"""P0 fail-closed / security regression gates. See docs/archive/plans/MERGED-PLAN.md §0a.

Each test reproduces a weakness that the current code either had or could
regress into, and asserts the hardened behaviour.
"""

from __future__ import annotations

import time

import pytest
from agentkit.core.agent import AgentResponse
from agentkit.core.loader import PythonTestCase
from agentkit.core.redaction import EvidencePolicy, RedactionConfig, Redactor
from agentkit.core.runner import _redact_assertions, _run_python_test, run_one
from agentkit.core.sandbox import Sandbox
from agentkit.core.schema import (
    Assertion,
    AssertionResult,
    Category,
    Risk,
    Status,
)
from agentkit.core.schema import (
    TestCase as SchemaTestCase,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def explicit_dev_auth(monkeypatch):
    monkeypatch.setenv("AGENTKIT_AUTH_MODE", "dev")

# --- scoring fails closed (covered in test_scoring.py::test_all_skipped_run_fails_closed)


# --- web run route: token required, paths outside allowlist rejected -------


def _web_client() -> TestClient:
    from agentkit.web.app import app

    return TestClient(app)


def test_post_runs_rejects_missing_token(monkeypatch):
    # With OIDC configured, an unauthenticated caller never reaches the runner.
    monkeypatch.setenv("AGENTKIT_AUTH_MODE", "oidc")
    monkeypatch.setenv("AGENTKIT_OIDC_JWKS_URL", "https://kc.test/certs")
    monkeypatch.setenv("AGENTKIT_OIDC_ISSUER", "https://kc.test/realms/agentkit")
    monkeypatch.setenv("AGENTKIT_OIDC_AUDIENCE", "agentkit-api")
    monkeypatch.setenv("AGENTKIT_OIDC_CLIENT_ID", "agentkit-web")
    monkeypatch.setenv("AGENTKIT_OIDC_REDIRECT_URI", "https://agentkit.test/auth/callback")
    client = _web_client()
    resp = client.post(
        "/runs",
        params={"target": "x", "packs": "y"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 401


def test_post_runs_rejects_path_outside_allowlist():
    client = _web_client()
    # An authorized caller (dev mode) with a target path escaping config/ and
    # packs/ must still be refused, so the route can never load an arbitrary
    # Python callable.
    resp = client.post(
        "/runs",
        params={"target": "/etc/passwd", "packs": "../../evil"},
    )
    assert resp.status_code == 400


# --- direct thread timeout must not yield a trusted sandbox diff -----------


class _SlowAgent:
    def run(self, input):  # noqa: A002 - mirror Agent signature
        time.sleep(0.5)
        return AgentResponse(text="done")


class _CountingSandbox(Sandbox):
    """Minimal sandbox whose snapshot changes over time, to prove that a
    post-timeout diff would be non-empty if we trusted it."""

    def __init__(self) -> None:
        self._n = 0

    def reset(self) -> None:
        self._n = 0

    def apply_setup(self, setup) -> None:  # noqa: ANN001
        pass

    def snapshot(self):
        self._n += 1
        return {"n": self._n}

    def diff(self, before, after):  # noqa: ANN001
        return {} if before == after else {"n": [before["n"], after["n"]]}


def test_direct_run_one_timeout_does_not_claim_a_trusted_diff():
    redactor = Redactor(RedactionConfig())
    test = SchemaTestCase(
        id="t.timeout.case",
        category=Category.reliability,
        input="hi",
        timeout_s=0.05,
        assertions=[Assertion(name="status_ok")],
    )
    result = run_one(_SlowAgent(), _CountingSandbox(), test, redactor)
    assert result.status == Status.error
    assert result.error == "timeout"
    # Only runner.run supplies the nested killable agent worker. A direct call
    # retains the thread fallback and must fail closed on timeout evidence.
    assert result.sandbox_diff is None


# --- redaction covers assertion details and error strings ------------------


def test_assertion_detail_is_redacted():
    redactor = Redactor(RedactionConfig())
    results = [
        AssertionResult(
            name="not_contains",
            passed=False,
            detail="response leaked sk-abcdefgh12345678 to the caller",
        )
    ]
    redacted = _redact_assertions(redactor, results)
    assert "sk-abcdefgh12345678" not in redacted[0].detail
    assert "redacted:api_key" in redacted[0].detail


class _FailingSandbox(_CountingSandbox):
    def reset(self) -> None:
        raise RuntimeError("sandbox failed with sk-abcdefgh12345678")


def test_runner_redacts_unexpected_exception_messages():
    test = SchemaTestCase(
        id="t.exception.case",
        category=Category.reliability,
        input="hi",
        assertions=[Assertion(name="status_ok")],
    )

    result = run_one(_SlowAgent(), _FailingSandbox(), test, Redactor(RedactionConfig()))

    assert result.status == Status.error
    assert "sk-abcdefgh12345678" not in result.error
    assert "redacted:api_key" in result.error


def test_python_runner_redacts_unexpected_exception_messages():
    test = PythonTestCase(
        id="python.exception.case",
        category=Category.reliability,
        risk=Risk.medium,
        fn=lambda agent, sandbox: None,
    )

    result = _run_python_test(
        _SlowAgent(),
        _FailingSandbox(),
        test,
        Redactor(RedactionConfig()),
        EvidencePolicy(),
    )

    assert result.status == Status.error
    assert "sk-abcdefgh12345678" not in result.error
    assert "redacted:api_key" in result.error


# ---- T15: egress allowlist (SSRF) -----------------------------------------

from agentkit.core.egress import (  # noqa: E402
    EgressError,
    EgressPolicy,
    validate_endpoint,
)

_ALLOWED = EgressPolicy.from_iterable(["agent.partner.test"])


def _resolves_to(*addresses: str):
    return lambda host, port: list(addresses)


def test_metadata_endpoint_is_rejected_before_any_request():
    policy = EgressPolicy.from_iterable(["169.254.169.254"])

    with pytest.raises(EgressError, match="non-public"):
        validate_endpoint(
            "https://169.254.169.254/latest/meta-data/",
            policy,
            _resolves_to("169.254.169.254"),
        )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
    ],
)
def test_hostname_resolving_to_a_private_address_is_rejected(address):
    with pytest.raises(EgressError, match="non-public"):
        validate_endpoint(
            "https://agent.partner.test/run", _ALLOWED, _resolves_to(address)
        )


def test_one_private_address_among_public_ones_rejects_the_whole_host():
    """A split-horizon answer must not be reachable at all."""
    with pytest.raises(EgressError, match="non-public"):
        validate_endpoint(
            "https://agent.partner.test/run",
            _ALLOWED,
            _resolves_to("93.184.216.34", "127.0.0.1"),
        )


def test_host_outside_the_allowlist_is_rejected_even_when_public():
    with pytest.raises(EgressError, match="allowlist"):
        validate_endpoint(
            "https://evil.test/run", _ALLOWED, _resolves_to("93.184.216.34")
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://agent.partner.test/run",
        "file:///etc/passwd",
        "gopher://agent.partner.test/",
        "https://user:pw@agent.partner.test/",
        "//agent.partner.test/run",
    ],
)
def test_only_https_without_url_credentials_is_accepted(endpoint):
    with pytest.raises(EgressError):
        validate_endpoint(endpoint, _ALLOWED, _resolves_to("93.184.216.34"))


