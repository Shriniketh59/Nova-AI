"""Double-submit-cookie CSRF protection.

State-changing requests (POST/PUT/PATCH/DELETE) that are authenticated via the
`nova_session` cookie must also carry an `X-CSRF-Token` header whose value
matches the non-httponly `csrf_token` cookie issued at login/session
creation. This defeats classic CSRF: an attacking site can make the browser
send cookies automatically, but it cannot read the csrf cookie (cross-origin)
to put its value in a custom header.

Requests authenticated via `Authorization: Bearer <token>` instead of a
cookie are not vulnerable to CSRF (browsers don't attach arbitrary headers
to cross-site requests automatically) and are exempt.
"""
from fastapi import Request
from starlette.responses import JSONResponse

from ..core.config import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, NODE_ENV

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Routes that create or destroy the session itself, or that are external
# redirect targets (OAuth callback) — none of these can reasonably carry a
# CSRF header yet issued by this app, so they are exempt from the check.
EXEMPT_PATH_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/google",
)


def _is_exempt(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in EXEMPT_PATH_PREFIXES)


async def csrf_protect(request: Request, call_next):
    """ASGI-style middleware enforcing the double-submit CSRF token."""
    # Disabled under the test harness, which drives the API directly via
    # httpx without a browser and has no way to read/set the csrf cookie
    # across the ASGI transport in the same way a real browser session does.
    if NODE_ENV == "test":
        return await call_next(request)

    if request.method.upper() in SAFE_METHODS:
        return await call_next(request)

    if _is_exempt(request.url.path):
        return await call_next(request)

    # Only cookie-authenticated requests are subject to CSRF; bearer-token
    # requests (e.g. non-browser API clients) can't be forged cross-site.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return await call_next(request)

    session_cookie = request.cookies.get(AUTH_COOKIE_NAME)
    if not session_cookie:
        # No session cookie means no CSRF-relevant state to protect; let the
        # request through so normal auth (get_current_user) can 401 it.
        return await call_next(request)

    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    csrf_header = request.headers.get("X-CSRF-Token")

    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        return JSONResponse(
            status_code=403,
            content={"detail": "Missing or invalid CSRF token"},
        )

    return await call_next(request)
