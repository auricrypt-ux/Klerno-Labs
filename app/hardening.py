# app/hardening.py
from __future__ import annotations

import os
import hmac
import secrets
from typing import Optional, Callable, Awaitable

from fastapi import Request, HTTPException
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

REQ_ID_HEADER = "X-Request-ID"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Sets a strict, but UI-friendly baseline of security headers."""
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        resp: Response = await call_next(request)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        resp.headers.setdefault("Content-Security-Policy", csp)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if (os.getenv("ENABLE_HSTS", "true").lower() == "true") and request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        return resp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Adds/propagates a stable request id for traceability."""
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        rid = request.headers.get(REQ_ID_HEADER) or secrets.token_hex(8)
        request.state.request_id = rid
        resp: Response = await call_next(request)
        resp.headers.setdefault(REQ_ID_HEADER, rid)
        return resp


def issue_csrf_cookie(resp: Response) -> str:
    """Mint a CSRF token cookie (readable by JS; header-only is checked server-side)."""
    token = secrets.token_urlsafe(32)
    # NOTE: SameSite=Strict and Secure; not HttpOnly because client JS must reflect it into header.
    resp.set_cookie("csrf_token", token, secure=True, samesite="Strict", httponly=False, path="/", max_age=60 * 60 * 8)
    return token


def verify_csrf(request: Request) -> None:
    """Double-submit cookie check."""
    token_cookie = request.cookies.get(CSRF_COOKIE)
    token_hdr = request.headers.get(CSRF_HEADER)
    if not token_cookie or not token_hdr:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not hmac.compare_digest(token_cookie, token_hdr):
        raise HTTPException(status_code=403, detail="Bad CSRF token")


async def csrf_guard(request: Request):
    """FastAPI dependency to protect unsafe UI methods."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        verify_csrf(request)
    return True


def install_security(app) -> None:
    """Attach security middlewares (single place, avoids duplication)."""
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)


# ---- Optional rate limiting (no warnings if library absent) ------------------

def rate_limit(spec: str):
    """
    Returns a dependency suitable for FastAPI route `dependencies=[Depends(rate_limit("10/min"))]`.
    - If starlette-limiter is installed and REDIS_URL is set, uses it.
    - Otherwise, returns a no-op dependency (clean, no linter warnings).
    """
    try:
        from starlette_limiter import RateLimiter  # type: ignore
        # Parse "10/min", "100/hour", or raw seconds like "20/30"
        parts = spec.split("/")
        times = int(parts[0])
        per = parts[1].lower() if len(parts) > 1 else "min"
        seconds = {"sec": 1, "second": 1, "min": 60, "minute": 60, "hour": 3600}.get(per, 60)
        # Require redis URL to actually enable limiter
        if not os.getenv("REDIS_URL"):
            # RateLimiter without Redis will fail; fall back to no-op
            raise RuntimeError("No REDIS_URL set; skipping real limiter.")
        return RateLimiter(times=times, seconds=seconds)
    except Exception:
        # No-op dependency
        async def _noop():
            return True
        return _noop
