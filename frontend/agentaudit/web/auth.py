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

from agentaudit.core.intake import demo_mode
from agentaudit.core.store import DEFAULT_ORG

_LOG = logging.getLogger(__name__)
_ALGORITHMS = ["RS256"]
# `aud` and `azp` are deliberately absent. Clerk's OAuth applications issue
# access tokens carrying neither and expose no setting to add them, so
# requiring either rejects every real token. Both are still *verified* when an
# IdP does send them (see below); what binds a token to this client when they
# are missing is the PKCE code exchange itself, which only the holder of the
# code_verifier for this client_id can complete.
_REQUIRED_CLAIMS = ["exp", "iss", "sub"]
ORG_CLAIM = "org_id"
SESSION_COOKIE = "agentaudit_session"
LOGIN_STATE_COOKIE = "agentaudit_login_state"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_IDP_UNAVAILABLE = "identity provider unavailable"
_INVALID_TOKEN = "invalid token"
_REVOKED = "authorization revoked"
# A session caches authorization, so this is how long a removed or demoted user
# keeps read access. Writes re-check with the IdP, so this bounds reads only.
SESSION_TTL_SECONDS = 1800


def private_tenant_without_org() -> bool:
    """Whether a login carrying no Clerk org gets its own private tenant.

    Off by default: on a shared instance anyone who can finish a login would
    otherwise mint a workspace and run jobs on the box. Turning it on trades
    that for not having to provision an org per user, which is what a
    single-operator or internal deployment usually wants.
    """
    return os.environ.get("AGENTAUDIT_ALLOW_ORGLESS_LOGIN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


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
    authorization_endpoint: str
    userinfo_endpoint: str

    @property
    def authorization_url(self) -> str:
        return self.authorization_endpoint

    @property
    def token_url(self) -> str:
        return self.token_endpoint

    @property
    def cookie_secure(self) -> bool:
        configured = os.environ.get("AGENTAUDIT_SESSION_COOKIE_SECURE")
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
    # Retained so a mutating request can re-ask the IdP who this user still is.
    access_token: str = ""


_OIDC_ENV_VARS = (
    "AGENTAUDIT_OIDC_JWKS_URL",
    "AGENTAUDIT_OIDC_ISSUER",
    "AGENTAUDIT_OIDC_AUDIENCE",
    "AGENTAUDIT_OIDC_CLIENT_ID",
    "AGENTAUDIT_OIDC_REDIRECT_URI",
)


class AuthConfigError(RuntimeError):
    """Authentication mode is absent, invalid, or incompletely configured."""


def _settings() -> _Settings | None:
    """Return OIDC settings or the explicitly requested loopback dev mode."""
    mode = os.environ.get("AGENTAUDIT_AUTH_MODE", "").strip().lower()
    if mode == "dev":
        return None
    if mode != "oidc":
        raise AuthConfigError("AGENTAUDIT_AUTH_MODE must be 'oidc' or explicit loopback-only 'dev'")

    values = [os.environ.get(name, "").strip() for name in _OIDC_ENV_VARS]
    missing = [name for name, value in zip(_OIDC_ENV_VARS, values, strict=True) if not value]
    if missing:
        raise AuthConfigError(f"OIDC is incompletely configured; missing: {missing}")
    issuer = values[1].rstrip("/")
    token_endpoint = os.environ.get("AGENTAUDIT_OIDC_TOKEN_URL", "").strip()
    if not token_endpoint:
        token_endpoint = f"{issuer}/protocol/openid-connect/token"
    authorization_endpoint = os.environ.get("AGENTAUDIT_OIDC_AUTH_URL", "").strip()
    if not authorization_endpoint:
        authorization_endpoint = f"{issuer}/protocol/openid-connect/auth"
    userinfo_endpoint = os.environ.get("AGENTAUDIT_OIDC_USERINFO_URL", "").strip()
    if not userinfo_endpoint:
        userinfo_endpoint = f"{issuer}/oauth/userinfo"
    return _Settings(*values, token_endpoint, authorization_endpoint, userinfo_endpoint)


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
    """Read the flat `roles` claim, tolerating a scalar.

    Clerk's JWT templates expose `{{org.role}}` as a single string, so a token
    may carry either a list or one bare role. Anything else -- a dict, a list
    with a non-string in it -- yields no roles at all, which `_principal_from_token`
    turns into a 403. Failing closed here matters more than being permissive:
    a malformed claim must never be read as "some role was present".
    """
    values = claims.get("roles", [])
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return frozenset()
    # Clerk namespaces org roles as `org:admin`; the app's vocabulary is bare.
    return frozenset(value.split(":", 1)[-1] for value in values)


def _principal_from_token(
    token: str,
    settings: _Settings,
    *,
    require_azp: bool = True,
    identity: dict | None = None,
) -> tuple[Principal, dict]:
    """Validate a token and derive its principal.

    `require_azp` is the caller's assertion about what else binds the token to
    this client. A bare bearer token has nothing behind it, so `azp` is the only
    proof and stays mandatory. A token just fetched by `_exchange_code` is bound
    by the PKCE exchange itself, so an IdP that omits `azp` (Clerk) is tolerated.

    `identity` supplies org/role/email when the token itself cannot carry them.
    Clerk's OAuth access tokens hold only `client_id, exp, iat, iss, jti, nbf,
    scope, sub` -- no JWT template applies to them, so the browser-login path
    reads those claims from the userinfo endpoint instead. The token is still
    what is *verified*; `identity` only names the user it already authenticated.
    """
    try:
        signing_key = _client(settings.jwks_url).get_signing_key_from_jwt(token)
        # Read-only peek to see whether the IdP sent `aud` at all. Nothing from
        # here is trusted; the verified decode below is the only source of truth.
        unverified = jwt.decode(token, options={"verify_signature": False})
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            issuer=settings.issuer,
            audience=settings.audience,
            # An IdP that omits `aud` entirely (Clerk) still gets a verified
            # audience when it does send one; only the absence is tolerated.
            options={"require": _REQUIRED_CLAIMS, "verify_aud": "aud" in unverified},
        )
    except jwt_exceptions.PyJWKClientConnectionError as exc:
        _LOG.warning("OIDC JWKS endpoint is unavailable")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE) from exc
    except (jwt_exceptions.PyJWKClientError, jwt_exceptions.PyJWTError) as exc:
        # Signature, issuer, audience and required-claim failures all land here
        # and are otherwise indistinguishable from the opaque 401 below.
        _LOG.warning("OIDC token validation failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN) from exc

    # Authorized party: when the IdP sends `azp` it must name this client, which
    # stops a token issued to a different application on the same IdP instance
    # from being replayed here. An IdP that omits it (Clerk) leaves that job to
    # the PKCE exchange in `_exchange_code`; a *wrong* azp is still refused.
    if (require_azp or "azp" in claims) and claims.get("azp") != settings.client_id:
        _LOG.warning("OIDC azp mismatch: token azp=%r", claims.get("azp"))
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
    source = claims if identity is None else identity
    subject = claims.get("sub")
    email = source.get("email", "")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
    if not isinstance(email, str):
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN)

    # Clerk marks a user whose org membership has not been accepted yet. That
    # is a distinct, diagnosable state, so it is refused ahead of the
    # private-tenant fallback rather than being silently absorbed by it --
    # except where that fallback is the deployment's intended landing place.
    if source.get("sts") == "pending" and not private_tenant_without_org():
        raise HTTPException(
            status_code=403,
            detail="organization invitation not accepted",
        )

    org_id = source.get(ORG_CLAIM)
    roles = _roles(source)
    if not isinstance(org_id, str) or not org_id.strip():
        # No IdP-supplied tenancy. A browser login is still bound to one real
        # user by the PKCE exchange, so it gets a private tenant keyed on that
        # user's stable `sub` -- every store query is already scoped by org_id,
        # so this isolates the user's runs from everyone else's with no further
        # filtering. A bare bearer token (`identity is None`) has no such
        # binding and is still refused: handing it a tenant would let any
        # token issued by this IdP quietly mint its own workspace.
        if identity is None:
            _LOG.warning(
                "OIDC token carries no usable %s; claims present: %s", ORG_CLAIM, sorted(claims)
            )
            raise HTTPException(status_code=401, detail=_INVALID_TOKEN)
        # On a shared instance anyone who can finish a Clerk login could
        # otherwise mint their own workspace and run jobs on the box, so a
        # missing org is a hard refusal unless the deployment opted in.
        if not demo_mode() and not private_tenant_without_org():
            _LOG.warning(
                "OIDC userinfo carries no usable %s for sub=%r; keys present: %s",
                ORG_CLAIM,
                subject,
                sorted(source),
            )
            raise HTTPException(status_code=403, detail="organization membership required")
        org_id = f"user:{subject.strip()}"
        # Sole occupant of a tenant nobody else can reach, so admin over it.
        roles = roles or frozenset({"admin"})

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


