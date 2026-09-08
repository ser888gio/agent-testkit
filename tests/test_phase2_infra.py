"""Static system-boundary checks for the checked-in Phase 2 deployment contract."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
COMPOSE_PATH = ROOT / "infra" / "docker-compose.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


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

    for name in (
        "AGENTAUDIT_OIDC_ISSUER",
        "AGENTAUDIT_OIDC_JWKS_URL",
        "AGENTAUDIT_OIDC_TOKEN_URL",
        "AGENTAUDIT_OIDC_AUTH_URL",
        "AGENTAUDIT_OIDC_AUDIENCE",
        "AGENTAUDIT_OIDC_CLIENT_ID",
        "AGENTAUDIT_OIDC_REDIRECT_URI",
    ):
        assert environment[name].startswith(f"${{{name}:?")
    # Secure cookies are the default; only an explicit override relaxes them.
    assert (
        environment["AGENTAUDIT_SESSION_COOKIE_SECURE"] == "${AGENTAUDIT_SESSION_COOKIE_SECURE:-1}"
    )
    # TLS terminates at the reverse proxy, so nothing binds beyond loopback.
    assert services["agentaudit"]["ports"] == ["127.0.0.1:8000:8000"]
    # The identity provider is hosted, so the only thing the app waits for is
    # the migration job.
    assert (
        services["agentaudit"]["depends_on"]["migrate"]["condition"]
        == "service_completed_successfully"
    )


def test_compose_healthcheck_is_a_single_valid_python_command():
    """YAML escapes in a double-quoted scalar expand to real newlines, which
    used to split the probe's `python -c` source across lines and fail with
    SyntaxError -- leaving a serving container permanently unhealthy."""
    probe = _compose()["services"]["agentaudit"]["healthcheck"]["test"][1]
    assert "\n" not in probe
    source = probe.split("python -c ", 1)[1].strip('"')
    compile(source, "<healthcheck>", "exec")


def test_data_mounting_services_carry_the_same_container_hardening():
    """The internet-facing service guards the same volume the worker does."""
    services = _compose()["services"]
    for name in ("agentaudit", "worker"):
        service = services[name]
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert service["pids_limit"] == 512, name
        assert service["mem_limit"] == "2g", name
        # read_only leaves no writable temp dir, and uvicorn/Python want one.
        assert "/tmp" in service["tmpfs"], name
