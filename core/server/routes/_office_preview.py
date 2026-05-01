# -*- coding: utf-8 -*-
"""Stub for office preview (proj-template placeholder)."""

from typing import Any


class OfficePreviewConfig:
    pass


def get_office_preview_config() -> OfficePreviewConfig:
    return OfficePreviewConfig()


async def office_preview(file_path: str, **kwargs: Any) -> bytes:
    return b""


async def office_preview_pdf(file_path: str, **kwargs: Any) -> bytes:
    return b""


async def office_preview_thumb(file_path: str, **kwargs: Any) -> bytes:
    return b""


def office_preview_cache_key(file_path: str, **kwargs: Any) -> str:
    return f"office_preview:{file_path}"


def office_preview_cache_paths(file_path: str, **kwargs: Any) -> dict[str, str]:
    return {}


def office_preview_kind(file_path: str, **kwargs: Any) -> str:
    return "unknown"


def office_preview_payload(file_path: str, **kwargs: Any) -> dict[str, Any]:
    return {}


def presentation_preview_payload(file_path: str, **kwargs: Any) -> dict[str, Any]:
    return {}
