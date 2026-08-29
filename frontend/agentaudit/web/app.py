"""FastAPI entrypoint: OIDC auth, the JSON API, and the React SPA shell.

The pages live in ``frontend/spa`` (React); this module serves their data via
``agentaudit.web.api`` and hands out the built SPA bundle for every other GET.
Derivation lives in ``core/runview.py``; mutations are admin-gated + CSRF
checked in ``auth.require_admin``.
"""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agentaudit.web.api import router as api_router
from agentaudit.web.auth import (
    LOGIN_STATE_COOKIE,
    SESSION_COOKIE,
    Principal,
    auth_enabled,
    begin_browser_login,
    complete_browser_login,
    cookie_secure,
    current_principal,
    end_browser_session,
    reset_auth_state,
)
from agentaudit.web.runtime import BASE_DIR, close_store, get_store

# Built by `npm run build` inside frontend/spa; committed artifacts ship in the
# wheel via package-data.
SPA_DIST = BASE_DIR / "spa_dist"

_SPA_PLACEHOLDER = """<!doctype html><html lang="en"><body style="
  font-family: system-ui, sans-serif; background: #010102; color: #f7f8f8;
  display: grid; place-items: center; min-height: 100vh;">
<p>The dashboard bundle is not built yet. Run <code>npm ci &amp;&amp; npm run build</code>
inside <code>frontend/spa</code>, then reload.</p></body></html>"""

# Sources for the bundle above; used only to detect a stale build in dev.
SPA_SRC = BASE_DIR.parents[1] / "spa" / "src"

_SPA_STALE_BANNER = """<div style="
  font: 14px system-ui, sans-serif; background: #7a2e00; color: #fff;
  padding: 8px 14px; text-align: center;">
Stale bundle: frontend/spa/src changed since the last build. Reloading will not
show it. Run <code>bash infra/dev.sh</code> for hot reload on
<code>:5173</code>, or <code>npm run build</code> in <code>frontend/spa</code>.
</div>"""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Validate authentication before accepting traffic. An unset mode is a
    # deployment error; loopback development must opt in explicitly.
    auth_enabled()
    get_store()
    try:
        yield
    finally:
        reset_auth_state()
        close_store()


# Swagger/ReDoc/openapi.json are off: they cannot carry a principal, so they
# would be the only unauthenticated routes on a partner-facing deployment, and
# they publish the whole route surface for free.
app = FastAPI(
    title="agentaudit",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)
app.include_router(api_router)


@app.middleware("http")
async def frame_protection(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return response


# StaticFiles guesses content types from the OS. On some Windows setups the
# registry maps .js to application/json, and browsers refuse to execute a
# module with that MIME type -- pin what we serve.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

if (BASE_DIR / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
if SPA_DIST.is_dir():
    # Vite is configured with assetsDir "" and base "/assets/", so bundle files
    # sit directly in spa_dist and their URLs land here.
    app.mount("/assets", StaticFiles(directory=str(SPA_DIST)), name="assets")


@app.get("/login", include_in_schema=False)
def login(next: str | None = None) -> RedirectResponse:  # noqa: A002
    destination, state = begin_browser_login(next)
    response = RedirectResponse(destination, status_code=302)
    if state:
        response.set_cookie(
            LOGIN_STATE_COOKIE,
            state,
            max_age=300,
            httponly=True,
            secure=cookie_secure(),
            samesite="lax",
        )
    return response


@app.get("/auth/callback", include_in_schema=False)
def auth_callback(code: str, state: str, request: Request) -> RedirectResponse:
    session_id, _principal, destination = complete_browser_login(
        code,
        state,
        request.cookies.get(LOGIN_STATE_COOKIE, ""),
    )
    response = RedirectResponse(destination, status_code=303)
    response.delete_cookie(LOGIN_STATE_COOKIE)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=3600,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )
    return response


@app.get("/logout", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    destination = end_browser_session(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse(destination, status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response


def _spa_is_stale() -> bool:
    """True when a source file is newer than the built bundle.

    The bundle is content-hashed, so a stale build is invisible to the browser:
    it caches nothing wrong, it is simply served the last thing that was built.
    Editing frontend/spa/src and reloading then looks like a broken reload.
    """
    if not SPA_SRC.is_dir():
        return False
    try:
        built = max(f.stat().st_mtime for f in SPA_DIST.iterdir() if f.is_file())
        return any(f.stat().st_mtime > built for f in SPA_SRC.rglob("*") if f.is_file())
    except OSError:
        return False


def _spa_index() -> HTMLResponse:
    index = SPA_DIST / "index.html"
    if index.is_file():
        html = index.read_text(encoding="utf-8")
        if _spa_is_stale():
            html = html.replace("<body>", f"<body>{_SPA_STALE_BANNER}", 1)
        return HTMLResponse(html)
    return HTMLResponse(_SPA_PLACEHOLDER, status_code=200)


@app.get("/{full_path:path}", include_in_schema=False)
def spa_shell(full_path: str, principal: Principal = Depends(current_principal)) -> HTMLResponse:  # noqa: ARG001
    """Serve the SPA shell for every application path.

    Takes a Principal like every application route -- reads included, since
    reads are the leak -- so an unauthenticated browser navigation is answered
    by the 401 handler's redirect to /login below, exactly as the Jinja pages
    were. Data itself flows through /api routes, which enforce the same rule.
    """
    return _spa_index()


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> Response:
    accept = request.headers.get("accept", "").lower()
    browser_navigation = request.method in {"GET", "HEAD"} and (
        "text/html" in accept or request.headers.get("accept", "") == "*/*"
    )
    public_auth_paths = {"/login", "/auth/callback"}
    if (
        exc.status_code == 401
        and auth_enabled()
        and browser_navigation
        and request.url.path not in public_auth_paths
    ):
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
