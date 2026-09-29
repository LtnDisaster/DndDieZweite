"""Tiny in-memory rate limiter for auth endpoints (no external infra).

A small fixed window per (bucket, client). Enough to blunt credential-stuffing
against /login and abuse of /register on a small self-hosted install. State is
per-process and ephemeral — acceptable for a single-instance deployment."""
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_TRUST_PROXY = os.environ.get("VTT_TRUST_PROXY") == "1"
_hits: dict[tuple, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    if _TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit(bucket: str, request: Request, max_n: int = 10, window: int = 60):
    now = time.time()
    q = _hits[(bucket, client_ip(request))]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= max_n:
        raise HTTPException(429, "Too many attempts — please slow down")
    q.append(now)


def reset(bucket: str, request: Request):
    """Clear a bucket after a successful action (e.g. a good login)."""
    _hits.pop((bucket, client_ip(request)), None)
