import asyncio
import sqlite3 as _sqlite3
import threading

from typing import AsyncGenerator, Literal, Mapping, Self, Sequence, TYPE_CHECKING, overload
from typing_extensions import Unpack

if TYPE_CHECKING:
    import aiosqlite

from .field_schema import (
    ORMFieldSpec,
    detect_column_renames,
    native_field_names,
    sql_column_type,
)
from .field_metadata import (
    remap_payload_to_db,
)
from ..base import (
    _default_local_storage_root,
    _ensure_parent_dir,
    _json_dumps,
    _json_dumps_bytes,
    _json_loads,
    _normalize_expire_at,
    _now_ts,
    _ttl_from_expire_at,
    ObjectId,
    _validate_collection_name,
)
from .model import ORMModel, ModelT, CollectionLike, QueryLike
from .client_base import (
    HydratedORMDocument,
    ORMPayload,
    ORMPayloadLike,
    ORM_ClientBase,
    SQLiteORMClientInitParams,
    _get_schema_lock,
    _q,
    _native_column_values,
    _deserialize_row,
    _build_sql_sort_clauses,
    _query_to_sql_conditions,
    _require_sql_query_conditions,
    _sqlite_regexp,
    _fts_rowid,
    _normalize_raw_orm_payload,
    _raw_schema_from_specs,
    _safe_model_schema,
    _normalize_selected_fields,
    _project_selected_pairs,
    _build_sql_selected_columns,
    _orm_logger,
)


def _raw_kind_from_declared_sqlite_type(declared_type: str | None) -> str:
    normalized = str(declared_type or "").strip().lower()
    if not normalized:
        return "json"
    if "bool" in normalized:
        return "bool"
    if any(token in normalized for token in ("bigint", "smallint", "integer", "int")) and "point" not in normalized:
        return "int"
    if any(token in normalized for token in ("double", "float", "real", "numeric", "decimal")):
        return "float"
    if "date" in normalized and "time" not in normalized:
        return "date"
    if "time" in normalized:
        return "datetime"
    if any(token in normalized for token in ("char", "text", "clob", "varchar", "nvarchar", "string")):
        return "str"
    return "json"


def _schema_from_existing_sqlite_columns(collection: str, columns: Mapping[str, tuple[str, int | None]]) -> dict[str, object] | None:
    specs: dict[str, ORMFieldSpec] = {}
    for column_name, (declared_type, max_length) in columns.items():
        field_name = str(column_name or "").strip()
        if not field_name or field_name == "id" or field_name.startswith("_"):
            continue
        kind = _raw_kind_from_declared_sqlite_type(declared_type)
        specs[field_name] = ORMFieldSpec(
            field_name=field_name,
            column_name=field_name,
            kind=kind,
            nullable=True,
            index=None,
            max_length=max_length if kind == "str" else None,
        )
    return _raw_schema_from_specs(collection, specs) if specs else None

