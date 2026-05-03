"""Stable tool error_code strings — aligned with ``data/meta/error_codes.yaml`` (SSOT for descriptions)."""

from __future__ import annotations

from typing import Final, FrozenSet


class ErrorCode:
    UPSTREAM_FETCH_FAILED: Final[str] = "UPSTREAM_FETCH_FAILED"
    RATE_LIMITED: Final[str] = "RATE_LIMITED"
    INVALID_PARAMS: Final[str] = "INVALID_PARAMS"
    NO_DATA: Final[str] = "NO_DATA"
    PLUGIN_UNAVAILABLE: Final[str] = "PLUGIN_UNAVAILABLE"
    CACHE_MISS: Final[str] = "CACHE_MISS"


ERROR_CODE_KEYS: FrozenSet[str] = frozenset(
    {
        ErrorCode.UPSTREAM_FETCH_FAILED,
        ErrorCode.RATE_LIMITED,
        ErrorCode.INVALID_PARAMS,
        ErrorCode.NO_DATA,
        ErrorCode.PLUGIN_UNAVAILABLE,
        ErrorCode.CACHE_MISS,
    }
)


class QualityStatus:
    OK: Final[str] = "ok"
    DEGRADED: Final[str] = "degraded"
    ERROR: Final[str] = "error"


QUALITY_ENUM: FrozenSet[str] = frozenset(
    {QualityStatus.OK, QualityStatus.DEGRADED, QualityStatus.ERROR}
)
