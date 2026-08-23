"""The credential vocabulary, and the two places that must keep agreeing on it."""

from __future__ import annotations

import pytest

from agentaudit.core import credentials
from agentaudit.core.redaction import RedactionConfig, Redactor

# --- the divergence this module exists to prevent ---------------------------


def test_every_credential_shape_is_both_refused_and_masked():
    """The store used to know `Basic ...` is a credential while the redactor did not.

    A shape rejected at the config door but not masked in evidence is the worst
    of both: the partner cannot store it, and if it arrives in a response it is
    persisted in the clear. This walks the shared vocabulary and asserts both
    halves act on every entry, so adding a pattern to one place cannot silently
    skip the other.
    """
    redactor = Redactor(RedactionConfig())
    samples = [
        "sk-abcdefgh1234",
        "Bearer abc.def-123",
        "Basic dXNlcjpwYXNz",
    ]

    for sample in samples:
        assert credentials.looks_like_secret(sample), sample
        assert "«redacted:" in redactor.redact_text(sample), sample
        with pytest.raises(credentials.CredentialError, match="literal credential"):
            credentials.scan_config({"note": sample})


def test_credential_error_is_a_value_error():
    """Callers (Store.save_target, the web layer) catch ValueError."""
    assert issubclass(credentials.CredentialError, ValueError)


# --- key names --------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["api_key", "API-Key", "X-Api-Key", "authorization", "password", "client_secret"],
)
def test_sensitive_key_names_are_recognised_however_they_are_spelled(key):
    assert credentials.is_sensitive_key(key)


@pytest.mark.parametrize("key", ["openai_api_key", "db_password", "hmac_secret", "auth_token"])
def test_sensitive_suffixes_are_recognised(key):
    assert credentials.is_sensitive_key(key)


@pytest.mark.parametrize("key", ["endpoint", "timeout_s", "name", "tokens_used"])
def test_ordinary_keys_are_not_sensitive(key):
    assert not credentials.is_sensitive_key(key)


# --- literals versus references ---------------------------------------------


def test_env_reference_is_not_a_literal():
    assert credentials.is_reference("${AGENT_TOKEN}")
    assert not credentials.looks_like_secret("${AGENT_TOKEN}")


def test_authorization_reference_may_carry_its_scheme():
    """A real header is written `Bearer ${VAR}`; only auth keys may say so."""
    assert credentials.is_reference("Bearer ${AGENT_TOKEN}", authorization=True)
    assert credentials.is_reference("Basic ${AGENT_TOKEN}", authorization=True)
    assert not credentials.is_reference("Bearer ${AGENT_TOKEN}")


def test_partial_reference_is_not_a_reference():
    """`${VAR}-suffix` resolves to a literal, so it must not pass as a reference."""
    assert not credentials.is_reference("${AGENT_TOKEN}-extra")
    assert not credentials.is_reference("prefix-${AGENT_TOKEN}")


def test_empty_list_is_not_a_reference():
    """Nothing to resolve is not the same as a reference."""
    assert not credentials.is_reference([])
    assert credentials.is_reference(["${A}", "${B}"])
    assert not credentials.is_reference(["${A}", "literal"])


# --- scanning a config ------------------------------------------------------


def test_reference_under_a_sensitive_key_is_accepted():
    credentials.scan_config({"headers": {"authorization": "Bearer ${AGENT_TOKEN}"}})


def test_literal_under_a_sensitive_key_is_refused_even_if_it_looks_harmless():
    """Pattern matching alone would miss this; the key name is what catches it."""
    with pytest.raises(credentials.CredentialError, match="password"):
        credentials.scan_config({"db": {"password": "hunter2"}})


def test_literal_anywhere_is_refused_even_under_an_innocent_key():
    """Key matching alone would miss a token pasted into a URL."""
    with pytest.raises(credentials.CredentialError, match="endpoint"):
        credentials.scan_config({"endpoint": "https://x/?k=sk-abcdefgh1234"})


def test_error_names_the_path_to_the_offending_value():
    with pytest.raises(credentials.CredentialError, match=r"agent\.headers\.authorization"):
        credentials.scan_config({"agent": {"headers": {"authorization": "Bearer live-abc"}}})


def test_secret_ref_may_not_live_inside_the_config_blob():
    with pytest.raises(credentials.CredentialError, match="stored separately"):
        credentials.scan_config({"secret_ref": "env://AGENT_TOKEN"})


def test_scan_walks_lists():
    with pytest.raises(credentials.CredentialError, match=r"notes\.1"):
        credentials.scan_config({"notes": ["fine", "sk-abcdefgh1234"]})


# --- references and locators ------------------------------------------------


def test_contains_reference_only_counts_sensitive_keys():
    assert credentials.contains_reference({"headers": {"authorization": "Bearer ${T}"}})
    assert not credentials.contains_reference({"name": "${NOT_A_SECRET}"})


def test_mask_references_survives_validation_without_the_env_var_set():
    masked = credentials.mask_references({"h": {"authorization": "Bearer ${AGENT_TOKEN}"}})
    assert "${" not in masked["h"]["authorization"]
    assert masked["h"]["authorization"].startswith("Bearer ")


def test_secret_ref_must_be_an_opaque_locator():
    assert credentials.is_secret_ref("env://AGENT_TOKEN")
    assert credentials.is_secret_ref("  vault://team/agent  ")
    assert not credentials.is_secret_ref("AGENT_TOKEN")
    assert not credentials.is_secret_ref("")
