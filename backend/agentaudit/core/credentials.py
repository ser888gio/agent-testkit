"""What a credential looks like, and where one is allowed to appear.

Two modules used to answer this independently. `redaction.py` knew the shape of
an API key so it could mask one out of evidence; `store.py` knew the shape of an
API key so it could refuse to persist one in a target config -- with its own
regex, private, ~110 lines of it. The two spellings had already diverged: the
store knew that `Basic ...` is a credential and the redactor did not, so a
`Basic` header was rejected at the config door and masked nowhere in evidence.

One vocabulary now, used two ways:

- `Redactor` composes `CREDENTIAL_PATTERNS` with its own PII patterns and masks.
- `Store.save_target` calls `scan_config` and refuses the write.

Teaching agentaudit a new key format is one edit here rather than two edits in
two modules, one of them private.

This module imports nothing from `agentaudit`. It sits below both `redaction`
and `store`, which is what keeps the runner / control-plane split intact.

## Literals versus references

A config may not contain a credential; it may contain a *reference* to one --
`${AGENT_TOKEN}`, resolved from the environment at load time. The distinction is
the whole point of the check, so it is drawn explicitly:

- `is_reference` -- `${VAR}`, optionally behind `Bearer `/`Basic ` when the key
  is an authorization header, since that is how a real header is written.
- `looks_like_secret` -- a literal that matches a credential pattern anywhere in
  a string, regardless of the key it sits under.
- `is_sensitive_key` -- a key whose *name* means the value is a credential, so
  an unrecognised literal under `password:` is still refused.

All three are needed. Key-name matching alone misses a token pasted into a URL;
pattern matching alone misses a password that happens to look like a word.
"""

from __future__ import annotations

import re

# Credential literals. Shared with `redaction.Redactor`, which masks each one
# under its own name, so these stay (name, pattern) pairs rather than one blob.
CREDENTIAL_PATTERNS: list[tuple[str, str]] = [
    ("api_key", r"sk-[A-Za-z0-9_-]{8,}"),
    # `Basic` belongs here as much as `Bearer`: both carry a credential, and the
    # store has always rejected both.
    ("bearer", r"(?:Bearer|Basic)\s+[A-Za-z0-9._-]+"),
]

_CREDENTIAL_RE = re.compile(
    "|".join(f"(?:{pattern})" for _, pattern in CREDENTIAL_PATTERNS), re.IGNORECASE
)

# Key names whose value is a credential whatever it looks like. `literals` is
# here because `RedactionConfig.literals` holds the exact strings to mask, which
# are by definition the secrets themselves.
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "literals",
        "password",
        "proxy_authorization",
        "secret",
        "token",
        "x_api_key",
    }
)

_SENSITIVE_SUFFIXES = ("_api_key", "_password", "_secret", "_token")

# `${VAR}` -- an environment reference, resolved at config load time.
ENV_REFERENCE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")

# `env://VAR` and friends -- an external secret locator, stored in its own
# column rather than inside the config blob.
SECRET_REF_RE = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)

_ENV_REFERENCE_ONLY = re.compile(r"\s*\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*")
_AUTH_REFERENCE_ONLY = re.compile(
    r"\s*(?:(?:Bearer|Basic)\s+)?\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*", re.IGNORECASE
)

_REFERENCE_PLACEHOLDER = "agentaudit-secret-reference"


class CredentialError(ValueError):
    """A literal credential was found where only a reference is allowed."""


def is_sensitive_key(key: str) -> bool:
    """Does this key's *name* mean its value is a credential?"""
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return normalized in SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def looks_like_secret(text: str) -> bool:
    """Does a credential literal appear anywhere in this string?"""
    return bool(_CREDENTIAL_RE.search(text))


def is_secret_ref(text: str) -> bool:
    """Is this a well-formed external secret locator, e.g. `env://AGENT_TOKEN`?"""
    return bool(SECRET_REF_RE.fullmatch(text.strip()))


def is_reference(value: object, *, authorization: bool = False) -> bool:
    """Is this value *only* an environment reference, and never a literal?

    A list counts when every element does, and an empty list does not: nothing
    to resolve is not the same as a reference.
    """
    if isinstance(value, list):
        return bool(value) and all(
            is_reference(item, authorization=authorization) for item in value
        )
    if not isinstance(value, str):
        return False
    pattern = _AUTH_REFERENCE_ONLY if authorization else _ENV_REFERENCE_ONLY
    return bool(pattern.fullmatch(value))


def contains_reference(value: object) -> bool:
    """Does any sensitive key anywhere in this structure hold a reference?

    Used to decide whether a config needs an accompanying `secret_ref`: a config
    that references `${AGENT_TOKEN}` is unusable without one.
    """
    if isinstance(value, dict):
        return any(
            (
                is_sensitive_key(str(key))
                and is_reference(item, authorization="authorization" in str(key).lower())
            )
            or contains_reference(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_reference(item) for item in value)
    return False


def _check_key(key_text: str, item: object, path: tuple[str, ...]) -> None:
    if key_text == "secret_ref":
        raise CredentialError("secret_ref must be stored separately from config_json")
    if is_sensitive_key(key_text) and not is_reference(
        item, authorization="authorization" in key_text.lower()
    ):
        location = ".".join((*path, key_text))
        raise CredentialError(f"literal credential is not allowed in config_json at {location}")


def scan_config(value: object, path: tuple[str, ...] = ()) -> None:
    """Raise `CredentialError` if a literal credential appears anywhere.

    Walks the whole structure rather than a known set of fields: a config is
    partner-supplied, and the field a token gets pasted into is not predictable.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            _check_key(key_text, item, path)
            scan_config(item, (*path, key_text))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            scan_config(item, (*path, str(index)))
        return
    if isinstance(value, str) and looks_like_secret(value):
        location = ".".join(path) or "<root>"
        raise CredentialError(f"literal credential is not allowed in config_json at {location}")


def mask_references(value: object) -> object:
    """Replace every `${VAR}` with a placeholder that survives config validation.

    A stored config is re-validated on read, and the loader resolves `${VAR}`
    from the environment -- which, on a machine that does not have the variable
    set, would fail a validation that is only checking the config's shape.
    """
    if isinstance(value, str):
        return ENV_REFERENCE_RE.sub(_REFERENCE_PLACEHOLDER, value)
    if isinstance(value, dict):
        return {key: mask_references(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_references(item) for item in value]
    return value