class SQLiteORMClient(ORM_ClientBase, type="sqlite"):
    _WRITE_BUFFER_DEFAULT = 1

    def __init__(self, **kwargs: Unpack[SQLiteORMClientInitParams]) -> None:
        self._db_path = _ensure_parent_dir(kwargs.get("db_path") or (_default_local_storage_root("orm") / "orm.sqlite3"))
        self._aio_conn: "aiosqlite.Connection | None" = None
        self._aio_conn_by_owner: "dict[tuple[int, int], aiosqlite.Connection]" = {}
        self._conn_init_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._conn_state_lock = threading.RLock()
        self._schema_ready = False
        # write coalescing
        self._pending_writes: int = 0
        self._write_buffer_size: int = int(kwargs.get("write_buffer_size", self._WRITE_BUFFER_DEFAULT))  # type: ignore[arg-type]
        # SQL template cache: collection_name → (data_sql, sys_sql, col_names)
        self._sql_cache: dict[str, tuple[str, str, list[str]]] = {}
        super().__init__(**kwargs)

    def _conn(self) -> None:  # kept as a tombstone; use _get_conn() instead
        raise RuntimeError("SQLiteORMClient: use `await self._get_conn()` (async)")

    async def _get_conn(self) -> 'aiosqlite.Connection':
        owner = (threading.get_ident(), id(asyncio.get_running_loop()))
        with self._conn_state_lock:
            cached = self._aio_conn_by_owner.get(owner)
            if cached is not None:
                self._aio_conn = cached
                return cached
            init_lock = self._conn_init_locks.get(owner)
            if init_lock is None:
                init_lock = asyncio.Lock()
                self._conn_init_locks[owner] = init_lock
        async with init_lock:
            with self._conn_state_lock:
                cached = self._aio_conn_by_owner.get(owner)
                if cached is not None:
                    self._aio_conn = cached
                    return cached
            import aiosqlite
            conn_task = aiosqlite.connect(str(self._db_path), timeout=30, isolation_level="IMMEDIATE")
            worker_thread = getattr(conn_task, "_thread", None)
            if worker_thread is not None:
                worker_thread.daemon = True
            conn = await conn_task
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA busy_timeout = 30000;")
            await conn.execute("PRAGMA journal_mode = WAL;")
            await conn.execute("PRAGMA synchronous = NORMAL;")
            await conn.execute("PRAGMA cache_size = -32000;")  # 32 MB page cache
            # ── load sqlite-regex extension (native regexp); fall back to Python UDF ──
            try:
                import sqlite_regex
                conn._conn.enable_load_extension(True)
                conn._conn.load_extension(sqlite_regex.loadable_path())
            except Exception:
                await conn.create_function("regexp", 2, _sqlite_regexp)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _orm_collections (
                    collection_name TEXT PRIMARY KEY,
                    model_module     TEXT,
                    model_name       TEXT,
                    schema_json      TEXT
                )
                """
            )
            # Migration: drop legacy created_at column from _orm_collections
            for _legacy_col in ("created_at",):
                try:
                    await conn.execute(f"ALTER TABLE _orm_collections DROP COLUMN {_legacy_col}")
                except Exception:
                    pass
            await conn.commit()
            with self._conn_state_lock:
                self._aio_conn_by_owner[owner] = conn
                self._aio_conn = conn
            self._schema_ready = True
            return conn

    def start(self) -> Self:
        """Mark the client as started; the DB connection is opened lazily on first use."""
        if self._started:
            return self
        self._mark_started()
        return self

    async def flush(self) -> None:
        """Commit any buffered writes to disk."""
        if self._pending_writes <= 0:
            return
        conn = await self._get_conn()
        await conn.commit()
        self._pending_writes = 0

    async def aclose(self) -> None:
        # flush pending writes before closing
        try:
            if self._pending_writes > 0:
                conn = self._aio_conn
                if conn is not None:
                    await conn.commit()
                    self._pending_writes = 0
        except Exception:
            pass
        with self._conn_state_lock:
            connections = list(self._aio_conn_by_owner.values())
            self._aio_conn_by_owner.clear()
            self._conn_init_locks.clear()
            self._aio_conn = None
        self._schema_ready = False
        self._mark_stopped()
        if not connections:
            return
        for conn in connections:
            try:
                await conn.close()
            except Exception as e:
                _orm_logger.warning("SQLiteORMClient.aclose() aiosqlite error: %s", e)

    def close(self) -> None:
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and loop.is_running():
                loop.create_task(self.aclose())
            else:
                temp_loop = asyncio.new_event_loop()
                try:
                    temp_loop.run_until_complete(self.aclose())
                finally:
                    temp_loop.close()
        except Exception as e:
            _orm_logger.warning("SQLiteORMClient.close() aiosqlite error: %s", e)

    def _table_sql(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f'"orm_{collection}"'

    def _sys_table_sql(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f'"_orm_{collection}_sys"'

    def _fts_table_sql(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f'"_orm_{collection}_fts"'

    def _fts_table_name(self, collection: str) -> str:
        """Unquoted FTS virtual table name (used inside MATCH subqueries)."""
        _validate_collection_name(collection)
        return f"_orm_{collection}_fts"

    def _get_fts_columns(self, collection: str) -> list[str]:
        """Return *sorted* list of column names that participate in FTS5 (indexed str fields).

        Only fields with ``index=True`` (explicitly requested) are included.
        ``index=None`` (align-with-DB) is handled by ``_ensure_field_schema``
        which resolves ``None`` to ``True``/``False`` based on existing DB state.
        """
        specs = self._get_native_field_specs(collection)
        if not specs:
            return []
        return sorted(spec.column_name for spec in specs.values() if spec.index is True and spec.kind == "str")

    async def _fetch_existing_columns(
        self,
        conn: "aiosqlite.Connection",
        collection: str,
        *,
        table_override: str | None = None,
    ) -> dict[str, tuple[str, int | None]]:
        table = table_override or self._table_sql(collection)
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        await cursor.close()
        return {
            str(row["name"]): (str(row["type"] or ""), None)
            for row in rows
        }

    async def _ensure_field_schema(self, conn: "aiosqlite.Connection", collection: str) -> None:
        """Ensure data table and sys table columns match the registered field specs.

        Handles ADD COLUMN for new fields, RENAME COLUMN for db_name changes,
        and blob_union ``{col}_type`` columns in the sys table.
        """
        specs = self._get_native_field_specs(collection)
        if not specs:
            return

        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)

        # ── inspect data table ──
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        await cursor.close()
        existing_columns: dict[str, str] = {
            str(row["name"]): str(row["type"] or "")
            for row in rows
        }

        idx_cursor = await conn.execute(f"PRAGMA index_list({table})")
        idx_rows = await idx_cursor.fetchall()
        await idx_cursor.close()
        existing_indexes = {str(row["name"]) for row in idx_rows}

        # ── detect renames before adding missing columns ──
        renames = detect_column_renames(existing_columns, specs, "sqlite")
        for old_col, spec in renames:
            try:
                await conn.execute(
                    f"ALTER TABLE {table} RENAME COLUMN {_q(old_col)} TO {_q(spec.column_name)}"
                )
                _orm_logger.info(
                    "SQLite field `%s`: renamed column %s → %s",
                    collection, old_col, spec.column_name,
                )
                existing_columns[spec.column_name] = existing_columns.pop(old_col)
                # drop old index if present
                old_idx = f"idx_{collection}_{old_col}"
                if old_idx in existing_indexes:
                    try:
                        await conn.execute(f"DROP INDEX IF EXISTS {old_idx}")
                    except Exception:
                        pass
            except Exception as exc:
                _orm_logger.warning(
                    "SQLite field `%s`: column rename %s → %s failed: %s",
                    collection, old_col, spec.column_name, exc,
                )

        # ── add missing columns + ensure indexes ──
        for spec in specs.values():
            desired_type = sql_column_type(spec, "sqlite")
            if spec.column_name not in existing_columns:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {_q(spec.column_name)} {desired_type}"
                )
            else:
                existing_type = str(existing_columns.get(spec.column_name) or "").upper()
                if existing_type and desired_type.upper() not in existing_type and existing_type not in desired_type.upper():
                    _orm_logger.warning(
                        "SQLite field `%s.%s` schema differs (db=%s, code=%s); keeping existing column.",
                        collection, spec.field_name, existing_type, desired_type,
                    )

            # str fields with index=True use FTS5 instead of B-tree (handled below)
            if spec.index is True and spec.kind == "str":
                continue
            index_name = f"idx_{collection}_{spec.column_name}"
            if spec.index is True:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({_q(spec.column_name)})"
                )
            elif spec.index is False and index_name in existing_indexes:
                # Explicit index=False → drop existing index
                try:
                    await conn.execute(f"DROP INDEX IF EXISTS {index_name}")
                    _orm_logger.info(
                        "SQLite field `%s.%s`: dropped index `%s` (index=False).",
                        collection, spec.field_name, index_name,
                    )
                except Exception as exc:
                    _orm_logger.warning(
                        "SQLite field `%s.%s`: failed to drop index `%s`: %s",
                        collection, spec.field_name, index_name, exc,
                    )
            # index=None → align with DB: do nothing (keep whatever exists)

        # ── ensure blob_union {col}_type columns in sys table ──
        sys_cursor = await conn.execute(f"PRAGMA table_info({sys_table})")
        sys_rows = await sys_cursor.fetchall()
        await sys_cursor.close()
        sys_existing = {str(row["name"]) for row in sys_rows}
        for spec in specs.values():
            if spec.kind == "blob_union":
                type_col = f"{spec.column_name}_type"
                if type_col not in sys_existing:
                    await conn.execute(
                        f"ALTER TABLE {sys_table} ADD COLUMN {_q(type_col)} TEXT"
                    )

        # ── FTS5 virtual table for indexed str fields (trigram tokenizer) ──
        fts_cols = self._get_fts_columns(collection)
        fts_table = self._fts_table_sql(collection)
        if fts_cols:
            # Check if FTS table exists and has the right columns
            fts_needs_rebuild = False
            try:
                fts_cur = await conn.execute(f"PRAGMA table_info({fts_table})")
                fts_rows = await fts_cur.fetchall()
                await fts_cur.close()
                existing_fts_cols = sorted(
                    str(r["name"]) for r in fts_rows
                    if str(r["name"]) != "_doc_id"
                )
                if existing_fts_cols != fts_cols:
                    fts_needs_rebuild = True
            except Exception:
                fts_needs_rebuild = True  # table doesn't exist

            if fts_needs_rebuild:
                await conn.execute(f"DROP TABLE IF EXISTS {fts_table}")
                fts_col_defs = ", ".join(_q(c) for c in fts_cols)
                await conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table} USING fts5("
                    f"{fts_col_defs}, _doc_id UNINDEXED, "
                    f"tokenize='trigram case_sensitive 0')"
                )
                # Backfill existing data into FTS
                sel_cols = ", ".join(_q(c) for c in fts_cols)
                await conn.execute(
                    f"INSERT INTO {fts_table}(rowid, {sel_cols}, _doc_id) "
                    f"SELECT rowid, {sel_cols}, \"id\" FROM {table}"
                )
        else:
            # No indexed str fields → drop FTS table if it exists
            await conn.execute(f"DROP TABLE IF EXISTS {fts_table}")

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        self.register_model(model_cls)
        collection = model_cls.CollectionName
        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        new_schema = _safe_model_schema(model_cls)
        specs = self._get_native_field_specs(collection)

        with _get_schema_lock(collection):
            conn = await self._get_conn()

            # ── data table: id + all field columns ──
            field_col_defs = ""
            if specs:
                col_lines = [
                    f"    {_q(spec.column_name)} {sql_column_type(spec, 'sqlite')}"
                    for spec in specs.values()
                ]
                field_col_defs = ",\n" + ",\n".join(col_lines)
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    "id" TEXT PRIMARY KEY{field_col_defs}
                )
                """
            )

            # ── sys table: id + system metadata ──
            blob_union_type_cols = ""
            for spec in specs.values():
                if spec.kind == "blob_union":
                    blob_union_type_cols += f',\n    {_q(spec.column_name + "_type")} TEXT'
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {sys_table} (
                    "id"        TEXT PRIMARY KEY,
                    expire_at   REAL,
                    "size"      INTEGER NOT NULL,
                    accessed_at REAL NOT NULL{blob_union_type_cols}
                )
                """
            )
            # Migration: drop legacy created_at/updated_at from sys table
            for _legacy_col in ("created_at", "updated_at"):
                try:
                    await conn.execute(f"ALTER TABLE {sys_table} DROP COLUMN {_legacy_col}")
                except Exception:
                    pass
            try:
                await conn.execute(f'DROP INDEX IF EXISTS "idx_{collection}_sys_created"')
            except Exception:
                pass

            # ── sys table indexes ──
            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{collection}_sys_expire" ON {sys_table}(expire_at)'
            )
            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{collection}_sys_access" ON {sys_table}(accessed_at)'
            )

            # ── register in _orm_collections ──
            await conn.execute(
                """
                INSERT INTO _orm_collections(collection_name, model_module, model_name, schema_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(collection_name) DO UPDATE SET
                    model_module=excluded.model_module,
                    model_name=excluded.model_name,
                    schema_json=excluded.schema_json
                """,
                (collection, model_cls.__module__, model_cls.__name__, _json_dumps(new_schema)),
            )
            await self._ensure_field_schema(conn, collection)

            # ── field-level indexes on data table ──
            # NOTE: must be AFTER _ensure_field_schema so that all columns exist.
            # Creating an index on a non-existent column creates a corrupt
            # expression index in SQLite (the identifier resolves to a string
            # literal instead of the future column).
            # Indexed str fields use FTS5 (created in _ensure_field_schema), not B-tree.
            for spec in specs.values():
                if spec.index is True and spec.kind != "str":
                    await conn.execute(
                        f'CREATE INDEX IF NOT EXISTS "idx_{collection}_{spec.column_name}" ON {table}({_q(spec.column_name)})'
                    )

            await conn.commit()
            self._mark_collection_known(collection)
            self._bootstrapped_collections.add(collection)

    async def _ensure_schemaless_collection(
        self,
        collection_name: str,
        payload: Mapping[str, object],
        *,
        schema: Mapping[str, object] | None = None,
    ) -> None:
        """Bootstrap or extend a schemaless (no-model) collection.

        Payload / schema keys are inferred into raw ORM field specs. New keys
        discovered in subsequent ``raw_set()`` calls trigger ``ALTER TABLE
        ADD COLUMN``.
        """
        conn = await self._get_conn()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        specs = await self._ensure_raw_specs(collection_name, schema=schema, payload=payload)
        schema_json = _raw_schema_from_specs(collection_name, specs) if specs else (dict(schema) if schema is not None else None)
        model_module = None
        model_name = None
        model_cls = self._resolve_collection_model(collection_name)
        if model_cls is not None:
            self.register_model(model_cls)
            model_module = model_cls.__module__
            model_name = model_cls.__name__
        else:
            existing_meta_cursor = await conn.execute(
                "SELECT model_module, model_name FROM _orm_collections WHERE collection_name = ?",
                (collection_name,),
            )
            existing_meta = await existing_meta_cursor.fetchone()
            await existing_meta_cursor.close()
            if existing_meta is not None:
                try:
                    model_module = existing_meta[0]
                    model_name = existing_meta[1]
                except Exception:
                    model_module = None
                    model_name = None

        if collection_name not in self._bootstrapped_collections:
            col_defs = ['"id" TEXT PRIMARY KEY']
            for spec in specs.values():
                col_defs.append(f"{_q(spec.column_name)} {sql_column_type(spec, 'sqlite')}")
            await conn.execute(f"CREATE TABLE IF NOT EXISTS {table}({', '.join(col_defs)})")
            await conn.execute(
                f'CREATE TABLE IF NOT EXISTS {sys_table}('
                f'"id" TEXT PRIMARY KEY, expire_at REAL, "size" INTEGER NOT NULL, accessed_at REAL NOT NULL)'
            )
            await conn.execute(
                "INSERT OR IGNORE INTO _orm_collections(collection_name, model_module, model_name, schema_json) "
                "VALUES (?, ?, ?, ?)",
                (collection_name, model_module, model_name, _json_dumps(schema_json) if schema_json is not None else None),
            )
            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{collection_name}_sys_expire" ON {sys_table}(expire_at)'
            )
            await conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{collection_name}_sys_access" ON {sys_table}(accessed_at)'
            )
            await conn.commit()
            self._mark_collection_known(collection_name)
            self._bootstrapped_collections.add(collection_name)

        # ---- ensure columns exist for inferred specs (schema evolution) ----
        await self._ensure_field_schema(conn, collection_name)

        await conn.execute(
            "UPDATE _orm_collections SET model_module = ?, model_name = ?, schema_json = ? WHERE collection_name = ?",
            (model_module, model_name, _json_dumps(schema_json) if schema_json is not None else None, collection_name),
        )
        await conn.commit()

    async def raw_create_collection(self, collection: str, schema: Mapping[str, object] | None = None) -> None:
        collection_name = _validate_collection_name(collection)
        await self._ensure_schemaless_collection(collection_name, {}, schema=schema)

    async def raw_set(
        self,
        collection: str,
        payload: ORMPayloadLike,
        *,
        expire: float | int | None = None,
        create_collection: bool = True,
    ) -> str:
        collection_name = _validate_collection_name(collection)
        normalized_payload = _normalize_raw_orm_payload(payload)
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        await self._ensure_schemaless_collection(collection_name, normalized_payload)

        object_id = str(normalized_payload.get("id") or normalized_payload.get("_id"))
        specs = self._get_native_field_specs(collection_name)
        column_values = _native_column_values(normalized_payload, specs)
        db_payload = remap_payload_to_db(normalized_payload, self._get_field_name_map(collection_name))
        size = len(_json_dumps_bytes(db_payload))
        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)

        data_columns = ['"id"', *[_q(c) for c in column_values.keys()]]
        data_update = ", ".join(f"{_q(c)}=excluded.{_q(c)}" for c in column_values)
        data_values = (object_id, *column_values.values())

        conn = await self._get_conn()
        data_sql = (
            f"INSERT INTO {self._table_sql(collection_name)}({', '.join(data_columns)})"
            f" VALUES ({', '.join(['?'] * len(data_columns))})"
        )
        if data_update:
            data_sql += f' ON CONFLICT("id") DO UPDATE SET {data_update}'
        else:
            data_sql += ' ON CONFLICT("id") DO NOTHING'
        await conn.execute(data_sql, data_values)

        await conn.execute(
            f"INSERT INTO {self._sys_table_sql(collection_name)}(\"id\", expire_at, \"size\", accessed_at)"
            f" VALUES (?, ?, ?, ?)"
            f' ON CONFLICT("id") DO UPDATE SET expire_at=excluded.expire_at, "size"=excluded."size", accessed_at=excluded.accessed_at',
            (object_id, expire_at, size, ts),
        )
        await conn.commit()
        if self._should_cleanup():
            asyncio.create_task(self._background_cleanup())
        return object_id

    async def drop_collection(self, collection: CollectionLike[ORMModel]) -> None:
        collection, model_cls = self._normalize_collection(collection)
        conn = await self._get_conn()
        await conn.execute(f"DROP TABLE IF EXISTS {self._table_sql(collection)}")
        await conn.execute(f"DROP TABLE IF EXISTS {self._sys_table_sql(collection)}")
        await conn.execute(f"DROP TABLE IF EXISTS {self._fts_table_sql(collection)}")
        await conn.execute("DELETE FROM _orm_collections WHERE collection_name = ?", (collection,))
        await conn.commit()
        self._collection_models.pop(collection, None)
        self._sql_cache.pop(collection, None)
        self._forget_collection(collection)
        if model_cls is not None:
            self.register_model(model_cls)

    def _collection_exists(self, collection: str) -> bool:
        """Treat physical ORM tables as existing even when metadata is missing."""
        if collection in self._known_collections:
            return True
        table_name = f"orm_{_validate_collection_name(collection)}"
        try:
            with _sqlite3.connect(str(self._db_path)) as conn:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
                    (table_name,),
                ).fetchone()
        except Exception:
            return False
        if row is not None:
            self._mark_collection_known(collection)
        return row is not None

    async def _async_collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT 1 FROM _orm_collections WHERE collection_name = ? LIMIT 1",
            (collection,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            await self._ensure_raw_specs(collection)
            self._mark_collection_known(collection)
            return True
        table_name = f"orm_{_validate_collection_name(collection)}"
        cursor = await conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            await self._ensure_raw_specs(collection)
            self._mark_collection_known(collection)
        return row is not None

    async def _load_stored_schema(self, collection: str) -> dict[str, object] | None:
        try:
            conn = await self._get_conn()
            cursor = await conn.execute(
                "SELECT schema_json FROM _orm_collections WHERE collection_name = ? LIMIT 1",
                (collection,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        except Exception:
            return None
        if row is None:
            existing_columns = await self._fetch_existing_columns(conn, collection)
            return _schema_from_existing_sqlite_columns(collection, existing_columns)
        raw = row[0]
        if not raw:
            existing_columns = await self._fetch_existing_columns(conn, collection)
            return _schema_from_existing_sqlite_columns(collection, existing_columns)
        if isinstance(raw, dict):
            return raw
        try:
            return _json_loads(raw)
        except Exception:
            existing_columns = await self._fetch_existing_columns(conn, collection)
            return _schema_from_existing_sqlite_columns(collection, existing_columns)

    @overload
    def dump_collection(self, collection: type[ModelT], *, as_model: Literal[True] = True) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def dump_collection(self, collection: type[ModelT], *, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def dump_collection(self, collection: str, *, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def dump_collection(self, collection: str, *, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    async def dump_collection(self, collection: CollectionLike[ORMModel], *, as_model: bool = True) -> AsyncGenerator[HydratedORMDocument, None]:
        async for item in self.search(collection, None, as_model=as_model):
            yield item

    @overload
    def search(self, collection: type[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def search(self, collection: type[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def search(self, collection: str, query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[True] = True) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search(self, collection: str, query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: Literal[False]) -> AsyncGenerator[ORMPayload, None]: ...

    async def search(self, collection: CollectionLike[ModelT], query: "QueryLike" = None, *, limit: int | None = None, offset: int = 0, as_model: bool = True) -> AsyncGenerator[HydratedORMDocument, None]:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return

        conn = await self._get_conn()
        now = _now_ts()
        native_fields = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)

        fts_cols = self._get_fts_columns(collection_name)
        fts_table_q = self._fts_table_sql(collection_name) if fts_cols else None
        fts_col_set = set(fts_cols) if fts_cols else None

        q_conds, q_params = _require_sql_query_conditions(
            query,
            "sqlite",
            native_fields=native_field_names(native_fields),
            field_name_map=fnmap,
            operation="search",
            fts_table=fts_table_q,
            fts_columns=fts_col_set,
        )

        where_parts: list[str] = ["(s.expire_at IS NULL OR s.expire_at > :_now)"]
        params: dict[str, object] = {"_now": now}
        where_parts.extend(q_conds)
        params.update(q_params)

        query_sql = (
            f"SELECT d.*, s.expire_at, s.accessed_at AS _sys_accessed_at"
            f" FROM {table} d LEFT JOIN {sys_table} s ON d.\"id\" = s.\"id\""
            f" WHERE {' AND '.join(where_parts)} ORDER BY d.rowid DESC"
        )
        if limit is not None:
            query_sql += " LIMIT :_lim"
            params["_lim"] = int(limit)
        if offset > 0:
            query_sql += " OFFSET :_off"
            params["_off"] = int(offset)

        cursor = await conn.execute(query_sql, params)
        try:
            async for row in cursor:
                payload = _deserialize_row(row, native_fields, field_name_map=fnmap)
                yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)
        finally:
            await cursor.close()

    async def selected_search(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[ORMPayload, None]:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return

        normalized_fields = _normalize_selected_fields(fields)
        native_fields = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)
        selected_columns = _build_sql_selected_columns(normalized_fields, dialect="sqlite", native_fields=native_fields, field_name_map=fnmap, table_alias="d")

        fts_cols = self._get_fts_columns(collection_name)
        fts_table_q = self._fts_table_sql(collection_name) if fts_cols else None
        fts_col_set = set(fts_cols) if fts_cols else None

        q_conds, q_params = _require_sql_query_conditions(
            query,
            "sqlite",
            native_fields=native_field_names(native_fields),
            field_name_map=fnmap,
            operation="selected_search",
            fts_table=fts_table_q,
            fts_columns=fts_col_set,
        )

        if selected_columns is None:
            async for item in self._selected_search_fallback(
                collection_name, fields=normalized_fields, query=query,
                limit=limit, offset=offset
            ):
                yield item
            return

        columns, aliases = selected_columns
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        now = _now_ts()
        all_conds = ["(s.expire_at IS NULL OR s.expire_at > :_sel_now)"] + q_conds
        params: dict[str, object] = {"_sel_now": now, **q_params}

        # selected_columns are expressions on d.* columns; wrap with JOIN
        sel_expr = ", ".join(columns)
        query_sql = (
            f"SELECT {sel_expr} FROM {table} d"
            f' LEFT JOIN {sys_table} s ON d."id" = s."id"'
            f" WHERE {' AND '.join(all_conds)} ORDER BY d.rowid DESC"
        )
        if limit is not None:
            query_sql += " LIMIT :_sel_lim"
            params["_sel_lim"] = int(limit)
        if offset > 0:
            query_sql += " OFFSET :_sel_off"
            params["_sel_off"] = int(offset)

        conn = await self._get_conn()
        cursor = await conn.execute(query_sql, params)
        try:
            async for row in cursor:
                yield _project_selected_pairs([(field, row[alias]) for field, alias in aliases])
        finally:
            await cursor.close()

    @overload
    async def search_one(self, collection: type[ModelT], query: "QueryLike" = None, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def search_one(self, collection: type[ModelT], query: "QueryLike" = None, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def search_one(self, collection: str, query: "QueryLike" = None, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def search_one(self, collection: str, query: "QueryLike" = None, *, as_model: Literal[False]) -> ORMPayload | None: ...

    async def search_one(self, collection: CollectionLike[ModelT], query: "QueryLike" = None, *, as_model: bool = True) -> HydratedORMDocument | None:
        return await self._first_or_none(
            self.search(collection, query, limit=1, as_model=as_model)
        )

    @overload
    async def search_by_id(self, collection: type[ModelT], id: str | ObjectId, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def search_by_id(self, collection: type[ModelT], id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def search_by_id(self, collection: str, id: str | ObjectId, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def search_by_id(self, collection: str, id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    async def search_by_id(self, collection: CollectionLike[ModelT], id: str | ObjectId, *, as_model: bool = True) -> HydratedORMDocument | None:
        return await self.get(collection, id, as_model=as_model)

    async def set(self, value: ORMModel | ORMPayloadLike, *, collection: CollectionLike[ORMModel] | None = None, expire: float | int | None = None, create_collection: bool = True) -> str:
        collection_name, payload, model_cls = self._normalize_value(value, collection=collection)
        if model_cls is None:
            raise ValueError(
                f"Collection `{collection_name}` does not map to a loaded ORMModel class; "
                "raw dict writes require a defined ORM model."
            )
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        if create_collection:
            await self.ensure_collection(model_cls)

        object_id = str(payload.get("id") or payload.get("_id"))
        specs = self._get_native_field_specs(collection_name)
        column_values = _native_column_values(payload, specs)

        # ── file_id ref counting on overwrite ──
        file_id_specs = [s for s in (specs or {}).values() if s.kind == "file_id"]
        if file_id_specs:
            try:
                old = await self.get(collection_name, object_id)
                old_payload = old if isinstance(old, dict) else (old._serialize_for_storage() if old else None)
            except Exception:
                old_payload = None
            await self._handle_file_id_ref_on_overwrite(collection_name, old_payload, payload)

        # ── estimate size (JSON byte length of the payload, for LRU eviction) ──
        db_payload = remap_payload_to_db(payload, self._get_field_name_map(collection_name))
        size = len(_json_dumps_bytes(db_payload))

        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)

        # ── UPSERT data table ──
        data_columns = ['"id"', *[_q(c) for c in column_values.keys()]]
        data_update = ", ".join(f"{_q(c)}=excluded.{_q(c)}" for c in column_values)
        data_values = (object_id, *column_values.values())

        conn = await self._get_conn()
        data_sql = (
            f"INSERT INTO {self._table_sql(collection_name)}({', '.join(data_columns)})"
            f" VALUES ({', '.join(['?'] * len(data_columns))})"
        )
        if data_update:
            data_sql += f' ON CONFLICT("id") DO UPDATE SET {data_update}'
        else:
            data_sql += ' ON CONFLICT("id") DO NOTHING'

        await conn.execute(data_sql, data_values)

        # ── UPSERT sys table ──
        sys_columns = ['"id"', "expire_at", '"size"', "accessed_at"]
        sys_update = "expire_at=excluded.expire_at, \"size\"=excluded.\"size\", accessed_at=excluded.accessed_at"
        sys_values: list[object] = [object_id, expire_at, size, ts]
        # blob_union type columns
        for spec in (specs or {}).values():
            if spec.kind == "blob_union":
                type_col = f"{spec.column_name}_type"
                sys_columns.append(_q(type_col))
                raw = payload.get(spec.field_name)
                sys_values.append(type(raw).Type if raw is not None and hasattr(type(raw), "Type") else None)
                sys_update += f", {_q(type_col)}=excluded.{_q(type_col)}"

        await conn.execute(
            f"INSERT INTO {self._sys_table_sql(collection_name)}({', '.join(sys_columns)})"
            f" VALUES ({', '.join(['?'] * len(sys_columns))})"
            f' ON CONFLICT("id") DO UPDATE SET {sys_update}',
            tuple(sys_values),
        )

        # ── sync FTS5 index ──
        fts_cols = self._get_fts_columns(collection_name)
        if fts_cols:
            fts_table = self._fts_table_sql(collection_name)
            fts_rid = _fts_rowid(object_id)
            await conn.execute(f"DELETE FROM {fts_table} WHERE rowid = ?", (fts_rid,))
            fts_values = [str(column_values.get(c) or "") for c in fts_cols]
            fts_col_list = ", ".join(["rowid"] + [_q(c) for c in fts_cols] + ["_doc_id"])
            fts_ph = ", ".join(["?"] * (len(fts_cols) + 2))
            await conn.execute(
                f"INSERT OR REPLACE INTO {fts_table}({fts_col_list}) VALUES ({fts_ph})",
                (fts_rid, *fts_values, object_id),
            )

        self._pending_writes += 1
        if self._pending_writes >= self._write_buffer_size:
            await conn.commit()
            self._pending_writes = 0
        if self._should_cleanup():
            asyncio.create_task(self._background_cleanup())
        return object_id

    async def set_many(
        self,
        values: Sequence[ORMModel | ORMPayloadLike],
        *,
        collection: CollectionLike[ORMModel] | None = None,
        expire: float | int | None = None,
        create_collection: bool = True,
    ) -> list[str]:
        batch = list(values)
        if not batch:
            return []

        collection_name, payloads, model_cls = self._normalize_batch_values(batch, collection=collection)
        if model_cls is None:
            return await ORM_ClientBase.set_many(
                self,
                batch,
                collection=collection,
                expire=expire,
                create_collection=create_collection,
            )

        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        if create_collection:
            await self.ensure_collection(model_cls)

        specs = self._get_native_field_specs(collection_name)
        field_name_map = self._get_field_name_map(collection_name)
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        ts = _now_ts()

        # ── determine column layout from first payload ──
        sample_col_values = _native_column_values(payloads[0], specs)
        field_columns = list(sample_col_values.keys())
        data_columns = ['"id"', *[_q(c) for c in field_columns]]
        data_update = ", ".join(f"{_q(c)}=excluded.{_q(c)}" for c in field_columns)

        # detect blob_union type columns
        blob_union_specs = [s for s in (specs or {}).values() if s.kind == "blob_union"]
        sys_columns = ['"id"', "expire_at", '"size"', "accessed_at"]
        sys_update = 'expire_at=excluded.expire_at, "size"=excluded."size", accessed_at=excluded.accessed_at'
        for bu_spec in blob_union_specs:
            type_col = f"{bu_spec.column_name}_type"
            sys_columns.append(_q(type_col))
            sys_update += f", {_q(type_col)}=excluded.{_q(type_col)}"

        data_rows: list[tuple[object, ...]] = []
        sys_rows: list[tuple[object, ...]] = []
        object_ids: list[str] = []
        for payload in payloads:
            object_id = str(payload.get("id") or payload.get("_id"))
            object_ids.append(object_id)
            col_values = _native_column_values(payload, specs)
            db_payload = remap_payload_to_db(payload, field_name_map)
            size = len(_json_dumps_bytes(db_payload))
            data_rows.append((object_id, *col_values.values()))
            sys_row: list[object] = [object_id, expire_at, size, ts]
            for bu_spec in blob_union_specs:
                raw = payload.get(bu_spec.field_name)
                sys_row.append(type(raw).Type if raw is not None and hasattr(type(raw), "Type") else None)
            sys_rows.append(tuple(sys_row))

        conn = await self._get_conn()
        data_sql = (
            f"INSERT INTO {self._table_sql(collection_name)}({', '.join(data_columns)})"
            f" VALUES ({', '.join(['?'] * len(data_columns))})"
        )
        if data_update:
            data_sql += f' ON CONFLICT("id") DO UPDATE SET {data_update}'
        else:
            data_sql += ' ON CONFLICT("id") DO NOTHING'
        await conn.executemany(data_sql, data_rows)
        await conn.executemany(
            f"INSERT INTO {self._sys_table_sql(collection_name)}({', '.join(sys_columns)})"
            f" VALUES ({', '.join(['?'] * len(sys_columns))})"
            f' ON CONFLICT("id") DO UPDATE SET {sys_update}',
            sys_rows,
        )

        # ── sync FTS5 index (batch) ──
        fts_cols = self._get_fts_columns(collection_name)
        if fts_cols:
            fts_table = self._fts_table_sql(collection_name)
            fts_col_list = ", ".join(["rowid"] + [_q(c) for c in fts_cols] + ["_doc_id"])
            fts_ph = ", ".join(["?"] * (len(fts_cols) + 2))
            fts_del_rows = [(_fts_rowid(oid),) for oid in object_ids]
            fts_ins_rows: list[tuple[object, ...]] = []
            for oid, payload in zip(object_ids, payloads):
                cv = _native_column_values(payload, specs)
                vals = tuple(str(cv.get(c) or "") for c in fts_cols)
                fts_ins_rows.append((_fts_rowid(oid), *vals, oid))
            await conn.executemany(f"DELETE FROM {fts_table} WHERE rowid = ?", fts_del_rows)
            await conn.executemany(f"INSERT OR REPLACE INTO {fts_table}({fts_col_list}) VALUES ({fts_ph})", fts_ins_rows)

        await conn.commit()
        self._pending_writes = 0
        if self._should_cleanup():
            asyncio.create_task(self._background_cleanup())
        return object_ids

    @overload
    def search_sorted(
        self,
        collection: type[ModelT],
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[True] = True,
    ) -> AsyncGenerator[ModelT, None]: ...

    @overload
    def search_sorted(
        self,
        collection: type[ModelT],
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[False],
    ) -> AsyncGenerator[ORMPayload, None]: ...

    @overload
    def search_sorted(
        self,
        collection: str,
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[True] = True,
    ) -> AsyncGenerator[ORMModel, None]: ...

    @overload
    def search_sorted(
        self,
        collection: str,
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: Literal[False],
    ) -> AsyncGenerator[ORMPayload, None]: ...

    async def search_sorted(
        self,
        collection: CollectionLike[ModelT],
        query: "QueryLike" = None,
        *,
        sort: Sequence[tuple[str, str]],
        limit: int | None = None,
        offset: int = 0,
        as_model: bool = True,
    ) -> AsyncGenerator[HydratedORMDocument, None]:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return

        native_fields = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)
        fts_cols = self._get_fts_columns(collection_name)
        fts_table_q = self._fts_table_sql(collection_name) if fts_cols else None
        fts_col_set = set(fts_cols) if fts_cols else None
        q_result = _query_to_sql_conditions(
            query, "sqlite", native_fields=native_field_names(native_fields),
            field_name_map=fnmap, fts_table=fts_table_q, fts_columns=fts_col_set,
        )
        if q_result is None:
            raise ValueError("SQLite sorted search requires a query that can be pushed down to SQL.")

        sort_clauses = _build_sql_sort_clauses(sort, dialect="sqlite", native_fields=native_fields, field_name_map=fnmap)
        if not sort_clauses:
            async for item in self.search(collection, query, limit=limit, offset=offset, as_model=as_model):
                yield item
            return

        conditions, params = q_result
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        params = {"_now": _now_ts(), **params}
        where_clause = "WHERE (s.expire_at IS NULL OR s.expire_at > :_now)"
        if conditions:
            where_clause += " AND " + " AND ".join(conditions)
        query_sql = (
            f"SELECT d.*, s.expire_at, s.accessed_at AS _sys_accessed_at"
            f" FROM {table} d LEFT JOIN {sys_table} s ON d.\"id\" = s.\"id\""
            f" {where_clause} ORDER BY {', '.join(sort_clauses)}"
        )
        if limit is not None:
            query_sql += " LIMIT :_limit"
            params["_limit"] = int(limit)
        if offset > 0:
            query_sql += " OFFSET :_offset"
            params["_offset"] = int(offset)

        conn = await self._get_conn()
        cursor = await conn.execute(query_sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            payload = _deserialize_row(row, native_fields, field_name_map=fnmap)
            yield await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    @overload
    async def get(self, collection: type[ModelT], object_id: str | ObjectId, *, as_model: Literal[True] = True) -> ModelT | None: ...

    @overload
    async def get(self, collection: type[ModelT], object_id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    @overload
    async def get(self, collection: str, object_id: str | ObjectId, *, as_model: Literal[True] = True) -> ORMModel | None: ...

    @overload
    async def get(self, collection: str, object_id: str | ObjectId, *, as_model: Literal[False]) -> ORMPayload | None: ...

    async def get(self, collection: CollectionLike[ModelT], object_id: str | ObjectId, *, as_model: bool = True) -> HydratedORMDocument | None:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return None
        object_id_str = str(object_id)
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        conn = await self._get_conn()
        cursor = await conn.execute(
            f"SELECT d.*, s.expire_at, s.accessed_at"
            f" FROM {table} d LEFT JOIN {sys_table} s ON d.\"id\" = s.\"id\""
            f" WHERE d.\"id\" = ?",
            (object_id_str,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        expire_at = row["expire_at"]
        if expire_at is not None and expire_at <= _now_ts():
            await conn.execute(f'DELETE FROM {table} WHERE "id" = ?', (object_id_str,))
            await conn.execute(f'DELETE FROM {sys_table} WHERE "id" = ?', (object_id_str,))
            fts_cols = self._get_fts_columns(collection_name)
            if fts_cols:
                await conn.execute(
                    f"DELETE FROM {self._fts_table_sql(collection_name)} WHERE rowid = ?",
                    (_fts_rowid(object_id_str),),
                )
            await conn.commit()
            return None
        specs = self._get_native_field_specs(collection_name)
        payload = _deserialize_row(row, specs, field_name_map=self._get_field_name_map(collection_name))
        return await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def delete(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> bool:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return False
        object_id_str = str(object_id)
        conn = await self._get_conn()

        # cascade cleanup: fetch file_id fields before deleting
        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(s.kind == "file_id" for s in specs.values())
        if has_file_id:
            cur = await conn.execute(
                f'SELECT * FROM {self._table_sql(collection_name)} WHERE "id" = ?',
                (object_id_str,),
            )
            row = await cur.fetchone()
            await cur.close()
            if row is not None:
                payload = _deserialize_row(
                    row, specs, field_name_map=self._get_field_name_map(collection_name),
                )
                await self._cleanup_foreign_on_delete(collection_name, payload)

        cursor = await conn.execute(
            f'DELETE FROM {self._table_sql(collection_name)} WHERE "id" = ?', (object_id_str,)
        )
        await conn.execute(
            f'DELETE FROM {self._sys_table_sql(collection_name)} WHERE "id" = ?', (object_id_str,)
        )
        # remove from FTS index
        fts_cols = self._get_fts_columns(collection_name)
        if fts_cols:
            await conn.execute(
                f"DELETE FROM {self._fts_table_sql(collection_name)} WHERE rowid = ?",
                (_fts_rowid(object_id_str),),
            )
        await conn.commit()
        return cursor.rowcount > 0

    async def delete_many(self, collection: CollectionLike[ORMModel], object_ids: Sequence[str | ObjectId]) -> dict[str, bool]:
        collection_name, _ = self._normalize_collection(collection)
        ids = [str(object_id or "").strip() for object_id in object_ids]
        ids = [object_id for object_id in ids if object_id]
        if not ids:
            return {}
        if not await self._async_collection_exists(collection_name):
            return {object_id: False for object_id in ids}

        specs = self._get_native_field_specs(collection_name)
        has_file_id = bool(specs and any(spec.kind == "file_id" for spec in specs.values()))
        if has_file_id:
            return await super().delete_many(collection, ids)

        conn = await self._get_conn()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        fts_table = self._fts_table_sql(collection_name)
        has_fts = bool(self._get_fts_columns(collection_name))

        existing_ids: set[str] = set()

        def _placeholders(batch: Sequence[object]) -> str:
            return ", ".join("?" for _ in batch)

        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            cursor = await conn.execute(
                f'SELECT "id" FROM {table} WHERE "id" IN ({_placeholders(batch)})',
                tuple(batch),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for row in rows:
                if row and row[0] is not None:
                    existing_ids.add(str(row[0]))

        if not existing_ids:
            return {object_id: False for object_id in ids}

        existing_list = [object_id for object_id in ids if object_id in existing_ids]
        for start in range(0, len(existing_list), 500):
            batch = existing_list[start:start + 500]
            params = tuple(batch)
            placeholders = _placeholders(batch)
            await conn.execute(
                f'DELETE FROM {table} WHERE "id" IN ({placeholders})',
                params,
            )
            await conn.execute(
                f'DELETE FROM {sys_table} WHERE "id" IN ({placeholders})',
                params,
            )
            if has_fts:
                rowids = tuple(_fts_rowid(object_id) for object_id in batch)
                await conn.execute(
                    f'DELETE FROM {fts_table} WHERE rowid IN ({_placeholders(rowids)})',
                    rowids,
                )
        await conn.commit()
        return {object_id: object_id in existing_ids for object_id in ids}

    async def set_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId, expire: float | int | None) -> bool:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return False
        object_id_str = str(object_id)
        expire_at = _normalize_expire_at(expire)
        await self.flush()
        conn = await self._get_conn()
        cursor = await conn.execute(
            f'UPDATE {self._sys_table_sql(collection_name)} SET expire_at = ? WHERE "id" = ?',
            (expire_at, object_id_str),
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def get_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> float | None:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return None
        object_id_str = str(object_id)
        conn = await self._get_conn()
        cursor = await conn.execute(
            f'SELECT expire_at FROM {self._sys_table_sql(collection_name)} WHERE "id" = ?', (object_id_str,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        ttl = _ttl_from_expire_at(row[0])
        if ttl == 0.0:
            await self.delete(collection_name, object_id_str)
        return ttl

    async def collection_count(self, collection: str) -> int:
        if not await self._async_collection_exists(collection):
            return 0
        conn = await self._get_conn()
        cursor = await conn.execute(
            f"SELECT COUNT(*) FROM {self._sys_table_sql(collection)} WHERE expire_at IS NULL OR expire_at > ?",
            (_now_ts(),),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0] if row else 0)

    async def query_count(self, collection: CollectionLike[ORMModel], query: "QueryLike" = None) -> int:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return 0
        native_fields = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        fts_cols = self._get_fts_columns(collection_name)
        fts_table_q = self._fts_table_sql(collection_name) if fts_cols else None
        fts_col_set = set(fts_cols) if fts_cols else None
        q_result = _query_to_sql_conditions(
            query, "sqlite", native_fields=native_field_names(native_fields),
            field_name_map=fnmap, fts_table=fts_table_q, fts_columns=fts_col_set,
        )
        if q_result is None:
            raise ValueError("SQLite query_count only supports pushdown-compatible filters.")
        conditions, params = q_result
        params = {"_now": _now_ts(), **params}
        where_clause = "WHERE (s.expire_at IS NULL OR s.expire_at > :_now)"
        if conditions:
            where_clause += " AND " + " AND ".join(conditions)
        conn = await self._get_conn()
        cursor = await conn.execute(
            f'SELECT COUNT(*) FROM {table} d LEFT JOIN {sys_table} s ON d."id" = s."id" {where_clause}',
            params,
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0] if row else 0)

    async def _background_cleanup(self) -> None:
        """Fire-and-forget wrapper around :meth:`cleanup`."""
        try:
            await self.cleanup()
        except Exception:
            pass  # background task — errors are non-critical

    async def cleanup(self, *, force: bool = False) -> int:
        if not self._should_cleanup(force=force):
            return 0
        await self.flush()
        removed = 0
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT collection_name FROM _orm_collections")
        collection_rows = await cursor.fetchall()
        await cursor.close()

        now = _now_ts()
        total_size = 0
        live_rows: list[tuple[str, str, int, float]] = []
        for c_row in collection_rows:
            collection = c_row[0]
            table = self._table_sql(collection)
            sys_table = self._sys_table_sql(collection)
            # delete expired: remove from sys first, then matching data rows
            exp_cur = await conn.execute(
                f'SELECT "id" FROM {sys_table} WHERE expire_at IS NOT NULL AND expire_at <= ?', (now,)
            )
            expired_rows = await exp_cur.fetchall()
            await exp_cur.close()
            if expired_rows:
                expired_ids = [str(r[0]) for r in expired_rows]
                ph = ", ".join(["?"] * len(expired_ids))
                await conn.execute(f'DELETE FROM {table} WHERE "id" IN ({ph})', expired_ids)
                await conn.execute(f'DELETE FROM {sys_table} WHERE "id" IN ({ph})', expired_ids)
                # remove expired entries from FTS
                fts_cols = self._get_fts_columns(collection)
                if fts_cols:
                    fts_table = self._fts_table_sql(collection)
                    fts_del = [(_fts_rowid(eid),) for eid in expired_ids]
                    await conn.executemany(f"DELETE FROM {fts_table} WHERE rowid = ?", fts_del)
                removed += len(expired_ids)
            # gather live row sizes for LRU
            if self._max_size is not None:
                size_cur = await conn.execute(f'SELECT "id", "size", accessed_at FROM {sys_table}')
                size_rows = await size_cur.fetchall()
                await size_cur.close()
                for row in size_rows:
                    total_size += int(row[1])
                    live_rows.append((collection, str(row[0]), int(row[1]), float(row[2])))

        total_count = len(live_rows)
        if self._max_size is not None and len(live_rows) > self._max_size:
            target = max(0, int(self._max_size * 0.9))
            for collection, object_id, size, _ in sorted(live_rows, key=lambda item: item[3]):
                if total_count <= target:
                    break
                del_cur = await conn.execute(
                    f'DELETE FROM {self._table_sql(collection)} WHERE "id" = ?', (object_id,)
                )
                if del_cur.rowcount:
                    await conn.execute(
                        f'DELETE FROM {self._sys_table_sql(collection)} WHERE "id" = ?', (object_id,)
                    )
                    # also remove from FTS
                    fts_cols = self._get_fts_columns(collection)
                    if fts_cols:
                        await conn.execute(
                            f"DELETE FROM {self._fts_table_sql(collection)} WHERE rowid = ?",
                            (_fts_rowid(object_id),),
                        )
                    total_count -= 1
                    removed += 1

        await conn.commit()
        self._mark_cleanup()
        return removed



__all__ = ['SQLiteORMClient']
