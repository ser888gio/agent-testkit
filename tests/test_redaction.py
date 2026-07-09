import pytest

from agentkit.core.redaction import (
    EvidencePolicy,
    RedactionConfig,
    RedactionPattern,
    Redactor,
)


def test_api_key_masked():
    r = Redactor(RedactionConfig())
    out = r.redact_text("key is sk-abcdefgh12345678")
    assert "sk-abcdefgh12345678" not in out
    assert "«redacted:api_key»" in out


def test_email_masked():
    r = Redactor(RedactionConfig())
    out = r.redact_text("mail me a@b.com please")
    assert "a@b.com" not in out
    assert "«redacted:email»" in out


def test_iban_masked():
    r = Redactor(RedactionConfig())
    out = r.redact_text("IBAN: DE89370400440532013000")
    assert "DE89370400440532013000" not in out
    assert "«redacted:iban»" in out


def test_16_digit_account_masked():
    r = Redactor(RedactionConfig())
    out = r.redact_text("card 4111111111111111")
    assert "4111111111111111" not in out


def test_nested_payload_masked_recursively_and_original_unchanged():
    r = Redactor(RedactionConfig())
    payload = {
        "headers": {"Authorization": "Bearer abc.def-123"},
        "body": ["mail me a@b.com", {"note": "sk-abcdefgh12345678"}],
    }
    out = r.redact(payload)
    assert out["headers"]["Authorization"] == "«redacted:bearer»"
    assert "a@b.com" not in out["body"][0]
    assert "sk-abcdefgh12345678" not in out["body"][1]["note"]
    # original untouched
    assert payload["headers"]["Authorization"] == "Bearer abc.def-123"
    assert payload["body"][0] == "mail me a@b.com"


def test_literal_secret_masked():
    r = Redactor(RedactionConfig(literals=["my-super-secret"]))
    out = r.redact_text("token=my-super-secret")
    assert "my-super-secret" not in out
    assert "«redacted»" in out


def test_evidence_policy_store_flags_default_true():
    policy = EvidencePolicy()
    assert policy.store_request is True
    assert policy.store_response is True


def test_bad_custom_regex_raises_at_construction():
    with pytest.raises(ValueError, match="invalid redaction pattern"):
        Redactor(RedactionConfig(patterns=[RedactionPattern(name="bad", regex="(")]))
