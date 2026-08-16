"""OIDC authentication, browser sessions, and coarse route authorization."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, replace
from urllib import error, parse
from urllib import request as urlrequest

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from jwt import exceptions as jwt_exceptions

from agentkit.core.store import DEFAULT_ORG

_LOG = logging.getLogger(__name__)
_ALGORITHMS = ["RS256"]
_REQUIRED_CLAIMS = ["exp", "iss", "aud", "sub", "typ"]
ORG_CLAIM = "org_id"
SESSION_COOKIE = "agentkit_session"
LOGIN_STATE_COOKIE = "agentkit_login_state"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_IDP_UNAVAILABLE = "identity provider unavailable"
_INVALID_TOKEN = "invalid token"


@dataclass(frozen=True)
class Principal:
    org_id: str
    subject: str
    email: str
    roles: frozenset[str]
    auth_method: str = "bearer"
    csrf_token: str = ""

    @property
    def can_mutate(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True)
class _Settings:
    jwks_url: str
    issuer: str
    audience: str
    client_id: str
    redirect_uri: str
    token_endpoint: str

    @property
    def authorization_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/protocol/openid-connect/auth"

    @property
    def token_url(self) -> str:
        return self.token_endpoint

    @property
    def logout_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/protocol/openid-connect/logout"

    @property
    def cookie_secure(self) -> bool:
        configured = os.environ.get("AGENTKIT_SESSION_COOKIE_SECURE")
        if configured is not None:
            return configured.lower() not in {"0", "false", "no"}
        return self.redirect_uri.startswith("https://")


@dataclass(frozen=True)
class _LoginAttempt:
    verifier: str
    next_url: str
    expires_at: float


@dataclass(frozen=True)
class _Session:
    principal: Principal
    expires_at: float


_OIDC_ENV_VARS = (
    "AGENTKIT_OIDC_JWKS_URL",
    "AGENTKIT_OIDC_ISSUER",
    "AGENTKIT_OIDC_AUDIENCE",
    "AGENTKIT_OIDC_CLIENT_ID",
    "AGENTKIT_OIDC_REDIRECT_URI",
)


class AuthConfigError(RuntimeError):
    """Authentication mode is absent, invalid, or incompletely configured."""


def _settings() -> _Settings | None:
    """Return OIDC settings or the explicitly requested loopback dev mode."""
    mode = os.environ.get("AGENTKIT_AUTH_MODE", "").strip().lower()
    if mode == "dev":
        return None
    if mode != "oidc":
        raise AuthConfigError("AGENTKIT_AUTH_MODE must be 'oidc' or explicit loopback-only 'dev'")

    values = [os.environ.get(name, "").strip() for name in _OIDC_ENV_VARS]
    missing = [name for name, value in zip(_OIDC_ENV_VARS, values, strict=True) if not value]
    if missing:
        raise AuthConfigError(f"OIDC is incompletely configured; missing: {missing}")
    token_endpoint = os.environ.get("AGENTKIT_OIDC_TOKEN_URL", "").strip()
    if not token_endpoint:
        token_endpoint = f"{values[1].rstrip('/')}/protocol/openid-connect/token"
    return _Settings(*values, token_endpoint)


_jwks_client: PyJWKClient | None = None
_state_lock = threading.RLock()
_login_attempts: dict[str, _LoginAttempt] = {}
_sessions: dict[str, _Session] = {}


def _client(jwks_url: str) -> PyJWKClient:
    global _jwks_client
    with _state_lock:
        if _jwks_client is None or _jwks_client.uri != jwks_url:
            _jwks_client = PyJWKClient(jwks_url, timeout=10)
        return _jwks_client


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header:
        return None
    scheme, separator, token = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="invalid authorization header")
    return token.strip()


def _roles(claims: dict) -> frozenset[str]:
    realm_access = claims.get("realm_access", {})
    if not isinstance(realm_access, dict):
        return frozenset()
    values = realm_access.get("roles", [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return frozenset()
    return frozenset(values)


def _principal_from_token(token: str, settings: _Settings) -> tuple[Principal, dict]:
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
    except jwt_exceptions.PyJWKClientConnectionError as exc:
        _LOG.warning("OIDC JWKS endpoint is unavailable")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE) from exc
    except (jwt_exceptions.PyJWKClientError, jwt_exceptions.PyJWTError) as exc:
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN) from exc

    if claims.get("typ") != "Bearer":
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
    org_id = claims.get(ORG_CLAIM)
    subject = claims.get("sub")
    email = claims.get("email", "")
    if not isinstance(org_id, str) or not org_id.strip():
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
    if not isinstance(email, str):
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
    roles = _roles(claims)
    if roles.isdisjoint({"admin", "viewer"}):
        raise HTTPException(status_code=403, detail="application role required")

    return (
        Principal(
            org_id=org_id.strip(),
            subject=subject,
            email=email,
            roles=roles,
        ),
        claims,
    )


DEV_PRINCIPAL = Principal(
    org_id=DEFAULT_ORG,
    subject="dev",
    email="dev@localhost",
    roles=frozenset({"admin", "viewer"}),
    auth_method="dev",
)


def auth_enabled() -> bool:
    return _settings() is not None


def current_principal(request: Request) -> Principal:
    """Resolve a service bearer token or a server-side browser session."""
    settings = _settings()
    if settings is None:
        return DEV_PRINCIPAL

    token = _bearer(request)
    if token is not None:
        principal, _claims = _principal_from_token(token, settings)
        return principal

    session_id = request.cookies.get(SESSION_COOKIE, "")
    now = time.time()
    with _state_lock:
        session = _sessions.get(session_id)
        if session is not None and session.expires_at <= now:
            _sessions.pop(session_id, None)
            session = None
    if session is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return session.principal


async def require_admin(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> Principal:
    """Require the coarse admin role and CSRF for browser-session mutations."""
    if not principal.can_mutate:
        raise HTTPException(status_code=403, detail="admin role required")
    if principal.auth_method == "session" and request.method.upper() not in _SAFE_METHODS:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied:
            form = await request.form()
            supplied = str(form.get("csrf_token", ""))
        if not supplied or not secrets.compare_digest(supplied, principal.csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
    return principal


def _safe_next_url(value: str | None) -> str:
    if not value:
        return "/"
    parsed = parse.urlsplit(value)
    is_local_path = not parsed.scheme and not parsed.netloc and value.startswith("/")
    return value if is_local_path and not value.startswith("//") else "/"


def begin_browser_login(next_url: str | None) -> tuple[str, str]:
    settings = _settings()
    if settings is None:
        return "/", ""

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    now = time.time()
    with _state_lock:
        for key, attempt in list(_login_attempts.items()):
            if attempt.expires_at <= now:
                _login_attempts.pop(key, None)
        _login_attempts[state] = _LoginAttempt(
            verifier=verifier,
            next_url=_safe_next_url(next_url),
            expires_at=now + 300,
        )
    query = parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": "openid profile email org",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{settings.authorization_url}?{query}", state


def _exchange_code(settings: _Settings, code: str, verifier: str) -> dict:
    payload = parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()
    token_request = urlrequest.Request(
        settings.token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(token_request, timeout=10) as response:  # noqa: S310
            token_response = json.loads(response.read())
    except error.HTTPError as exc:
        raise HTTPException(status_code=401, detail="authorization code rejected") from exc
    except (error.URLError, TimeoutError) as exc:
        _LOG.warning("OIDC token endpoint is unavailable")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _LOG.warning("OIDC token endpoint returned an invalid response")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE) from exc
    if not isinstance(token_response, dict):
        _LOG.warning("OIDC token endpoint returned a non-object response")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE)
    return token_response


def complete_browser_login(
    code: str,
    state: str,
    browser_state: str,
) -> tuple[str, Principal, str]:
    settings = _settings()
    if settings is None:
        return "", DEV_PRINCIPAL, "/"
    if not state or not browser_state or not secrets.compare_digest(state, browser_state):
        raise HTTPException(status_code=401, detail="invalid login state")
    with _state_lock:
        attempt = _login_attempts.pop(state, None)
    if attempt is None or attempt.expires_at <= time.time():
        raise HTTPException(status_code=401, detail="expired login state")

    token_response = _exchange_code(settings, code, attempt.verifier)
    access_token = token_response.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=503, detail="identity provider returned no access token")
    principal, claims = _principal_from_token(access_token, settings)
    csrf_token = secrets.token_urlsafe(32)
    principal = replace(principal, auth_method="session", csrf_token=csrf_token)
    session_id = secrets.token_urlsafe(48)
    expires_at = float(claims["exp"])
    with _state_lock:
        _sessions[session_id] = _Session(principal=principal, expires_at=expires_at)
    return session_id, principal, attempt.next_url


def end_browser_session(session_id: str | None) -> str:
    settings = _settings()
    if session_id:
        with _state_lock:
            _sessions.pop(session_id, None)
    if settings is None:
        return "/"
    query = parse.urlencode(
        {
            "client_id": settings.client_id,
            "post_logout_redirect_uri": settings.redirect_uri.rsplit("/auth/callback", 1)[0] + "/",
        }
    )
    return f"{settings.logout_url}?{query}"


def cookie_secure() -> bool:
    settings = _settings()
    return settings.cookie_secure if settings is not None else False


def reset_auth_state() -> None:
    """Clear process-local clients and sessions; intended for tests and shutdown."""
    global _jwks_client
    with _state_lock:
        _jwks_client = None
        _login_attempts.clear()
        _sessions.clear()
