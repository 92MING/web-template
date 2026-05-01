"""KV-backed sidecar for ``expire_at`` / ``accessed_at`` / ``size`` metadata.

This sidecar exists so storage backends with rigid schemas (notably Milvus)
can still honour our expire / max_size contract on collections that were
created **outside** the framework — i.e. that lack the ``_expire_at`` and
``_accessed_at`` declared fields.

Design:
- All metadata is stored in the global KV client (``KVClientBase.Default()``)
  under per-(backend, collection, id) keys::

      _expire:{backend}:{collection}:{id}  →  {"e": expire_at, "a": accessed_at, "s": size}

- Iteration during cleanup uses ``KVClientBase.keys(prefix=...)``.

- This sidecar is a *parallel* metadata path: backends that already have
  native expire columns (Mongo / Redis / SQL) keep using them. Backends that
  cannot extend an external schema (Milvus) opt into the sidecar per-collection.

Activation triggers:
- The model declares ``__NoExpireField__: ClassVar[bool] = True`` (explicit
  user opt-out from schema modification), or
- The backend probes the existing physical collection and detects the
  ``_expire_at`` / ``_accessed_at`` fields are missing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, TypedDict, cast


if TYPE_CHECKING:
    from .kv import KVClientBase


_PREFIX_ROOT = '_expire'


class SidecarEntry(TypedDict, total=False):
    """Per-id sidecar metadata. All fields optional so partial updates are cheap.

    Keys are intentionally short to keep KV payloads compact.
    """
    e: float | None  # expire_at (absolute UNIX ts) or None for "never"
    a: float          # accessed_at (absolute UNIX ts)
    s: int            # size in bytes (best-effort, may be 0)


class ExpireSidecar:
    """KV-backed sidecar for one (backend, collection) pair.

    The sidecar is intentionally stateless beyond its key prefix; every method
    talks directly to the KV client. This keeps multi-worker semantics correct
    (no in-process cache to invalidate).
    """

    def __init__(
        self,
        *,
        backend: str,
        collection: str,
        kv_client: "KVClientBase | None" = None,
    ) -> None:
        if not backend:
            raise ValueError('ExpireSidecar requires a non-empty backend tag.')
        if not collection:
            raise ValueError('ExpireSidecar requires a non-empty collection name.')
        self._backend = backend
        self._collection = collection
        self._kv_client = kv_client

    # ── KV plumbing ─────────────────────────────────────────────────────────

    def _kv(self) -> "KVClientBase":
        if self._kv_client is not None:
            kv = self._kv_client
        else:
            from .kv import KVClientBase
            kv = KVClientBase.Default()
        if not kv.started:
            kv.start()
        return kv

    @property
    def prefix(self) -> str:
        """KV key prefix for this (backend, collection) pair, including trailing colon."""
        return f'{_PREFIX_ROOT}:{self._backend}:{self._collection}:'

    def _key(self, object_id: str) -> str:
        return f'{self.prefix}{object_id}'

    def _id_from_key(self, key: str) -> str:
        return key[len(self.prefix):]

    # ── core read/write ─────────────────────────────────────────────────────

    async def get_metadata(self, object_id: str) -> SidecarEntry | None:
        raw = await self._kv().get(self._key(object_id))
        if raw is None:
            return None
        if not isinstance(raw, dict):
            return None
        return cast(SidecarEntry, raw)

    async def upsert(
        self,
        object_id: str,
        *,
        expire_at: float | None,
        accessed_at: float,
        size: int = 0,
    ) -> None:
        entry: SidecarEntry = {'e': expire_at, 'a': accessed_at, 's': int(size)}
        await self._kv().set(self._key(object_id), entry)

    async def set_expire(self, object_id: str, expire_at: float | None) -> bool:
        kv = self._kv()
        key = self._key(object_id)
        existing = await kv.get(key)
        if existing is None:
            from .base import _now_ts
            entry: SidecarEntry = {'e': expire_at, 'a': _now_ts(), 's': 0}
        else:
            if not isinstance(existing, dict):
                return False
            entry = cast(SidecarEntry, dict(existing))
            entry['e'] = expire_at
        await kv.set(key, entry)
        return True

    async def get_expire(self, object_id: str) -> float | None:
        entry = await self.get_metadata(object_id)
        if entry is None:
            return None
        return entry.get('e')

    async def touch_access(self, object_id: str, accessed_at: float) -> None:
        kv = self._kv()
        key = self._key(object_id)
        existing = await kv.get(key)
        if existing is None:
            entry: SidecarEntry = {'e': None, 'a': accessed_at, 's': 0}
        elif not isinstance(existing, dict):
            return
        else:
            entry = cast(SidecarEntry, dict(existing))
            entry['a'] = accessed_at
        await kv.set(key, entry)

    async def delete(self, object_id: str) -> bool:
        return await self._kv().delete(self._key(object_id))

    async def delete_many(self, object_ids: Iterable[str]) -> int:
        kv = self._kv()
        n = 0
        for oid in object_ids:
            if await kv.delete(self._key(oid)):
                n += 1
        return n

    # ── iteration helpers (cleanup loops) ───────────────────────────────────

    async def list_entries(self) -> list[tuple[str, SidecarEntry]]:
        """Return ``(object_id, entry)`` tuples for every id tracked under this collection."""
        kv = self._kv()
        keys = await kv.keys(prefix=self.prefix)
        out: list[tuple[str, SidecarEntry]] = []
        for k in keys:
            raw = await kv.get(k)
            if isinstance(raw, dict):
                out.append((self._id_from_key(k), cast(SidecarEntry, raw)))
        return out

    async def list_expired(self, now: float) -> list[str]:
        """Return ids whose stored ``expire_at`` is set and ``<= now``."""
        expired: list[str] = []
        for oid, entry in await self.list_entries():
            e = entry.get('e')
            if e is not None and e <= now:
                expired.append(oid)
        return expired


__all__ = ['ExpireSidecar', 'SidecarEntry']
