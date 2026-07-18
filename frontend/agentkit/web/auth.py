"""OIDC principal resolution for the dashboard.

Identity comes from a Keycloak-issued JWT. `org_id` is read from the validated
claim set and nowhere else -- never from a query parameter, path segment, or
form field -- because that claim is what every `Store` call is scoped by.
"""

from __future__ import annotations

import os
from typing import NamedTuple

import jwt
from agentkit.core.store import DEFAULT_ORG
from fastapi import HTTPException, Request
from jwt import PyJWKClient

# Algorithms accepted for the signature. Pinning this rejects `alg: none` and
# the HS256-with-the-public-key confusion attack.
_ALGORITHMS = ["RS256"]

# Claims that must be present and verified. PyJWT checks `exp`/`iss`/`aud`
# itself once they are required and the expected values are passed in.
_REQUIRED_CLAIMS = ["exp", "iss", "aud", "sub"]

ORG_CLAIM = "org_id"


class Principal(NamedTuple):
    org_id: str
    subject: str
    email: str


class _Settings(NamedTuple):
    jwks_url: str
    issuer: str
    audience: str


_ENV_VARS = (
    "AGENTKIT_OIDC_JWKS_URL",
    "AGENTKIT_OIDC_ISSUER",
    "AGENTKIT_OIDC_AUDIENCE",
)


class AuthConfigError(RuntimeError):
    """OIDC is partially configured, so neither mode can be chosen safely."""


def _settings() -> _Settings | None:
    """Read OIDC config from the environment, or None when unconfigured.

    All three variables or none. A partial config raises rather than falling
    back to dev mode: a typo in one variable would otherwise silently disable
    authentication on a deployment that meant to enable it.
    """
    values = [os.environ.get(name) for name in _ENV_VARS]
    if not any(values):
        return None
    if not all(values):
        missing = [n for n in _ENV_VARS if not os.environ.get(n)]
        raise AuthConfigError(f"OIDC is partially configured; missing: {missing}")
    return _Settings(*values)


# ponytail: one module-global client. PyJWKClient already caches the key set and
# refetches once on an unknown `kid`, which is the rotation behaviour we need.
_jwks_client: PyJWKClient | None = None


def _client(jwks_url: str) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None or _jwks_client.uri != jwks_url:
        _jwks_client = PyJWKClient(jwks_url)
    return _jwks_client


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    return token.strip()


# Single-tenant fallback for `agentkit ui` and the test suite. Only reachable
# when no OIDC issuer is configured, which also means the app must stay bound to
# loopback (see .claude/rules/security-sensitive.md).
DEV_PRINCIPAL = Principal(org_id=DEFAULT_ORG, subject="dev", email="dev@localhost")


def auth_enabled() -> bool:
    return _settings() is not None


def current_principal(request: Request) -> Principal:
    """Resolve the caller, or raise 401.

    Every failure mode -- absent, malformed, expired, wrong issuer, wrong
    audience, bad signature, missing org claim -- is the same 401. Callers get
    no signal about which check failed.
    """
    settings = _settings()
    if settings is None:
        return DEV_PRINCIPAL

    token = _bearer(request)
    try:
        signing_key = _client(settings.jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            issuer=settings.issuer,
            audience=settings.audience,
            options={"require": _REQUIRED_CLAIMS},
        )
    except Exception as exc:  # noqa: BLE001 - every failure is an opaque 401
        raise HTTPException(status_code=401, detail="invalid token") from exc

    org_id = claims.get(ORG_CLAIM)
    if not isinstance(org_id, str) or not org_id:
        raise HTTPException(status_code=401, detail="invalid token")

    return Principal(
        org_id=org_id,
        subject=claims["sub"],
        email=claims.get("email", ""),
    )
