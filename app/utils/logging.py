"""Structured logging & metrics helpers."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

from app.core.config import get_settings
from app.utils.pii import PIIFilter

settings = get_settings()


def setup_logging() -> None:
    """Configure the root logger for the application."""
    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    
    # Add PII filter to root logger for privacy compliance
    root_logger = logging.getLogger()
    pii_filter = PIIFilter(pii_types=["email", "phone", "ssn", "credit_card"])
    root_logger.addFilter(pii_filter)
    
    # Quiet noisy third-party loggers
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.debug else logging.WARNING
    )


class MetricsCollector:
    """Very lightweight in-process metrics (no external dependency).

    In production, replace this with Prometheus / StatsD pushes.
    """

    def __init__(self, retry_budget_per_hour: int = 1000) -> None:
        self._data: dict[str, list[float]] = {
            "token_usage": [],
            "latency_ms": [],
            "validation_failures": [],
            "retry_attempts": [],
        }
        self._retry_budget = retry_budget_per_hour
        self._retry_timestamps: list[float] = []

    def record_tokens(self, count: int) -> None:
        self._data["token_usage"].append(float(count))

    def record_latency(self, ms: float) -> None:
        self._data["latency_ms"].append(ms)

    def record_validation_failure(self) -> None:
        self._data["validation_failures"].append(1.0)

    def record_retry(self) -> None:
        self._data["retry_attempts"].append(1.0)
        self._retry_timestamps.append(time.time())

    def _cleanup_retry_timestamps(self) -> None:
        """Remove retry timestamps older than 1 hour."""
        cutoff = time.time() - 3600
        self._retry_timestamps = [t for t in self._retry_timestamps if t > cutoff]

    def get_retry_budget_status(self) -> dict:
        """Get current retry budget usage."""
        self._cleanup_retry_timestamps()
        used = len(self._retry_timestamps)
        remaining = max(0, self._retry_budget - used)
        return {
            "budget_per_hour": self._retry_budget,
            "used_this_hour": used,
            "remaining": remaining,
            "exhausted": remaining <= 0,
        }

    def is_retry_budget_exhausted(self) -> bool:
        """Check if retry budget is exhausted (for circuit-breaker behavior)."""
        self._cleanup_retry_timestamps()
        return len(self._retry_timestamps) >= self._retry_budget

    def _percentile(self, values: list[float], p: float) -> float:
        """Calculate the p-th percentile of a list of values."""
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_vals) else f
        return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

    def summary(self) -> dict:
        out: dict = {}
        for key, values in self._data.items():
            out[key] = {
                "count": len(values),
                "total": round(sum(values), 2),
                "avg": round(sum(values) / len(values), 2) if values else 0,
            }
        
        # Add latency percentiles for dashboard
        latencies = self._data["latency_ms"]
        out["latency_percentiles"] = {
            "p50": round(self._percentile(latencies, 50), 2),
            "p95": round(self._percentile(latencies, 95), 2),
            "p99": round(self._percentile(latencies, 99), 2),
            "min": round(min(latencies), 2) if latencies else 0,
            "max": round(max(latencies), 2) if latencies else 0,
        }
        
        out["retry_budget"] = self.get_retry_budget_status()
        out["collected_at"] = datetime.now(timezone.utc).isoformat()
        return out


# Singleton
metrics = MetricsCollector()
