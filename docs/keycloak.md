# Identity and local Keycloak

Phase 2 uses Keycloak for identity and organization membership. AgentKit remains
responsible for application authorization: `viewer` is read-only and `admin` may launch
runs and author tests.

## Start the local stack

```bash
cp infra/.env.example infra/.env
# Replace every placeholder in infra/.env with a random local value.
docker compose --env-file infra/.env -f infra/docker-compose.yml up --build --wait
```

The dashboard is available at `http://localhost:8000`. Opening it redirects to Keycloak's
Authorization Code + PKCE login. Direct Access Grants are disabled. Partner automation uses
one confidential service-account client per organization and the client-credentials grant.
Compose keeps browser-facing issuer/authorization URLs on `localhost:8080` while using internal
`keycloak:8080` URLs for the server-side token exchange and JWKS fetch.

Both human and service-account access tokens contain:

- `aud: agentkit-api`
- one scalar `org_id`
- a coarse realm role (`admin` or `viewer`)

The example user starts as a viewer. Grant `admin` only when mutation access is intended.

To smoke-test the service account without using a human password grant:

```bash
export AGENTKIT_CI_ACME_SECRET='the value placed in infra/.env'
TOKEN=$(curl --fail --silent --show-error \
  -X POST http://localhost:8080/realms/agentkit/protocol/openid-connect/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode grant_type=client_credentials \
  --data-urlencode client_id=agentkit-ci-acme \
  --data-urlencode client_secret="$AGENTKIT_CI_ACME_SECRET" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
TOKEN="$TOKEN" python -c 'import base64,json,os; p=os.environ["TOKEN"].split(".")[1]; print(json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4))))'
```

The decoded payload must contain `org_id: acme`, `agentkit-api` in `aud`, and `admin` in
`realm_access.roles`. This decoding command only inspects the smoke-test token; AgentKit itself
always verifies the signature and registered claims.

## Realm lifecycle

`infra/keycloak/agentkit-realm.json` is bootstrap configuration. Keycloak intentionally
skips startup import when the realm already exists, so changing the JSON does not reconcile
an existing Keycloak database. For local development, recreate the Keycloak database volume
when you intentionally want a clean import. For hosted environments, apply reviewed realm
changes through a versioned deployment job or the Admin API; do not rely on `--import-realm`
as a configuration controller.

Access tokens live for 60 seconds in the checked-in development realm. Disabling a user
prevents refresh/new sessions; already-issued self-contained tokens remain usable until
their short expiry.