def _revalidate_session(session_id: str) -> None:
    """Re-ask the IdP whether this session may still write.

    A session freezes org membership and roles at login, so removing a user from
    a company's Clerk org would otherwise leave them writing until the token
    expires. Reads tolerate that staleness (bounded by `SESSION_TTL_SECONDS`);
    writes do not. If the IdP is unreachable the mutation is denied rather than
    falling back to the cached principal, so an IdP outage degrades to read-only.
    """
    settings = _settings()
    if settings is None:
        return
    with _state_lock:
        session = _sessions.get(session_id)
    if session is None or not session.access_token:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        fresh, _claims = _principal_from_token(
            session.access_token,
            settings,
            require_azp=False,
            identity=_userinfo(settings, session.access_token),
        )
    except HTTPException as exc:
        if exc.status_code == 503:
            raise
        _end_session(session_id)
        raise HTTPException(status_code=403, detail=_REVOKED) from exc
    if fresh.org_id != session.principal.org_id or not fresh.can_mutate:
        _end_session(session_id)
        raise HTTPException(status_code=403, detail=_REVOKED)


def _end_session(session_id: str) -> None:
    with _state_lock:
        _sessions.pop(session_id, None)


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
        _revalidate_session(request.cookies.get(SESSION_COOKIE, ""))
    return principal


