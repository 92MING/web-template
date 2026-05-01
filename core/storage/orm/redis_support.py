from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis as _SyncRedis
    from redis.asyncio import Redis as _AsyncRedis


_REDIS_JSON_MODULE_NAMES = frozenset({"rejson", "redisjson", "json"})
_REDIS_JSON_REQUIRED_COMMANDS = frozenset({"json.get", "json.set"})


@dataclass(frozen=True)
class RedisRuntimeCapabilities:
    version: tuple[int, int, int]
    version_text: str
    modules: frozenset[str]
    acl_categories: frozenset[str]
    json_acl_commands: frozenset[str]
    has_json_commands: bool
    has_vectorset_commands: bool
    has_search_commands: bool

    @property
    def has_json_module(self) -> bool:
        return any(name in _REDIS_JSON_MODULE_NAMES for name in self.modules)


def parse_redis_version(value: str | bytes | int | None) -> tuple[int, int, int]:
    text = str(value or "0.0.0")
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _decode_redis_text(value: bytes | str | int | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def normalize_redis_module_names(payload: object) -> frozenset[str]:
    names: set[str] = set()
    for item in payload or []:
        module_name: object | None = None
        if isinstance(item, Mapping):
            module_name = item.get("name")
        elif isinstance(item, (list, tuple)):
            values = list(item)
            for index in range(0, max(0, len(values) - 1), 2):
                if _decode_redis_text(values[index]).strip().lower() == "name":
                    module_name = values[index + 1]
                    break
        if module_name is not None:
            names.add(_decode_redis_text(module_name).strip().lower())
    return frozenset(names)


def redis_command_available(client: _SyncRedis, command_name: str) -> bool:
    try:
        result = client.execute_command("COMMAND", "INFO", command_name)
    except Exception:
        return False
    if isinstance(result, Mapping):
        normalized = command_name.strip().upper()
        return any(_decode_redis_text(key).strip().upper() == normalized for key in result.keys())
    if isinstance(result, (list, tuple)):
        return bool(result) and result[0] is not None
    return bool(result)


def _normalize_acl_values(payload: object) -> frozenset[str]:
    if not isinstance(payload, (list, tuple)):
        return frozenset()
    return frozenset(
        _decode_redis_text(item).strip().lower()
        for item in payload
        if _decode_redis_text(item).strip()
    )


def redis_acl_categories(client: _SyncRedis) -> frozenset[str]:
    try:
        payload = client.execute_command("ACL", "CAT")
    except Exception:
        return frozenset()
    return _normalize_acl_values(payload)


def redis_acl_category_commands(client: _SyncRedis, category: str) -> frozenset[str]:
    try:
        payload = client.execute_command("ACL", "CAT", category)
    except Exception:
        return frozenset()
    return _normalize_acl_values(payload)


def load_redis_runtime_capabilities(client: _SyncRedis) -> RedisRuntimeCapabilities:
    try:
        info = client.info("server") or {}
    except Exception:
        info = {}
    version_text = _decode_redis_text((info or {}).get("redis_version"))
    version = parse_redis_version(version_text)
    try:
        module_payload = client.execute_command("MODULE", "LIST") or []
    except Exception:
        module_payload = []
    acl_categories = redis_acl_categories(client)
    json_acl_commands = redis_acl_category_commands(client, "json") if version >= (8, 0, 0) else frozenset()
    has_json_commands = _REDIS_JSON_REQUIRED_COMMANDS.issubset(json_acl_commands)
    return RedisRuntimeCapabilities(
        version=version,
        version_text=version_text or "0.0.0",
        modules=normalize_redis_module_names(module_payload),
        acl_categories=acl_categories,
        json_acl_commands=json_acl_commands,
        has_json_commands=has_json_commands,
        has_vectorset_commands=redis_command_available(client, "VADD") and redis_command_available(client, "VSIM"),
        has_search_commands=redis_command_available(client, "FT.CREATE") and redis_command_available(client, "FT.SEARCH"),
    )


def ensure_redis_orm_supported(capabilities: RedisRuntimeCapabilities) -> None:
    if capabilities.version >= (8, 0, 0):
        if capabilities.has_json_commands and capabilities.has_search_commands:
            return
        categories = ", ".join(sorted(capabilities.acl_categories)) or "none"
        commands = ", ".join(sorted(capabilities.json_acl_commands)) or "none"
        raise RuntimeError(
            "Redis ORM requires Redis >= 8.0 with JSON support exposed by `ACL CAT json` and RediSearch commands. "
            f"Current Redis is {capabilities.version_text}; ACL categories: {categories}; ACL CAT json: {commands}; FT support: {capabilities.has_search_commands}."
        )
    if capabilities.has_json_module and capabilities.has_search_commands:
        return
    module_text = ", ".join(sorted(capabilities.modules)) or "none"
    raise RuntimeError(
        "Redis ORM requires Redis >= 8.0 with native JSON support and RediSearch, or RedisJSON+RediSearch modules on older Redis. "
        f"Current Redis is {capabilities.version_text} with modules: {module_text}; FT support: {capabilities.has_search_commands}."
    )


def ensure_redis_vector_supported(capabilities: RedisRuntimeCapabilities) -> None:
    if capabilities.version < (8, 0, 0):
        raise RuntimeError(
            "Redis vector backend requires Redis >= 8.0. "
            f"Current Redis is {capabilities.version_text}."
        )
    if capabilities.has_json_commands and capabilities.has_search_commands:
        return
    categories = ", ".join(sorted(capabilities.acl_categories)) or "none"
    commands = ", ".join(sorted(capabilities.json_acl_commands)) or "none"
    raise RuntimeError(
        "Redis vector backend requires Redis >= 8.0 with JSON support exposed by `ACL CAT json` and RediSearch commands. "
        f"Current Redis is {capabilities.version_text}; ACL categories: {categories}; ACL CAT json: {commands}; FT support: {capabilities.has_search_commands}."
    )


# ── Async variants ────────────────────────────────────────────────────────────


async def async_redis_command_available(client: _AsyncRedis, command_name: str) -> bool:
    try:
        result = await client.execute_command("COMMAND", "INFO", command_name)
    except Exception:
        return False
    if isinstance(result, Mapping):
        normalized = command_name.strip().upper()
        return any(_decode_redis_text(key).strip().upper() == normalized for key in result.keys())
    if isinstance(result, (list, tuple)):
        return bool(result) and result[0] is not None
    return bool(result)


async def async_redis_acl_categories(client: _AsyncRedis) -> frozenset[str]:
    try:
        payload = await client.execute_command("ACL", "CAT")
    except Exception:
        return frozenset()
    return _normalize_acl_values(payload)


async def async_redis_acl_category_commands(client: _AsyncRedis, category: str) -> frozenset[str]:
    try:
        payload = await client.execute_command("ACL", "CAT", category)
    except Exception:
        return frozenset()
    return _normalize_acl_values(payload)


async def async_load_redis_runtime_capabilities(client: _AsyncRedis) -> RedisRuntimeCapabilities:
    try:
        info = await client.info("server") or {}
    except Exception:
        info = {}
    version_text = _decode_redis_text((info or {}).get("redis_version"))
    version = parse_redis_version(version_text)
    try:
        module_payload = await client.execute_command("MODULE", "LIST") or []
    except Exception:
        module_payload = []
    acl_categories = await async_redis_acl_categories(client)
    json_acl_commands = await async_redis_acl_category_commands(client, "json") if version >= (8, 0, 0) else frozenset()
    has_json_commands = _REDIS_JSON_REQUIRED_COMMANDS.issubset(json_acl_commands)
    return RedisRuntimeCapabilities(
        version=version,
        version_text=version_text or "0.0.0",
        modules=normalize_redis_module_names(module_payload),
        acl_categories=acl_categories,
        json_acl_commands=json_acl_commands,
        has_json_commands=has_json_commands,
        has_vectorset_commands=await async_redis_command_available(client, "VADD") and await async_redis_command_available(client, "VSIM"),
        has_search_commands=await async_redis_command_available(client, "FT.CREATE") and await async_redis_command_available(client, "FT.SEARCH"),
    )


__all__ = [
    "RedisRuntimeCapabilities",
    "ensure_redis_orm_supported",
    "ensure_redis_vector_supported",
    "load_redis_runtime_capabilities",
    "normalize_redis_module_names",
    "parse_redis_version",
    "redis_acl_categories",
    "redis_acl_category_commands",
    "redis_command_available",
]