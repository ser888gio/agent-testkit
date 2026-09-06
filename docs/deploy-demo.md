# Hosting a demo instance

How to put agentaudit on a public URL behind TLS so someone else can log in and
use it. Covers hosting only:

- Identity provider setup — [`deploy-clerk.md`](deploy-clerk.md) for a worked
  Clerk deployment on an Ionos VPS. The hosted OIDC provider is configured
  through the environment variables below.
- What to actually show once logged in — [`demo.md`](demo.md).

Target shape: one small VPS, Docker Compose, Caddy terminating TLS on the host.
SQLite on a local volume, one worker. That is sized for a handful of reviewers,
not for a public launch — see [Limits](#limits-of-this-setup).

## 1. Build

The image needs a Node stage: `frontend/agentaudit/web/spa_dist/` is gitignored,
so without it `pip install` packages no dashboard and the app serves a
"bundle is not built yet" placeholder. `infra/Dockerfile` handles this.

```bash
docker compose -f infra/docker-compose.yml build
```

Verify the bundle actually shipped:

```bash
docker compose -f infra/docker-compose.yml run --rm --no-deps agentaudit \
  ls /opt/venv/lib/python3.12/site-packages/agentaudit/web/spa_dist
```

`index.html` must be listed. If it is not, the SPA stage failed and every page
will render the placeholder.

## 2. Configure

```bash
cp infra/.env.example infra/.env
```

Fill in the OIDC block. The endpoint URLs come from the provider's discovery
document — fetch it once and paste the values; nothing reads it at runtime:

```bash
curl -s https://<your-frontend-api>/.well-known/oauth-authorization-server | python -m json.tool
```

Then set, in `infra/.env`:

| Variable | Source |
| --- | --- |
| `AGENTAUDIT_OIDC_ISSUER` | discovery `issuer` |
| `AGENTAUDIT_OIDC_AUTH_URL` | discovery `authorization_endpoint` |
| `AGENTAUDIT_OIDC_TOKEN_URL` | discovery `token_endpoint` |
| `AGENTAUDIT_OIDC_JWKS_URL` | discovery `jwks_uri` |
| `AGENTAUDIT_OIDC_CLIENT_ID` | the OAuth application |
| `AGENTAUDIT_OIDC_AUDIENCE` | the API audience the tokens carry |
| `AGENTAUDIT_OIDC_REDIRECT_URI` | `https://demo.example.com/auth/callback` |
| `AGENTAUDIT_SESSION_COOKIE_SECURE` | `1` |

The redirect URI must also be registered with the provider, exactly, including
scheme and trailing path.

### Token claims

`agentaudit.web.auth` requires each access token to carry:

- `org_id` — the tenancy boundary, threaded into every store query
- `roles` — `admin` or `viewer`, as a list or a single string; an `org:` prefix
  is stripped
- `azp` — must equal the configured client id
- `sub`, `email`, `aud`, `exp`, `iss`

**Every demo user must belong to an organization**, with one active at login. A
token without `org_id` is refused, deliberately: defaulting it would merge
tenants. A provider that marks not-yet-joined users with `sts: "pending"` is
refused for the same reason.

Confirm with a real token before going further — decode one and check the claim
shape matches. Most first-deploy failures are a JWT template that does not emit
`org_id`, or emits roles under a different name.

### Demo mode

Set `AGENTAUDIT_DEMO_MODE=1` on the `agentaudit` service to hide target configs
a visitor cannot successfully run. The shipped HTTP targets point at a
nonexistent host, at loopback (refused by the worker's egress policy), or at a
credential template; in demo mode only in-process `callable` targets are offered.

## 3. TLS

Caddy runs on the host, not in Compose. Both container ports stay bound to
loopback — do not expose them.

`/etc/caddy/Caddyfile`:

```caddyfile
demo.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Point an A record at the VPS, open 80 and 443, keep 8000 closed. Caddy
provisions and renews the certificate.

`agentaudit ui` passes `proxy_headers=True` to uvicorn, so the app reads Caddy's
`X-Forwarded-Proto` and builds `https://` redirects.

## 4. Run

```bash
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml ps
```

`migrate` runs once and exits; `agentaudit` and `worker` stay up.

All services are `restart: unless-stopped`, so a host reboot brings them back.

The `agentaudit` healthcheck probes `GET /` and accepts 200 or 303. It sends
`Accept: text/html` and does not follow redirects — without the header the app
answers 401 rather than redirecting, and following the redirect would make
container liveness depend on the identity provider being reachable.

## 5. Verify

```bash
curl -sI https://demo.example.com | head -1        # 303
```

Then in a browser, from a machine that is not the VPS:

1. Load the URL, complete the login round-trip.
2. Enqueue a run against `treasury-agent.yaml`; confirm a score and a report.
3. Log in as a second user in the same organization — same runs visible.
4. Log in as a user in a *different* organization — none of those runs visible.
   This is the tenancy check; do not skip it.
5. Reboot the VPS and confirm everything returns.

Then walk [`demo.md`](demo.md) end to end against the hosted instance.

## Observability

```bash
docker compose -f infra/docker-compose.yml logs -f agentaudit
docker compose -f infra/docker-compose.yml logs -f worker
```

Both services rotate at 10 MB × 3 files. The web process logs at INFO, which is
what surfaces identity-provider warnings — the most likely failure on a fresh
deployment.

There is no metrics endpoint, tracing, or error tracking, by choice. Note that
redaction rules forbid logging raw agent requests and responses, so any future
observability work has to route around evidence data rather than dropping in a
generic instrumentation library.

## Limits of this setup

Known and accepted for a reviewed demo; each becomes real work before anything
wider.

- **No rate limiting.** `POST /api/runs/enqueue` queues work that spawns
  processes, and nothing throttles it. Acceptable only while every account is
  one you created by hand. **Enabling self-serve signup makes this urgent.**
- **Sessions are process-local.** Restarting the web container logs everyone
  out. Harmless; tell reviewers to log in again.
- **SQLite, one worker.** Fine at demo concurrency. Not a scaling story.
- **Cloud metadata endpoint.** `core/egress.py` blocks `169.254.169.254` at the
  application layer, but no Compose network driver blocks it portably. On a
  cloud VPS add a host firewall rule. Not blocking when every demo target runs
  in-process, but required before pointing the worker at partner endpoints.
  See [`infra/CLAUDE.md`](../infra/CLAUDE.md).
