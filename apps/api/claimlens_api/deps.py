from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import lru_cache

from fastapi import Depends, HTTPException, Request

from claimlens.container import Container, build_container
from claimlens.services import ClaimService, Principal
from claimlens.settings import get_settings


@lru_cache
def get_container() -> Container:
    return build_container(get_settings())


def get_service(c: Container = Depends(get_container)) -> ClaimService:
    return ClaimService(c)


class RateLimiter:
    """Per-principal sliding window, in memory. Good enough for one replica; behind several replicas put the
    real limit at the gateway (API Management / Front Door) and keep this as a backstop."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(
                    429,
                    "too many requests; slow down",
                    headers={"Retry-After": str(int(self.window))},
                )
            q.append(now)


def limited(limiter: RateLimiter, scope: str):  # type: ignore[no-untyped-def]
    from claimlens_api.auth import current_principal

    def dep(request: Request, p: Principal = Depends(current_principal)) -> Principal:
        limiter.check(f"{scope}:{p.tenant_id}:{p.subject}")
        return p

    return dep
