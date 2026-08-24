import time
from collections.abc import Callable

import httpx


def with_retry(fn: Callable, attempts: int = 3, backoff: float = 0.5):
    """Standard retry wrapper. All outbound HTTP goes through this."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(backoff * (2 ** i))
    raise RuntimeError("retries exhausted") from last
