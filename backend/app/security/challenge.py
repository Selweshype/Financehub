"""Server-side WebAuthn challenge store.

Security finding C4: the previous implementation assigned the challenge to an
attribute on the per-request object (``request.session_challenge``), which is
discarded as soon as the response is sent.  No challenge was ever compared, so
a captured assertion could be replayed indefinitely.

Challenges are now generated server-side, held here under an opaque id, and
popped exactly once on completion.  A challenge that is replayed, expired, or
never issued fails closed.

NOTE ON DEPLOYMENT: this store is in-process.  FinanceHub is a single-user app
served by a single Uvicorn worker (see ``entrypoint.sh``), so that is correct
today.  If the deployment ever grows to multiple workers or processes, this
must move to the database or a shared cache — otherwise a challenge issued by
one worker will not be found by another and WebAuthn will silently break.
"""
from __future__ import annotations

import secrets
import time

# How long an issued challenge remains valid.  The WebAuthn client-side
# timeout is 60 s; 120 s leaves room for slow authenticators without keeping
# a replayable window open for long.
CHALLENGE_TTL = 120

# Hard cap so a flood of /begin requests cannot grow the process heap.
_MAX_ENTRIES = 64

# challenge_id -> (challenge_bytes, expires_at, purpose)
_store: dict[str, tuple[bytes, int, str]] = {}


def _purge_expired(now: int) -> None:
    """Drop every entry whose TTL has elapsed."""
    for key in [k for k, (_, exp, _) in _store.items() if exp <= now]:
        _store.pop(key, None)


def issue(purpose: str) -> tuple[str, bytes]:
    """Generate and store a fresh challenge.

    *purpose* is either ``"registration"`` or ``"authentication"``; it is bound
    into the entry so a registration challenge cannot be redeemed against the
    authentication endpoint.

    Returns ``(challenge_id, challenge_bytes)``.
    """
    now = int(time.time())
    _purge_expired(now)

    # Evict oldest entries if an unauthenticated caller spams /begin.
    while len(_store) >= _MAX_ENTRIES:
        oldest = min(_store, key=lambda k: _store[k][1])
        _store.pop(oldest, None)

    challenge_id = secrets.token_urlsafe(16)
    challenge = secrets.token_bytes(32)
    _store[challenge_id] = (challenge, now + CHALLENGE_TTL, purpose)
    return challenge_id, challenge


def consume(challenge_id: str, purpose: str) -> bytes | None:
    """Pop and return the challenge for *challenge_id*, or None if invalid.

    Single-use: a second call with the same id always returns None, which is
    what makes replay impossible.  Returns None when the id is unknown, the
    entry has expired, or the stored purpose does not match.
    """
    now = int(time.time())
    _purge_expired(now)

    entry = _store.pop(challenge_id, None)
    if entry is None:
        return None

    challenge, expires_at, stored_purpose = entry
    if expires_at <= now or stored_purpose != purpose:
        return None
    return challenge


def clear() -> None:
    """Drop every stored challenge (used by tests)."""
    _store.clear()