@pytest.mark.parametrize(
    "host",
    ["AGENT.PARTNER.TEST", "agent.partner.test.", "  agent.partner.test  "],
)
def test_allowlist_matching_is_normalized_not_fuzzy(host):
    """Case, trailing dot, and padding normalize; substrings never match."""
    assert EgressPolicy.from_iterable([host]).allowed_hosts == frozenset(
        {"agent.partner.test"}
    )


@pytest.mark.parametrize(
    "impostor",
    [
        "https://agent.partner.test.evil.test/run",
        "https://evil-agent.partner.test/run",
        "https://notagent.partner.test/run",
    ],
)
def test_no_wildcard_or_suffix_matching(impostor):
    with pytest.raises(EgressError, match="allowlist"):
        validate_endpoint(impostor, _ALLOWED, _resolves_to("93.184.216.34"))


def test_connection_is_pinned_so_a_second_lookup_cannot_rebind():
    """The classic DNS-rebinding bypass: public on validation, private after.

    Nothing dials the hostname a second time, so the flip never lands. This is
    the test that fails if pinning is ever replaced by a preflight
    getaddrinfo() plus an ordinary request.
    """
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])

    def rebinding(host, port):
        return next(answers)

    validated = validate_endpoint(
        "https://agent.partner.test/run", _ALLOWED, rebinding
    )

    assert validated.pinned_url == "https://93.184.216.34:443/run"
    assert validated.host == "agent.partner.test"
    assert validated.host_header == "agent.partner.test"
    # The rebinding answer is still sitting in the iterator, unused.
    assert next(answers) == ["127.0.0.1"]


def test_ipv6_pinned_url_is_bracketed():
    validated = validate_endpoint(
        "https://agent.partner.test/run", _ALLOWED, _resolves_to("2606:2800:220:1::1")
    )

    assert validated.pinned_url == "https://[2606:2800:220:1::1]:443/run"


def test_http_agent_pins_the_address_and_refuses_redirects():
    import inspect

    from agentkit.core.agent import HTTPAgent
    from agentkit.core.config import HTTPSpec

    source = inspect.getsource(HTTPAgent.run)
    assert "follow_redirects=False" in source
    assert "sni_hostname" in source

    validated = validate_endpoint(
        "https://agent.partner.test/run", _ALLOWED, _resolves_to("93.184.216.34")
    )
    agent = HTTPAgent(HTTPSpec(type="http", endpoint=validated.url), endpoint=validated)
    assert agent.endpoint.pinned_url.startswith("https://93.184.216.34")


