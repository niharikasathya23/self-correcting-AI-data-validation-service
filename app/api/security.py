"""API security: authentication, rate limiting, and request validation."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from app.api.errors import AuthenticationError, ErrorCode, RateLimitError
from app.core.config import get_settings
from app.services.distributed_controls import check_rate_limit_distributed

logger = logging.getLogger(__name__)
settings = get_settings()

# ═══════════════════════════════════════════════════════════════════════
# API Key Authentication
# ═══════════════════════════════════════════════════════════════════════

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _hash_key(key: str) -> str:
    """Hash API key for safe comparison and logging."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Depends(_api_key_header),
) -> str:
    """Validate API key from X-API-Key header.

    Returns the key identifier (hashed) for rate limiting and audit.
    If auth is disabled (no keys configured), returns 'anonymous'.
    """
    configured_keys = settings.api_keys

    # Auth disabled — allow all requests
    if not configured_keys:
        return "anonymous"

    if not api_key:
        logger.warning("Missing API key from %s", request.client.host if request.client else "unknown")
        raise AuthenticationError(ErrorCode.AUTH_MISSING_KEY, "X-API-Key header required")

    if api_key not in configured_keys:
        logger.warning("Invalid API key attempt: %s", _hash_key(api_key))
        raise AuthenticationError(ErrorCode.AUTH_INVALID_KEY, "Invalid API key")

    return _hash_key(api_key)


# ═══════════════════════════════════════════════════════════════════════
# Rate Limiting (in-memory sliding window)
# ═══════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple in-memory sliding window rate limiter.

    For production, replace with Redis-based limiter for multi-instance support.
    """

    def __init__(self, requests_per_minute: int = 60, window_seconds: int = 60):
        self.rpm = requests_per_minute
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, key: str, now: float) -> None:
        """Remove timestamps outside the current window."""
        cutoff = now - self.window
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """Check if request is allowed.

        Returns (allowed, remaining, reset_seconds).
        """
        now = time.time()
        self._cleanup(key, now)

        current_count = len(self._requests[key])
        remaining = max(0, self.rpm - current_count)
        reset_seconds = int(self.window - (now - self._requests[key][0])) if self._requests[key] else self.window

        if current_count >= self.rpm:
            return False, 0, reset_seconds

        self._requests[key].append(now)
        return True, remaining - 1, reset_seconds

    def get_usage(self, key: str) -> dict:
        """Get current usage stats for a key."""
        now = time.time()
        self._cleanup(key, now)
        current_count = len(self._requests[key])
        return {
            "limit": self.rpm,
            "used": current_count,
            "remaining": max(0, self.rpm - current_count),
            "window_seconds": self.window,
        }


# Global rate limiter instance
_rate_limiter = RateLimiter(
    requests_per_minute=settings.rate_limit_rpm,
    window_seconds=60,
)


async def check_rate_limit(
    request: Request,
    api_key_id: str = Depends(verify_api_key),
) -> str:
    """Rate limit middleware. Raises 429 if limit exceeded.

    Returns the API key identifier for downstream use.
    """
    allowed, remaining, reset_seconds = await check_rate_limit_distributed(
        key=api_key_id,
        rpm=settings.rate_limit_rpm,
        window_seconds=60,
    )

    # Add rate limit headers to response
    request.state.rate_limit_remaining = remaining
    request.state.rate_limit_reset = reset_seconds

    if not allowed:
        logger.warning("Rate limit exceeded for key: %s", api_key_id)
        raise RateLimitError(retry_after=reset_seconds)

    return api_key_id


def get_rate_limit_usage(key: str) -> dict:
    """Get rate limit usage for a specific key."""
    return _rate_limiter.get_usage(key)
