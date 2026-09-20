# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9Chat visitor identity — real signed-cookie sessions (Starlette's
SessionMiddleware, itsdangerous under the hood), not a hand-rolled scheme.

No password, deliberately -- ported from k9x_satan's actual behavior
(k9x-ecosystem/k9x_satan/app.py), not the "shared demo/demo password"
version this file used earlier tonight. That version was worked through
and dropped for a concrete reason: a single shared password shown right
on the login page is not a real deterrent to automated abuse -- any bot
that found the URL could trivially find and submit it too. What actually
guards against a bot hammering real GPU/LLM compute is the rate limiter
(rate_limit.py), which applies the same regardless of whether a visitor
typed a name or not. The name-entry step that remains exists for a
different reason entirely: giving every visitor their own identity is
what lets Projects be scoped per-visitor (see current_owner_id() below) --
confirmed 2026-09-20 that without it, every visitor shared every other
visitor's Projects, since ProjectManager had zero per-visitor scoping.

Same codename generator and "never reject a name, silently swap to a
generated one" approach as satan's version.
"""

import os
import re
import secrets
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

# Paths reachable without a session -- the login page itself, its own
# POST target, and static assets (the login page's CSS/images need to
# load before the user can log in at all).
_PUBLIC_PREFIXES = ("/login", "/static", "/health")


def get_session_secret() -> str:
    """Falls back to a fixed dev-only value -- unlike the old password
    gate, the name-entry step always runs (see LoginRequiredMiddleware),
    so SessionMiddleware always needs a secret, not just in some opt-in
    deployment mode."""
    return os.environ.get("K9CHAT_SESSION_SECRET") or "k9chat-dev-only-unused-secret"


# ── Per-visitor display name (ported from k9x_satan's guest identity) ───────

_CODENAME_ADJECTIVES = [
    "shadow", "phantom", "silent", "rogue", "night", "crimson", "iron",
    "ghost", "feral", "grim", "obsidian", "venomous", "razor", "cursed",
    "hollow", "savage", "wicked", "midnight", "ashen", "rabid",
]
_CODENAME_NOUNS = [
    "wolf", "viper", "reaper", "wraith", "hawk", "jackal", "cobra",
    "panther", "raven", "specter", "hound", "scorpion", "falcon", "lynx",
    "mantis", "vulture", "banshee", "golem", "wyrm", "sentinel",
]

# Not exhaustive -- a blocklist never is. Deliberately conservative (common
# English profanity/slurs); the point is to catch the obvious case, with
# silent codename substitution (not a rejection/retry loop) as the safety
# net for whatever it misses -- same as satan's own version of this list.
_USERNAME_BLOCKLIST = {
    "fuck", "shit", "bitch", "cunt", "asshole", "bastard", "dick", "pussy",
    "nigger", "nigga", "faggot", "fag", "retard", "whore", "slut", "rape",
    "nazi", "hitler", "cock", "twat", "dyke", "chink", "spic", "kike",
}


def generate_guest_username() -> str:
    adjective = secrets.choice(_CODENAME_ADJECTIVES)
    noun = secrets.choice(_CODENAME_NOUNS)
    return f"{adjective}-{noun}-{secrets.token_hex(2)}"


def sanitize_username(raw: str) -> str:
    """Returns a display-safe username: the visitor's own text if it's
    non-empty, reasonably short, and clean -- otherwise a freshly
    generated codename. Never raises/rejects -- a blocked or malformed
    name just silently becomes a codename, exactly like leaving the
    field blank."""
    candidate = (raw or "").strip()
    if not candidate or len(candidate) > 24:
        return generate_guest_username()
    normalized = re.sub(r"[^a-z0-9]", "", candidate.lower())
    if any(bad in normalized for bad in _USERNAME_BLOCKLIST):
        return generate_guest_username()
    return candidate


def current_owner_id(request: Request) -> Optional[str]:
    """The current visitor's scoping key for Projects. Always set once
    past the name-entry step (see LoginRequiredMiddleware) -- there's no
    "login disabled" mode anymore, so this is only ever None mid-request
    on a path the middleware already let through unauthenticated."""
    return request.session.get("visitor_id")


class LoginRequiredMiddleware(BaseHTTPMiddleware):
    """Redirects every request to /login (a name-entry step, not a
    password gate -- see this module's docstring) unless the session
    already has a visitor_id, or the path is one of the public prefixes
    above. Always active; there's no opt-out env var -- the step is a
    single optional-text-field submit, not real friction, and it's what
    gives every visitor their own Projects scope."""

    async def dispatch(self, request: Request, call_next):
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
