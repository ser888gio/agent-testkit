#!/usr/bin/env bash
# Provision an Ionos VPS and bring up agentaudit behind Caddy/TLS.
#
# Run as root ON THE VPS, from a checkout of this repo:
#
#   DEPLOY_HOST=demo.example.com bash infra/deploy-ionos.sh
#
# Idempotent: safe to re-run after fixing infra/.env or pulling new code.
#
# Prerequisites this script does NOT do for you (they need your Ionos/Clerk
# accounts, see docs/deploy-clerk.md):
#   - Cloud Panel firewall: allow 22, 80, 443 only. Port 8000 must stay closed.
#   - DNS: an A record for $DEPLOY_HOST -> this VPS IPv4. No AAAA (no IPv6).
#   - Clerk: OAuth app, Organizations enabled, every user in an org with a
#     role, redirect URI https://$DEPLOY_HOST/auth/callback. No JWT template
#     is involved: org_id/roles come from userinfo (see docs/deploy-clerk.md).
set -euo pipefail

: "${DEPLOY_HOST:?set DEPLOY_HOST to the public hostname, e.g. demo.example.com}"

cd "$(dirname "$0")/.."
readonly COMPOSE="docker compose -f infra/docker-compose.yml --env-file infra/.env"

log() { printf '\n=== %s\n' "$1"; }

log "Host packages"
# ponytail: apt-get is idempotent; re-running just no-ops on installed packages.
apt-get update
apt-get install -y docker.io docker-compose-v2 git curl \
    debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update && apt-get install -y caddy
fi

log "Block the cloud metadata endpoint"
# core/egress.py rejects this at the application layer; DOCKER-USER is the
# chain that actually covers container traffic (Docker's rules precede INPUT).
# -C tests for the rule first so re-runs don't stack duplicates.
iptables -C DOCKER-USER -d 169.254.169.254 -j DROP 2>/dev/null \
    || iptables -I DOCKER-USER -d 169.254.169.254 -j DROP
DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
netfilter-persistent save

log "Caddy -> 127.0.0.1:8000"
cat > /etc/caddy/Caddyfile <<EOF
$DEPLOY_HOST {
    reverse_proxy 127.0.0.1:8000
}
EOF
systemctl reload caddy || systemctl restart caddy

log "Config check"
if [ ! -f infra/.env ]; then
    cp infra/.env.example infra/.env
    cat >&2 <<EOF

infra/.env was just created from the example and still holds placeholders.
Fill in the AGENTAUDIT_OIDC_* block from Clerk's discovery document:

  curl -s https://<instance>.clerk.accounts.dev/.well-known/oauth-authorization-server | python3 -m json.tool

Set AGENTAUDIT_OIDC_REDIRECT_URI=https://$DEPLOY_HOST/auth/callback
Set AGENTAUDIT_DEMO_MODE=1 for an instance strangers can log into.

Then re-run this script.
EOF
    exit 1
fi

if grep -q 'your-instance.example.com' infra/.env; then
    echo "infra/.env still contains example OIDC values -- fill them in first." >&2
    exit 1
fi

log "Build"
$COMPOSE build

# The #1 first-deploy failure: spa_dist is gitignored, so if the Node stage
# silently failed every page serves app.py's "not built yet" placeholder.
log "Verify the SPA bundle shipped inside the wheel"
$COMPOSE run --rm --no-deps agentaudit \
    ls /opt/venv/lib/python3.12/site-packages/agentaudit/web/spa_dist/index.html

log "Start (migrate runs once and exits)"
$COMPOSE up -d
$COMPOSE ps

log "Wait for health"
for _ in $(seq 1 30); do
    status="$(docker inspect --format='{{.State.Health.Status}}' infra-agentaudit-1 2>/dev/null || echo missing)"
    [ "$status" = healthy ] && break
    [ "$status" = unhealthy ] && { $COMPOSE logs --tail=50 agentaudit; exit 1; }
    sleep 5
done
echo "health: ${status:-unknown}"

log "Verify"
# ponytail: the app is already health-checked above; this hop also crosses DNS
# and Caddy, which the VPS cannot always resolve for its own public name. Report
# it, never fail the deploy on it.
code="$(curl -sk -o /dev/null -w '%{http_code}' "https://$DEPLOY_HOST/" || echo "curl-failed")"
echo "GET https://$DEPLOY_HOST/ -> $code (expect 303)"

cat <<EOF

Deployed. Remaining checks are manual (docs/deploy-demo.md section 5), from a
machine that is not this VPS:

  1. Load https://$DEPLOY_HOST/ and complete the login round-trip.
  2. Enqueue a run against treasury-agent.yaml; confirm a score and a report.
  3. Log in as a second user in the same org -- same runs visible.
  4. Log in as a user in a DIFFERENT org -- none of those runs visible.
     This is the tenancy check. Do not skip it.
  5. Reboot the VPS and confirm everything returns.
  6. Remove a user from the Clerk org and confirm a mutating request now fails
     inside their still-live session.
  7. $COMPOSE exec agentaudit sqlite3 /data/agentaudit.db "PRAGMA journal_mode;"
     must print wal.

Logs: $COMPOSE logs -f agentaudit
EOF
