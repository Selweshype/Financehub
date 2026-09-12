"""Fixed-window in-memory rate limiter for the authentication surface.

Security finding H1: nothing throttled ``/auth/totp/verify``.  A TOTP code is
six digits and ``pyotp.verify(..., valid_window=1)`` accepts three of them at
any instant, so ~3 in 10**6 guesses succeed.  Unthrottled, an attacker gets
through in hours.

Implemented with the standard library only — no slowapi, no Redis — because
FinanceHub is a single-user, single-worker app and the project rule is to
prefer a stdlib alternative over a new dependency.  The same single-process
caveat as ``challenge.py`` applies: counters are per-process and would need a
shared store if the deployment ever grows past one worker.
"""
from __future__ import annotations

import os
import time

from fastapi import HTTPException, Request

# Default policy for authentication endpoints.
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_WINDOW = 15 * 60  # seconds

# Cap the number of tracked keys so a spoofed-IP flood cannot grow the heap.
_MAX_KEYS = 1024

# key -> (window_started_at, attempt_count)
_buckets: dict[str, tuple[int, int]] = {}


def _trust_proxy() -> bool:
    """Whether to believe X-Forwarded-For.

    Only true when explicitly opted in via FINANCEHUB_TRUST_PROXY=1.  In the
    shipped Docker topology Caddy is the sole ingress and the app is on an
    internal network, so the header cannot be spoofed by a client — but the
    default stays off so a direct-exposure deployment is not trivially
    bypassed by sending your own X-Forwarded-For.
    """
    return os.environ.get("FINANCEHUB_TRUST_PROXY", "").strip() == "1"


def client_key(request: Request) -> str:
    """Best-effort client identity for rate-limiting purposes."""
    if _trust_proxy():
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Left-most entry is the original client.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(now: int, window: int) -> None:
    """Drop buckets whose window has fully elapsed."""
    for key in [k for k, (started, _) in _buckets.items() if now - started >= window]:
        _buckets.pop(key, None)


def check(
    request: Request,
    scope: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    window: int = DEFAULT_WINDOW,
) -> None:
    """Record an attempt and raise 429 once *max_attempts* is exceeded.

    *scope* namespaces the counter so a lockout on one endpoint does not also
    lock out another.  Raises :class:`HTTPException` with ``Retry-After`` set
    to the seconds remaining in the current window.
    """
    now = int(time.time())
    _prune(now, window)

    if len(_buckets) >= _MAX_KEYS:
        oldest = min(_buckets, key=lambda k: _buckets[k][0])
        _buckets.pop(oldest, None)

    key = f"{scope}:{client_key(request)}"
    started, count = _buckets.get(key, (now, 0))

    if now - started >= window:
        started, count = now, 0

    count += 1
    _buckets[key] = (started, count)

    if count > max_attempts:
        retry_after = max(1, window - (now - started))
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )


def reset(request: Request, scope: str) -> None:
    """Clear the counter for this client and scope after a success.

    Called on successful authentication so a legitimate user who fat-fingered
    a few codes is not left throttled.
    """
    _buckets.pop(f"{scope}:{client_key(request)}", None)


def clear() -> None:
    """Drop every counter (used by tests)."""
    _buckets.clear()
