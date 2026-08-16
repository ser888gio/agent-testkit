"""Static system-boundary checks for the checked-in Phase 2 deployment contract."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
COMPOSE_PATH = ROOT / "infra" / "docker-compose.yml"
REALM_PATH = ROOT / "infra" / "keycloak" / "agentaudit-realm.json"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _realm() -> dict:
    return json.loads(REALM_PATH.read_text(encoding="utf-8"))


def test_compose_build_context_and_dockerfile_exist():
    compose = _compose()
    for service_name in ("migrate", "agentaudit"):
        build = compose["services"][service_name]["build"]
        context = (COMPOSE_PATH.parent / build["context"]).resolve()
        dockerfile = context / build["dockerfile"]
        assert context == ROOT.resolve()
        assert dockerfile.is_file()


def test_compose_enables_oidc_and_binds_public_services_to_loopback():
    services = _compose()["services"]
    environment = services["agentaudit"]["environment"]
    assert environment["AGENTAUDIT_AUTH_MODE"] == "oidc"
    assert environment["AGENTAUDIT_OIDC_AUDIENCE"] == "agentaudit-api"
    assert environment["AGENTAUDIT_OIDC_TOKEN_URL"].startswith("http://keycloak:8080/")
    assert services["agentaudit"]["ports"] == ["127.0.0.1:8000:8000"]
    assert services["keycloak"]["ports"] == ["127.0.0.1:8080:8080"]
    assert services["agentaudit"]["depends_on"]["keycloak"]["condition"] == "service_healthy"


def test_compose_requires_secrets_instead_of_shipping_defaults():
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    for name in (
        "KEYCLOAK_DB_PASSWORD",
        "KEYCLOAK_ADMIN_USERNAME",
        "KEYCLOAK_ADMIN_PASSWORD",
        "AGENTAUDIT_CI_ACME_SECRET",
        "AGENTAUDIT_DEMO_USER_PASSWORD",
    ):
        assert f"${{{name}:?" in text


def test_realm_uses_code_pkce_and_client_credentials_only():
    realm = _realm()
    clients = {client["clientId"]: client for client in realm["clients"]}
    web = clients["agentaudit-web"]
    assert web["publicClient"] is True
    assert web["standardFlowEnabled"] is True
    assert web["directAccessGrantsEnabled"] is False
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"

    service = clients["agentaudit-ci-acme"]
    assert service["serviceAccountsEnabled"] is True
    assert service["standardFlowEnabled"] is False
    assert service["directAccessGrantsEnabled"] is False
    assert service["secret"] == "${AGENTAUDIT_CI_ACME_SECRET}"
    role_mapper = next(
        mapper
        for mapper in service["protocolMappers"]
        if mapper["protocolMapper"] == "oidc-hardcoded-role-mapper"
    )
    assert role_mapper["config"]["role"] == "admin"


def test_access_tokens_receive_org_role_and_api_audience_claims():
    realm = _realm()
    scopes = {scope["name"]: scope for scope in realm["clientScopes"]}
    org_mapper = scopes["org"]["protocolMappers"][0]
    assert org_mapper["config"]["claim.name"] == "org_id"
    assert org_mapper["config"]["access.token.claim"] == "true"
    assert org_mapper["config"]["id.token.claim"] == "false"

    audience_mapper = scopes["agentaudit-api-audience"]["protocolMappers"][0]
    assert audience_mapper["config"]["included.client.audience"] == "agentaudit-api"
    assert audience_mapper["config"]["access.token.claim"] == "true"
    assert {role["name"] for role in realm["roles"]["realm"]} == {"admin", "viewer"}
