# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9Chat login gate — real signed-cookie sessions (Starlette's
SessionMiddleware, itsdangerous under the hood), not a hand-rolled
scheme. Credentials come from the environment only, never config.yaml,
matching RedisAdapter's own convention elsewhere in this framework
(REDIS_PASSWORD env-only).

Only meaningful once this app is exposed somewhere reachable beyond
localhost (e.g. chat.k9x.ai) -- for local-only use this is inert
overhead, but it's cheap and the app should be safe to expose without
a second pass once that happens.
"""

import os
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

# Paths reachable without a session -- the login page itself, its own
# POST target, and static assets (the login page's CSS/images need to
# load before the user can log in at all).
_PUBLIC_PREFIXES = ("/login", "/static", "/health")


def get_session_secret() -> str:
    secret = os.environ.get("K9CHAT_SESSION_SECRET", "")
    if not secret:
        raise RuntimeError(
            "K9CHAT_SESSION_SECRET must be set in the environment before "
            "starting k9chat with login enabled -- see .env.example."
        )
    return secret


def is_login_enabled() -> bool:
    """Login is opt-in via K9CHAT_LOGIN_EMAIL -- local/dev use (no .env
    override) stays exactly as open as it always was; only set this to
    actually expose the app somewhere (e.g. chat.k9x.ai)."""
    return bool(os.environ.get("K9CHAT_LOGIN_EMAIL"))


def check_credentials(email: str, password: str) -> bool:
    expected_email = os.environ.get("K9CHAT_LOGIN_EMAIL", "")
    expected_password = os.environ.get("K9CHAT_LOGIN_PASSWORD", "")
    if not expected_email or not expected_password:
        return False
    return email == expected_email and password == expected_password


class LoginRequiredMiddleware(BaseHTTPMiddleware):
    """Redirects every request to /login unless the session says
    logged_in=True, or the path is one of the public prefixes above.
    No-ops entirely when login isn't enabled (see is_login_enabled), so
    local development is unaffected unless K9CHAT_LOGIN_EMAIL is set."""

    async def dispatch(self, request: Request, call_next):
        if not is_login_enabled():
            return await call_next(request)

        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        if request.session.get("logged_in"):
            return await call_next(request)

        # API calls (JSON) get a 401, not a redirect -- a fetch() call
        # following a 302 to an HTML login page would just hand the
        # frontend an HTML blob where it expected JSON.
        if path.startswith("/chat") or path.startswith("/projects"):
            from starlette.responses import JSONResponse
            return JSONResponse({"error": "not authenticated"}, status_code=401)

        return RedirectResponse(url="/login")
