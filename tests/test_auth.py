"""JWT principal resolution (`agentkit.web.auth`).

Tokens are signed with a keypair generated in-process; no Keycloak is started.
Every negative case must be a 401 -- an assertion that a bad token yields *some*
error is not enough, because a 500 or a silently-accepted claim would pass it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from agentkit.web import auth
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

ISSUER = "https://keycloak.test/realms/agentkit"
AUDIENCE = "agentkit-web"
JWKS_URL = "https://keycloak.test/realms/agentkit/protocol/openid-connect/certs"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=_KEY, alg="RS256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "email": "user@acme.test",
        "org_id": "acme",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg)


def _request(token: str | None) -> SimpleNamespace:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(headers=headers)


@pytest.fixture
def oidc(monkeypatch):
    monkeypatch.setenv("AGENTKIT_OIDC_JWKS_URL", JWKS_URL)
    monkeypatch.setenv("AGENTKIT_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AGENTKIT_OIDC_AUDIENCE", AUDIENCE)
    # Stand in for the network-backed key set. `.uri` must match so `_client`
    # reuses the stub rather than constructing a real PyJWKClient.
    stub = SimpleNamespace(
        uri=JWKS_URL,
        get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=_KEY.public_key()),
    )
    monkeypatch.setattr(auth, "_jwks_client", stub)
    return stub


def _expect_401(request):
    with pytest.raises(HTTPException) as exc:
        auth.current_principal(request)
    assert exc.value.status_code == 401


def test_valid_token_yields_principal(oidc):
    principal = auth.current_principal(_request(_token()))
    assert principal == ("acme", "user-1", "user@acme.test")
    assert principal.org_id == "acme"


def test_missing_header_is_401(oidc):
    _expect_401(_request(None))


def test_non_bearer_scheme_is_401(oidc):
    _expect_401(SimpleNamespace(headers={"authorization": f"Basic {_token()}"}))


def test_expired_token_is_401(oidc):
    _expect_401(_request(_token(exp=int(time.time()) - 60)))


def test_wrong_issuer_is_401(oidc):
    _expect_401(_request(_token(iss="https://evil.test/realms/agentkit")))


def test_wrong_audience_is_401(oidc):
    _expect_401(_request(_token(aud="some-other-client")))


def test_bad_signature_is_401(oidc):
    _expect_401(_request(_token(key=_OTHER_KEY)))


def test_unsigned_token_is_401(oidc):
    """`alg: none` must not bypass verification."""
    _expect_401(_request(jwt.encode({"iss": ISSUER, "sub": "x"}, None, algorithm="none")))


def test_hmac_signed_with_public_key_is_401(oidc):
    """The classic RS256->HS256 confusion attack: reject any non-RS256 alg."""
    public_pem = _KEY.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # PyJWT refuses to *sign* this, so the attacker's token is built by hand --
    # which is what a real attacker does anyway.
    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "org_id": "acme",
             "exp": int(time.time()) + 300}
        ).encode()
    )
    signing_input = header + b"." + payload
    signature = b64(hmac.new(public_pem, signing_input, hashlib.sha256).digest())
    _expect_401(_request((signing_input + b"." + signature).decode()))


def test_missing_org_claim_is_401(oidc):
    _expect_401(_request(_token(org_id=None)))


def test_missing_sub_is_401(oidc):
    _expect_401(_request(_token(sub=None)))


def test_org_id_query_parameter_is_ignored(oidc):
    """org_id comes from the claim only, never from the request."""
    request = SimpleNamespace(
        headers={"authorization": f"Bearer {_token()}"},
        query_params={"org_id": "victim-org"},
    )
    assert auth.current_principal(request).org_id == "acme"


def test_unconfigured_falls_back_to_dev_principal(monkeypatch):
    for var in (
        "AGENTKIT_OIDC_JWKS_URL",
        "AGENTKIT_OIDC_ISSUER",
        "AGENTKIT_OIDC_AUDIENCE",
    ):
        monkeypatch.delenv(var, raising=False)
    assert not auth.auth_enabled()
    assert auth.current_principal(_request(None)) == auth.DEV_PRINCIPAL


def test_partial_config_raises_instead_of_falling_back(monkeypatch):
    """A typo'd variable must not silently disable authentication."""
    monkeypatch.setenv("AGENTKIT_OIDC_ISSUER", ISSUER)
    monkeypatch.delenv("AGENTKIT_OIDC_JWKS_URL", raising=False)
    monkeypatch.delenv("AGENTKIT_OIDC_AUDIENCE", raising=False)
    with pytest.raises(auth.AuthConfigError):
        auth.auth_enabled()
    with pytest.raises(auth.AuthConfigError):
        auth.current_principal(_request(_token()))