def test_local_escape_hatch_is_not_reachable_from_target_config():
    """allow_private is deployment-owned; no config field can set it."""
    import inspect

    from agentkit.core.config import HTTPSpec

    assert "allow_private" not in HTTPSpec.model_fields
    signature = inspect.signature(validate_endpoint)
    assert signature.parameters["allow_private"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["allow_private"].default is False


# ---- T15: secret resolution ------------------------------------------------

# Deliberately NOT sk-/Bearer-shaped: a builtin redaction pattern would mask
# it regardless, and the test would pass with the worker injection removed.
SECRET = "partner-token-9f3a2b1c4d5e"


def test_secrets_interpolate_from_the_mapping_not_the_environment(monkeypatch):
    import os

    from agentkit.core.config import load_target_dict

    monkeypatch.setenv("AGENT_TOKEN", "from-process-environment")
    raw = {
        "id": "t",
        "agent": {
            "type": "http",
            "endpoint": "https://agent.partner.test/run",
            "headers": {"authorization": "Bearer ${AGENT_TOKEN}"},
        },
    }

    scoped = load_target_dict(raw, secrets={"AGENT_TOKEN": "scoped-to-this-run"})

    assert scoped.agent.headers["authorization"] == "Bearer scoped-to-this-run"
    assert os.environ["AGENT_TOKEN"] == "from-process-environment"


def test_worker_never_puts_a_resolved_secret_into_os_environ(tmp_path, monkeypatch):
    """The secret reaches the run through an explicit mapping, not the process.

    Observed while the run is in flight, not just afterwards: a worker that set
    and then restored the variable would still expose it to every concurrent
    run in the process for the duration.
    """
    import os

    from agentkit.core.store import Store

    from agentkit import worker as worker_module

    monkeypatch.setenv("PARTNER_TOKEN", SECRET)
    seen: list[str] = []
    real_run = worker_module.run_tests

    def spy(target, tests, **kwargs):
        seen.extend(k for k, v in os.environ.items() if v == SECRET)
        return real_run(target, tests, **kwargs)

    monkeypatch.setattr(worker_module, "run_tests", spy)
    store = Store(str(tmp_path / "env.db"))
    store.save_target(
        "org-a",
        "echo-target",
        "Echo",
        {
            "id": "echo-target",
            "agent": {
                "type": "callable",
                "callable": "tests.test_security_p0:create_echoing_agent",
            },
            "evidence": {"redact": {"literals": ["${PARTNER_TOKEN}"]}},
        },
        secret_ref="env://PARTNER_TOKEN",
    )
    store.save_pack(
        "org-a",
        "p1",
        "Pack",
        [
            {
                "id": "leak.case",
                "category": "reliability",
                "input": "hi",
                "assertions": [{"name": "response_nonempty"}],
            }
        ],
    )
    store.enqueue_job("org-a", "echo-target", "p1")

    worker_module.work_once(store, "w1")

    # PARTNER_TOKEN is the deployment's own provisioning, which the worker read
    # from. It must not have grown a second copy under the config's var name.
    assert seen == ["PARTNER_TOKEN"], seen


def test_resolved_secret_is_added_to_the_run_redactor(tmp_path, monkeypatch):
    """A resolved credential is masked in evidence even though it is never stored."""
    from agentkit.core.store import Store
    from agentkit.worker import work_once

    monkeypatch.setenv("PARTNER_TOKEN", SECRET)
    store = Store(str(tmp_path / "secrets.db"))
    store.save_target(
        "org-a",
        "echo-target",
        "Echo",
        {
            "id": "echo-target",
            "agent": {
                "type": "callable",
                "callable": "tests.test_security_p0:create_echoing_agent",
            },
            # Deliberately NO evidence.redact.literals: those would interpolate
            # to the secret and mask it regardless of the worker. Only the
            # worker's injection can make this pass.
        },
        secret_ref="env://PARTNER_TOKEN",
    )
    store.save_pack(
        "org-a",
        "p1",
        "Pack",
        [
            {
                "id": "leak.case",
                "category": "reliability",
                "input": "hi",
                "assertions": [{"name": "response_nonempty"}],
            }
        ],
    )
    job_id = store.enqueue_job("org-a", "echo-target", "p1")

    work_once(store, "w1")

    job = store.get_job("org-a", job_id)
    assert job.state == "done", job.error
    run, _report = store.get_run("org-a", job.run_id)
    assert SECRET not in run.model_dump_json()
    # The stored config never held the literal either.
    assert SECRET not in str(store.get_target("org-a", "echo-target"))


def test_unprovisioned_secret_ref_fails_permanently(tmp_path, monkeypatch):
    from agentkit.worker import PermanentJobError, resolve_secret

    monkeypatch.delenv("NOT_PROVISIONED", raising=False)
    with pytest.raises(PermanentJobError, match="not provisioned"):
        resolve_secret("env://NOT_PROVISIONED")
    with pytest.raises(PermanentJobError, match="unsupported secret_ref scheme"):
        resolve_secret("vault://some/path")
    assert resolve_secret(None) == {}


def create_echoing_agent():
    def _echo(input: str) -> str:
        return SECRET

    return _echo
