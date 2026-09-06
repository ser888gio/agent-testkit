# Deploying with Clerk on an Ionos VPS

Concrete instance of [`deploy-demo.md`](deploy-demo.md): Clerk as the identity
provider, one Ionos VPS, Caddy on the host. Read that document for the general
shape — build, TLS, verification, and the [limits of this
setup](deploy-demo.md#limits-of-this-setup). This one covers only what is
specific to Clerk and to Ionos.

`frontend/agentaudit/web/auth.py` was written against Clerk's claim shapes, so
this is configuration only — no code changes.

## 1. Clerk

### OAuth application

Dashboard → Configure → OAuth Applications. Register the redirect URI exactly,
including scheme and path:

```
https://<your-host>/auth/callback
```

Note the **Client ID**. `auth.py:_principal_from_token` requires the token's
`azp` claim to equal it, so a mismatch is a 403 with a valid-looking token.

### Organizations

Configure → Organizations → enable. **Every user must belong to one, with one
active at login.** A token without `org_id` is refused rather than defaulted —
defaulting it would merge tenants. Clerk marks a user who has not yet joined an
organization with `sts: "pending"`; those tokens are refused for the same
reason.

### Where the org claims come from

**Not from a JWT template.** Templates apply to Clerk *session* tokens
(`getToken({template})`); this deployment uses the OAuth authorization-code
flow, whose access token carries a fixed claim set and nothing else:

```
client_id, exp, iat, iss, jti, nbf, scope, sub
```

No template, scope, or dashboard setting adds `org_id` to that. So
`complete_browser_login` fetches identity from the **userinfo endpoint**
(`_userinfo` in `auth.py`) and passes it to `_principal_from_token` as
`identity`. The access token is still what gets signature-verified; userinfo
only names the user it already authenticated.

`AGENTAUDIT_OIDC_USERINFO_URL` overrides the endpoint; it defaults to
`<issuer>/oauth/userinfo`.

The role may arrive as a single string such as `org:admin` rather than a list.
`auth.py:_roles` accepts either shape and strips the `org:` prefix. A role that
is neither `admin` nor `viewer` after stripping yields a 403.

### Endpoints

Fetch the discovery document once and paste the values; nothing reads it at
runtime:

```bash
curl -s https://<instance>.clerk.accounts.dev/.well-known/oauth-authorization-server \
  | python3 -m json.tool
```

Map `issuer`, `authorization_endpoint`, `token_endpoint`, and `jwks_uri` onto
the `AGENTAUDIT_OIDC_*` variables in `infra/.env`. Use the values the document
returns rather than assuming the paths.

### Verify the claims before deploying

Decode a real token and confirm `org_id`, `roles`, and `azp` are present and
correctly shaped. Doing this first turns the most common failure into a
two-minute check instead of a login loop against a running stack.

## 2. Ionos

### Firewall

Ionos filters in front of the OS, so a host-level rule alone is not enough. In
Cloud Panel → Network → Firewall Policies allow **22, 80, 443** and nothing
else. Compose binds the app to `127.0.0.1:8000`, so 8000 must stay closed.

### Hostname

Each VPS gets a DNS name of the form `<id>.cserverhost.cloud`, which Caddy can
obtain a certificate for with no DNS setup. Use it, or point an A record for
your own domain at the VPS IPv4 address. Ionos VPS instances have no IPv6
address, so do not publish an AAAA record.

### Cloud metadata

`core/egress.py` rejects `169.254.169.254` at the application layer, but
[`../infra/CLAUDE.md`](../infra/CLAUDE.md) records an OS-level rule as the
deployment operator's responsibility:

```bash
iptables -I DOCKER-USER -d 169.254.169.254 -j DROP
DEBIAN_FRONTEND=noninteractive apt install -y iptables-persistent
```

`DOCKER-USER` is the correct chain: Docker's own rules are evaluated before
`INPUT`, so a rule added there would not apply to container traffic.

### Host packages

Ubuntu 24.04 ships Docker and Compose v2, but not Caddy:

```bash
apt update && apt install -y docker.io docker-compose-v2 git \
    debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

Caddyfile — this is configuration written to a file, not shell:

```bash
cat > /etc/caddy/Caddyfile <<'EOF'
<your-host> {
    reverse_proxy 127.0.0.1:8000
}
EOF
systemctl reload caddy
```

## 3. Run

A Clerk deploy starts three services:

```bash
cp infra/.env.example infra/.env     # fill the OIDC block, set AGENTAUDIT_DEMO_MODE=1
docker compose -f infra/docker-compose.yml build
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml ps
```

Then follow [`deploy-demo.md` §5](deploy-demo.md#5-verify), including the
cross-organization tenancy check.

## Sizing

A VPS 4-4-120 (4 vCore / 4 GB / 120 GB) runs the Clerk configuration
comfortably: the `worker` container is capped at `mem_limit: 2g` and the web
service is small.
