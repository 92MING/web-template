import fnmatch
import re

from datetime import date as Date
from datetime import datetime, time as DateTimeTime, timedelta
from typing import Literal

from pydantic import BaseModel, Field


class _ResetTime(BaseModel):
    date: Date | None = None
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class SlidingWindowRateLimit(BaseModel):
    mode: Literal["sliding_window"] = "sliding_window"
    reset_interval_seconds: float = Field(gt=0)
    capacity: int = Field(ge=1)


class FixedWindowRateLimit(BaseModel):
    mode: Literal["fixed_window"] = "fixed_window"
    reset_time: _ResetTime = Field(default_factory=_ResetTime)
    capacity: int = Field(ge=1)


class RateLimitConfig(BaseModel):
    minimum_interval_seconds: float = Field(default=0.0, ge=0.0)
    limits: list[SlidingWindowRateLimit | FixedWindowRateLimit] = Field(default_factory=list)


def normalize_patterns(patterns: list[str]) -> list[str]:
    normalized: list[str] = []
    for pattern in patterns:
        text = str(pattern or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def normalize_whitelist_routes_value(value: object) -> list[str]:
    if value is None:
        return ["*"]
    if value == "all":
        return ["*"]
    if isinstance(value, list):
        normalized = normalize_patterns([str(item) for item in value])
        return normalized or ["*"]
    text = str(value or "").strip()
    if not text or text == "all":
        return ["*"]
    return normalize_patterns([text]) or ["*"]


def whitelist_routes_is_all(patterns: list[str]) -> bool:
    normalized = normalize_patterns(patterns)
    return not normalized or normalized == ["*"] or normalized == ["all"]


def export_whitelist_routes(patterns: list[str]) -> Literal["all"] | list[str]:
    return "all" if whitelist_routes_is_all(patterns) else normalize_patterns(patterns)


_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _compile_route_pattern(pattern: str) -> re.Pattern[str]:
    cached = _PATTERN_CACHE.get(pattern)
    if cached is not None:
        return cached
    compiled = re.compile(fnmatch.translate(pattern))
    _PATTERN_CACHE[pattern] = compiled
    return compiled


def match_route_pattern(route: str, pattern: str) -> bool:
    return bool(_compile_route_pattern(pattern).match(route))


def is_route_allowed(*, banned: bool, blacklist_routes: list[str], whitelist_routes: list[str], route: str) -> bool:
    if banned:
        return False
    if any(match_route_pattern(route, pattern) for pattern in blacklist_routes):
        return False
    if not whitelist_routes_is_all(whitelist_routes) and not any(
        match_route_pattern(route, pattern)
        for pattern in whitelist_routes
    ):
        return False
    return True


def fixed_window_bounds(reset_time: _ResetTime, now_ts: float) -> tuple[float, float]:
    now = datetime.fromtimestamp(now_ts)
    anchor_date = reset_time.date or now.date()
    anchor = datetime.combine(anchor_date, DateTimeTime(hour=reset_time.hour, minute=reset_time.minute))
    if reset_time.date is None:
        if now < anchor:
            anchor -= timedelta(days=1)
        return anchor.timestamp(), (anchor + timedelta(days=1)).timestamp()
    if now < anchor:
        return anchor.timestamp(), (anchor + timedelta(days=1)).timestamp()
    elapsed_days = int((now - anchor).total_seconds() // 86400)
    window_start = anchor + timedelta(days=elapsed_days)
    window_end = window_start + timedelta(days=1)
    return window_start.timestamp(), window_end.timestamp()


__all__ = [
    "SlidingWindowRateLimit",
    "FixedWindowRateLimit",
    "RateLimitConfig",
    "normalize_patterns",
    "normalize_whitelist_routes_value",
    "whitelist_routes_is_all",
    "export_whitelist_routes",
    "match_route_pattern",
    "is_route_allowed",
    "fixed_window_bounds",
]