def _safe_next_url(value: str | None) -> str:
    if not value:
        return "/"
    if "\\" in value:
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
            "scope": "openid profile email user:org:read",
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
        # Clerk fronts its token endpoint with Cloudflare, which 403s urllib's
        # default agent (error 1010). Identify the app instead of the runtime.
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "agentaudit",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(token_request, timeout=10) as response:  # noqa: S310
            token_response = json.loads(response.read())
    except error.HTTPError as exc:
        # The IdP's error code is the only thing that distinguishes a replayed
        # code from a redirect_uri or client mismatch; without it the 401 below
        # is undiagnosable. The body is an OAuth error object, not user data.
        _LOG.warning("OIDC token exchange rejected: %s %s", exc.code, exc.read()[:300])
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


def _userinfo(settings: _Settings, access_token: str) -> dict:
    """Fetch the identity claims Clerk's OAuth access token cannot carry.

    Returns the raw userinfo object; `_principal_from_token` applies the same
    shape checks to it that it applies to token claims, so a malformed or
    partial response fails closed there rather than here.
    """
    userinfo_request = urlrequest.Request(
        settings.userinfo_endpoint,
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": "agentaudit"},
        method="GET",
    )
    try:
        with urlrequest.urlopen(userinfo_request, timeout=10) as response:  # noqa: S310
            userinfo = json.loads(response.read())
    except error.HTTPError as exc:
        _LOG.warning("OIDC userinfo rejected: %s %s", exc.code, exc.read()[:300])
        raise HTTPException(status_code=401, detail=_INVALID_TOKEN) from exc
    except (error.URLError, TimeoutError) as exc:
        _LOG.warning("OIDC userinfo endpoint is unavailable")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _LOG.warning("OIDC userinfo endpoint returned an invalid response")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE) from exc
    if not isinstance(userinfo, dict):
        _LOG.warning("OIDC userinfo endpoint returned a non-object response")
        raise HTTPException(status_code=503, detail=_IDP_UNAVAILABLE)
    return userinfo


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
    principal, claims = _principal_from_token(
        access_token, settings, require_azp=False, identity=_userinfo(settings, access_token)
    )
    csrf_token = secrets.token_urlsafe(32)
    principal = replace(principal, auth_method="session", csrf_token=csrf_token)
    session_id = secrets.token_urlsafe(48)
    # The IdP token can live for hours; cap the session so cached authorization
    # goes stale in minutes, not for the token's whole lifetime.
    expires_at = min(float(claims["exp"]), time.time() + SESSION_TTL_SECONDS)
    with _state_lock:
        _sessions[session_id] = _Session(
            principal=principal, expires_at=expires_at, access_token=access_token
        )
    return session_id, principal, attempt.next_url


def end_browser_session(session_id: str | None) -> str:
    """Destroy the server-side session and return where to send the browser.

    Only the local session is ended; there is no IdP round-trip. Once the
    session row is gone the cookie is inert, so a federated logout would buy
    nothing here beyond a redirect the deployment has to keep in sync.
    """
    if session_id:
        with _state_lock:
            _sessions.pop(session_id, None)
    return "/"


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
