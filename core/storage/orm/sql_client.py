import asyncio
import threading

from datetime import date, datetime
from typing import AsyncGenerator, Iterable, Literal, Mapping, Self, Sequence, TYPE_CHECKING, cast, overload
from typing_extensions import Unpack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection as _AsyncConnection, AsyncEngine as _AsyncEngine
    from sqlalchemy import TextClause

from .field_schema import (
    ORMFieldSpec,
    detect_column_renames,
    native_field_names,
    sql_column_type,
)
from .field_metadata import remap_payload_to_db
from ..base import (
    _default_local_storage_root,
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
from .query import _ParamCounter
from .client_base import (
    HydratedORMDocument,
    ORMPayload,
    ORMPayloadLike,
    ORM_ClientBase,
    SQLORMClientInitParams,
    _get_schema_lock,
    _q,
    _native_column_values,
    _deserialize_row,
    _build_sql_sort_clauses,
    _query_to_sql_conditions,
    _require_sql_query_conditions,
    _sqlite_regexp,
    _normalize_raw_orm_payload,
    _raw_schema_from_specs,
    _safe_model_schema,
    _normalize_selected_fields,
    _project_selected_pairs,
    _build_sql_selected_columns,
    _orm_logger,
)


def _raw_kind_from_declared_sql_type(declared_type: str | None) -> str:
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


def _schema_from_existing_sql_columns(collection: str, columns: Mapping[str, tuple[str, int | None]]) -> dict[str, object] | None:
    specs: dict[str, ORMFieldSpec] = {}
    for column_name, (declared_type, max_length) in columns.items():
        field_name = str(column_name or "").strip()
        if not field_name or field_name == "id" or field_name.startswith("_"):
            continue
        kind = _raw_kind_from_declared_sql_type(declared_type)
        specs[field_name] = ORMFieldSpec(
            field_name=field_name,
            column_name=field_name,
            kind=kind,
            nullable=True,
            index=None,
            max_length=max_length if kind == "str" else None,
        )
    return _raw_schema_from_specs(collection, specs) if specs else None


def _coerce_sql_native_value(value: object, kind: str) -> object:
    if value is None:
        return None
    if kind == "datetime":
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            try:
                return datetime.fromisoformat(text)
            except Exception:
                return value
    if kind == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            text = value.strip()
            try:
                return date.fromisoformat(text)
            except Exception:
                try:
                    return datetime.fromisoformat(text).date()
                except Exception:
                    return value
    return value


def _normalize_sql_column_values(
    values: Mapping[str, object],
    specs: Mapping[str, object] | None,
) -> dict[str, object]:
    if not specs:
        return dict(values)
    normalized = dict(values)
    for spec in specs.values():
        kind = getattr(spec, "kind", None)
        column_name = getattr(spec, "column_name", None)
        if kind not in {"date", "datetime"} or not isinstance(column_name, str) or column_name not in normalized:
            continue
        normalized[column_name] = _coerce_sql_native_value(normalized[column_name], str(kind))
    return normalized

class SQL_ORM_Client(ORM_ClientBase, type="sql"):
    def __init__(self, **kwargs: Unpack[SQLORMClientInitParams]) -> None:
        raw_url = kwargs.get("url", f"sqlite:///{(_default_local_storage_root('orm') / 'orm_sqlalchemy.sqlite3').as_posix()}")
        self._url = self._adapt_async_url(raw_url)
        self._engine: "_AsyncEngine | None" = None
        self._schema_ready: bool = False
        self._cleanup_async_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        super().__init__(**kwargs)
        
    def _sql_text(self, text: str) -> "TextClause":
        from sqlalchemy import text as _text_fn  # lazy import
        return _text_fn(text)

    @staticmethod
    def _adapt_async_url(url: str) -> str:
        """Convert sync SQLAlchemy URLs to their async driver equivalents."""
        if url.startswith("sqlite:///") and "+aiosqlite" not in url:
            return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
        if url.startswith("sqlite://") and "+aiosqlite" not in url:
            return "sqlite+aiosqlite://" + url[len("sqlite://"):]
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://"):]
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            return "postgresql+asyncpg://" + url[len("postgresql://"):]
        if url.startswith("postgresql+psycopg://"):
            return "postgresql+asyncpg://" + url[len("postgresql+psycopg://"):]
        if url.startswith("mysql://") and "+aiomysql" not in url:
            return "mysql+aiomysql://" + url[len("mysql://"):]
        return url

    def _require_engine(self) -> "_AsyncEngine":
        engine = self._engine
        if engine is None:
            raise RuntimeError("SQL_ORM_Client engine is not started.")
        return engine

    @staticmethod
    def _row_mapping_dict(mapping: object) -> dict[str, object]:
        if isinstance(mapping, Mapping):
            items = mapping.items()
        else:
            items_fn = getattr(mapping, "items", None)
            if not callable(items_fn):
                raise TypeError(f"Unsupported SQL row mapping type: {type(mapping).__name__}")
            items = cast(Iterable[tuple[object, object]], items_fn())
        return {str(key): value for key, value in items}

    def start(self) -> Self:
        if self._started:
            return self
        from sqlalchemy.ext.asyncio import create_async_engine  # lazy import
        from sqlalchemy import event
        engine = create_async_engine(self._url, future=True)
        self._engine = engine
        if engine.dialect.name == "sqlite":
            @event.listens_for(self._engine.sync_engine, "connect")
            def _register_sqlite_regexp(dbapi_connection: object, _connection_record: object) -> None:
                try:
                    if hasattr(dbapi_connection, "create_function"):
                        dbapi_connection.create_function("regexp", 2, _sqlite_regexp)   # type: ignore[attr-defined]
                except Exception:
                    pass
        self._mark_started()
        return self

    async def _ensure_schema_ready(self) -> "_AsyncEngine":
        if self._schema_ready:
            return self._require_engine()
        if not self._started:
            self.start()
        engine = self._require_engine()
        async with engine.begin() as conn:
            await conn.execute(self._sql_text(
                """
                CREATE TABLE IF NOT EXISTS _orm_collections (
                    collection_name VARCHAR(255) PRIMARY KEY,
                    model_module TEXT,
                    model_name TEXT,
                    schema_json TEXT
                )
                """
            ))
            # Migration: drop legacy created_at column
            for _legacy_col in ("created_at",):
                try:
                    await conn.execute(self._sql_text(f"ALTER TABLE _orm_collections DROP COLUMN IF EXISTS {_legacy_col}"))
                except Exception:
                    pass
        self._schema_ready = True
        return engine

    async def aclose(self) -> None:
        cleanup_task = self._cleanup_task
        self._cleanup_task = None
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
        engine = self._engine
        self._engine = None
        self._schema_ready = False
        self._cleanup_async_locks.clear()
        self._mark_stopped()
        if engine is None:
            return
        try:
            await engine.dispose()
        except Exception as e:
            _orm_logger.warning("SQLORMClient.aclose() failed for %s: %s", self._url, e)

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
            _orm_logger.warning("SQLORMClient.close() failed for %s: %s", self._url, e)

    def _cleanup_async_lock(self) -> asyncio.Lock:
        owner = (threading.get_ident(), id(asyncio.get_running_loop()))
        lock = self._cleanup_async_locks.get(owner)
        if lock is None:
            lock = asyncio.Lock()
            self._cleanup_async_locks[owner] = lock
        return lock

    def _schedule_cleanup(self) -> None:
        if not self._should_cleanup():
            return
        task = self._cleanup_task
        if task is not None and not task.done():
            return
        self._cleanup_task = asyncio.create_task(self._background_cleanup())

    def _table_sql(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f"orm_{collection}"

    def _sys_table_sql(self, collection: str) -> str:
        _validate_collection_name(collection)
        return f"_orm_{collection}_sys"

    async def _fetch_existing_columns(self, conn: "_AsyncConnection", collection: str, *, table_override: str | None = None) -> dict[str, tuple[str, int | None]]:
        table = table_override or self._table_sql(collection)
        dialect = str(self._require_engine().dialect.name).lower()
        if dialect == "sqlite":
            result = await conn.execute(self._sql_text(f"PRAGMA table_info({table})"))
            rows = result.fetchall()
            return {str(row[1]): (str(row[2] or ""), None) for row in rows}
        if dialect == "postgresql":
            result = await conn.execute(
                self._sql_text(
                    """
                    SELECT column_name, data_type, character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = :table
                    """
                ),
                {"table": table},
            )
            return {
                str(row[0]): (str(row[1] or ""), int(row[2]) if row[2] is not None else None)
                for row in result.fetchall()
            }
        if dialect in {"mysql", "mariadb"}:
            result = await conn.execute(
                self._sql_text(
                    """
                    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table
                    """
                ),
                {"table": table},
            )
            return {
                str(row[0]): (str(row[1] or ""), int(row[2]) if row[2] is not None else None)
                for row in result.fetchall()
            }
        return {}

    async def _fetch_existing_index_names(self, conn: "_AsyncConnection", collection: str) -> set[str]:
        table = self._table_sql(collection)
        dialect = str(self._require_engine().dialect.name).lower()
        if dialect == "sqlite":
            result = await conn.execute(self._sql_text(f"PRAGMA index_list({table})"))
            return {str(row[1]) for row in result.fetchall()}
        if dialect == "postgresql":
            result = await conn.execute(
                self._sql_text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = :table"
                ),
                {"table": table},
            )
            return {str(row[0]) for row in result.fetchall()}
        if dialect in {"mysql", "mariadb"}:
            result = await conn.execute(
                self._sql_text(
                    "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
                ),
                {"table": table},
            )
            return {str(row[0]) for row in result.fetchall()}
        return set()

    async def _ensure_field_schema(self, conn: "_AsyncConnection", collection: str) -> None:
        specs = self._get_native_field_specs(collection)
        if not specs:
            return

        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        dialect = str(self._require_engine().dialect.name).lower()
        existing_columns = await self._fetch_existing_columns(conn, collection)
        existing_indexes = await self._fetch_existing_index_names(conn, collection)

        # ── detect renames before adding missing columns ──
        existing_types_flat = {col: str(t or "") for col, (t, _) in existing_columns.items()}
        renames = detect_column_renames(existing_types_flat, specs, dialect)
        for old_col, spec in renames:
            try:
                await conn.execute(
                    self._sql_text(f"ALTER TABLE {table} RENAME COLUMN {_q(old_col, dialect)} TO {_q(spec.column_name, dialect)}")
                )
                _orm_logger.info(
                    "%s field `%s`: renamed column %s → %s",
                    dialect, collection, old_col, spec.column_name,
                )
                existing_columns[spec.column_name] = existing_columns.pop(old_col)
                # drop old index if present
                old_idx = f"idx_{collection}_{old_col}"
                if old_idx in existing_indexes:
                    try:
                        await conn.execute(self._sql_text(f"DROP INDEX IF EXISTS {old_idx}"))
                    except Exception:
                        pass
            except Exception as exc:
                _orm_logger.warning(
                    "%s field `%s`: column rename %s → %s failed: %s",
                    dialect, collection, old_col, spec.column_name, exc,
                )

        # ── Pass 1: add missing columns and widen types ──
        for spec in specs.values():
            desired_type = sql_column_type(spec, dialect)
            current = existing_columns.get(spec.column_name)
            if current is None:
                try:
                    await conn.execute(
                        self._sql_text(f"ALTER TABLE {table} ADD COLUMN {_q(spec.column_name, dialect)} {desired_type}")
                    )
                except Exception as exc:
                    if not _is_duplicate_column_error(exc, dialect):
                        raise
            else:
                current_type, current_length = current
                current_type_upper = str(current_type or "").upper()
                if spec.kind == "str" and spec.max_length and current_length:
                    if spec.max_length > int(current_length):
                        try:
                            if dialect == "postgresql":
                                await conn.execute(
                                    self._sql_text(
                                        f"ALTER TABLE {table} ALTER COLUMN {_q(spec.column_name, dialect)} TYPE VARCHAR({int(spec.max_length)})"
                                    )
                                )
                            elif dialect in {"mysql", "mariadb"}:
                                await conn.execute(
                                    self._sql_text(
                                        f"ALTER TABLE {table} MODIFY COLUMN {_q(spec.column_name, dialect)} VARCHAR({int(spec.max_length)}) NULL"
                                    )
                                )
                        except Exception as exc:
                            _orm_logger.warning(
                                "Failed to widen %s.%s to VARCHAR(%s): %s",
                                collection, spec.field_name, spec.max_length, exc,
                            )
                    elif spec.max_length < int(current_length):
                        _orm_logger.warning(
                            "Field `%s.%s` max_length shrank from %s to %s; keeping database schema unchanged.",
                            collection, spec.field_name, current_length, spec.max_length,
                        )
                elif current_type_upper and desired_type.upper() not in current_type_upper and current_type_upper not in desired_type.upper():
                    _orm_logger.warning(
                        "Field `%s.%s` type differs (db=%s, code=%s); keeping database schema unchanged.",
                        collection, spec.field_name, current_type, desired_type,
                    )

            # blob_union → sys table needs {col}_type column
            if spec.kind == "blob_union":
                type_col = f"{spec.column_name}_type"
                sys_cols = await self._fetch_existing_columns(conn, collection, table_override=sys_table)
                if type_col not in sys_cols:
                    col_type = "TEXT" if dialect != "mysql" else "VARCHAR(64)"
                    try:
                        await conn.execute(
                            self._sql_text(f"ALTER TABLE {sys_table} ADD COLUMN {_q(type_col, dialect)} {col_type}")
                        )
                    except Exception as exc:
                        if not _is_duplicate_column_error(exc, dialect):
                            raise

        # ── Pass 2: reconcile indexes (all columns guaranteed to exist) ──
        for spec in specs.values():
            index_name = f"idx_{collection}_{spec.column_name}"
            if spec.index is True:
                try:
                    if dialect in {"mysql", "mariadb"}:
                        await conn.execute(self._sql_text(f"CREATE INDEX {index_name} ON {table} ({_q(spec.column_name, dialect)})"))
                    else:
                        await conn.execute(self._sql_text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({_q(spec.column_name, dialect)})"))
                except Exception as exc:
                    if dialect not in {"mysql", "mariadb"} or "1061" not in str(exc):
                        raise
            elif spec.index is False and index_name in existing_indexes:
                try:
                    await conn.execute(self._sql_text(f"DROP INDEX IF EXISTS {index_name}"))
                    _orm_logger.info(
                        "%s field `%s.%s`: dropped index `%s` (index=False).",
                        dialect, collection, spec.field_name, index_name,
                    )
                except Exception as exc:
                    _orm_logger.warning(
                        "%s field `%s.%s`: failed to drop index `%s`: %s",
                        dialect, collection, spec.field_name, index_name, exc,
                    )

    def _collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        try:
            from sqlalchemy import inspect as sa_inspect

            if not self._started:
                self.start()
            engine = self._require_engine()
            exists = bool(sa_inspect(engine.sync_engine).has_table(self._table_sql(collection)))
        except Exception:
            return False
        if exists:
            self._mark_collection_known(collection)
        return exists

    async def _async_collection_exists(self, collection: str) -> bool:
        if collection in self._known_collections:
            return True
        engine = await self._ensure_schema_ready()
        async with engine.connect() as conn:
            result = await conn.execute(
                self._sql_text("SELECT 1 FROM _orm_collections WHERE collection_name = :c LIMIT 1"),
                {"c": collection},
            )
            row = result.fetchone()
        if row is not None:
            self._mark_collection_known(collection)
            return True
        try:
            from sqlalchemy import inspect as sa_inspect

            async with engine.connect() as inspect_conn:
                exists = bool(
                    await inspect_conn.run_sync(
                        lambda sync_conn: sa_inspect(sync_conn).has_table(self._table_sql(collection))
                    )
                )
        except Exception:
            return False
        if exists:
            self._mark_collection_known(collection)
        return exists

    async def _load_stored_schema(self, collection: str) -> dict[str, object] | None:
        try:
            engine = await self._ensure_schema_ready()
            async with engine.connect() as conn:
                result = await conn.execute(
                    self._sql_text("SELECT schema_json FROM _orm_collections WHERE collection_name = :c LIMIT 1"),
                    {"c": collection},
                )
                row = result.fetchone()
        except Exception:
            return None
        if row is None:
            try:
                async with engine.connect() as schema_conn:
                    existing_columns = await self._fetch_existing_columns(schema_conn, collection)
            except Exception:
                return None
            return _schema_from_existing_sql_columns(collection, existing_columns)
        raw = row[0]
        if not raw:
            try:
                async with engine.connect() as schema_conn:
                    existing_columns = await self._fetch_existing_columns(schema_conn, collection)
            except Exception:
                return None
            return _schema_from_existing_sql_columns(collection, existing_columns)
        if isinstance(raw, dict):
            return raw
        try:
            return _json_loads(raw)
        except Exception:
            try:
                async with engine.connect() as schema_conn:
                    existing_columns = await self._fetch_existing_columns(schema_conn, collection)
            except Exception:
                return None
            return _schema_from_existing_sql_columns(collection, existing_columns)

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        engine = await self._ensure_schema_ready()
        self.register_model(model_cls)
        collection = model_cls.CollectionName
        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        dialect = str(engine.dialect.name).lower()
        new_schema = _safe_model_schema(model_cls)
        specs = self._get_native_field_specs(collection)

        # Build column definitions from field specs
        col_defs: list[str] = [f"{_q('id', dialect)} TEXT PRIMARY KEY"]
        for spec in (specs or {}).values():
            col_defs.append(f"{_q(spec.column_name, dialect)} {sql_column_type(spec, dialect)}")

        with _get_schema_lock(collection):
            async with engine.begin() as conn:
                # ── data table ──
                await conn.execute(self._sql_text(
                    f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)})"
                ))
                # ── sys table ──
                sys_col_defs = [
                    f"{_q('id', dialect)} TEXT PRIMARY KEY",
                    "expire_at REAL",
                    f"{_q('size', dialect)} INTEGER NOT NULL",
                    "accessed_at REAL NOT NULL",
                ]
                # blob_union → {col}_type column in sys table
                for spec in (specs or {}).values():
                    if spec.kind == "blob_union":
                        type_col = f"{spec.column_name}_type"
                        sys_col_defs.append(f"{_q(type_col, dialect)} TEXT")
                await conn.execute(self._sql_text(
                    f"CREATE TABLE IF NOT EXISTS {sys_table} ({', '.join(sys_col_defs)})"
                ))
                # Migration: drop legacy created_at/updated_at from sys table
                for _legacy_col in ("created_at", "updated_at"):
                    try:
                        await conn.execute(self._sql_text(f"ALTER TABLE {sys_table} DROP COLUMN IF EXISTS {_legacy_col}"))
                    except Exception:
                        pass
                # ── collection registry ──
                await conn.execute(self._sql_text(
                    """
                    INSERT INTO _orm_collections(collection_name, model_module, model_name, schema_json)
                    VALUES (:collection_name, :model_module, :model_name, :schema_json)
                    ON CONFLICT(collection_name) DO UPDATE SET
                        model_module=:model_module,
                        model_name=:model_name,
                        schema_json=:schema_json
                    """
                ), {
                    "collection_name": collection,
                    "model_module": model_cls.__module__,
                    "model_name": model_cls.__name__,
                    "schema_json": _json_dumps(new_schema),
                })
                # ── sys table indexes ──
                await conn.execute(self._sql_text(
                    f'CREATE INDEX IF NOT EXISTS "idx_{collection}_sys_expire" ON {sys_table} (expire_at)'
                ))
                await conn.execute(self._sql_text(
                    f'CREATE INDEX IF NOT EXISTS "idx_{collection}_sys_access" ON {sys_table} (accessed_at)'
                ))
                # ── schema evolution (adds missing columns + their indexes) ──
                await self._ensure_field_schema(conn, collection)
        self._mark_collection_known(collection)
        self._bootstrapped_collections.add(collection)

    async def _ensure_schemaless_collection(
        self,
        collection_name: str,
        payload: Mapping[str, object],
        *,
        schema: Mapping[str, object] | None = None,
    ) -> None:
        engine = await self._ensure_schema_ready()
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        specs = await self._ensure_raw_specs(collection_name, schema=schema, payload=payload)
        schema_json = _raw_schema_from_specs(collection_name, specs) if specs else (dict(schema) if schema is not None else None)

        with _get_schema_lock(collection_name):
            async with engine.begin() as conn:
                model_module = None
                model_name = None
                model_cls = self._resolve_collection_model(collection_name)
                if model_cls is not None:
                    self.register_model(model_cls)
                    model_module = model_cls.__module__
                    model_name = model_cls.__name__
                else:
                    existing_result = await conn.execute(
                        self._sql_text(
                            f"SELECT {_q('model_module', dialect)}, {_q('model_name', dialect)} "
                            f"FROM _orm_collections WHERE {_q('collection_name', dialect)} = :collection_name"
                        ),
                        {"collection_name": collection_name},
                    )
                    existing_row = existing_result.fetchone()
                    if existing_row is not None:
                        existing_mapping = getattr(existing_row, "_mapping", None)
                        if isinstance(existing_mapping, Mapping):
                            raw_model_module = existing_mapping.get("model_module")
                            raw_model_name = existing_mapping.get("model_name")
                            model_module = str(raw_model_module) if raw_model_module is not None else None
                            model_name = str(raw_model_name) if raw_model_name is not None else None
                        else:
                            try:
                                model_module = existing_row[0]
                                model_name = existing_row[1]
                            except Exception:
                                model_module = None
                                model_name = None
                id_column_type = "VARCHAR(255)" if dialect in {"mysql", "mariadb"} else "TEXT"
                col_defs: list[str] = [f"{_q('id', dialect)} {id_column_type} PRIMARY KEY"]
                for spec in specs.values():
                    col_defs.append(f"{_q(spec.column_name, dialect)} {sql_column_type(spec, dialect)}")
                await conn.execute(self._sql_text(
                    f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)})"
                ))
                await conn.execute(self._sql_text(
                    f"CREATE TABLE IF NOT EXISTS {sys_table} ("
                    f"{_q('id', dialect)} {id_column_type} PRIMARY KEY, "
                    f"expire_at REAL, "
                    f"{_q('size', dialect)} INTEGER NOT NULL, "
                    f"accessed_at REAL NOT NULL)"
                ))
                meta_columns = [
                    _q("collection_name", dialect),
                    _q("model_module", dialect),
                    _q("model_name", dialect),
                    _q("schema_json", dialect),
                ]
                meta_placeholders = [":collection_name", ":model_module", ":model_name", ":schema_json"]
                meta_update = [_q("model_module", dialect), _q("model_name", dialect), _q("schema_json", dialect)]
                await conn.execute(
                    self._sql_text(
                        self._upsert_sql(
                            "_orm_collections",
                            columns=meta_columns,
                            placeholders=meta_placeholders,
                            update_columns=meta_update,
                            pk=_q("collection_name", dialect),
                        )
                    ),
                    {
                        "collection_name": collection_name,
                        "model_module": model_module,
                        "model_name": model_name,
                        "schema_json": _json_dumps(schema_json) if schema_json is not None else None,
                    },
                )
                for index_name, column_name in (
                    (f"idx_{collection_name}_sys_expire", "expire_at"),
                    (f"idx_{collection_name}_sys_access", "accessed_at"),
                ):
                    if dialect in {"mysql", "mariadb"}:
                        statement = f"CREATE INDEX {index_name} ON {sys_table} ({column_name})"
                    else:
                        statement = f'CREATE INDEX IF NOT EXISTS "{index_name}" ON {sys_table} ({column_name})'
                    try:
                        await conn.execute(self._sql_text(statement))
                    except Exception as exc:
                        if dialect not in {"mysql", "mariadb"} or "1061" not in str(exc):
                            raise
                await self._ensure_field_schema(conn, collection_name)
        self._mark_collection_known(collection_name)
        self._bootstrapped_collections.add(collection_name)

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
        engine = await self._ensure_schema_ready()
        collection_name = _validate_collection_name(collection)
        normalized_payload = _normalize_raw_orm_payload(payload)
        if not create_collection and not await self._async_collection_exists(collection_name):
            raise ValueError(f"Collection `{collection_name}` does not exist.")
        await self._ensure_schemaless_collection(collection_name, normalized_payload)

        object_id = str(normalized_payload.get("id") or normalized_payload.get("_id"))
        specs = self._get_native_field_specs(collection_name)
        column_values = _normalize_sql_column_values(_native_column_values(normalized_payload, specs), specs)
        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)

        data_columns = [_q("id", dialect), *[_q(c, dialect) for c in column_values.keys()]]
        data_placeholders = [":oid", *[f":d_{i}" for i in range(len(column_values))]]
        data_update = [_q(c, dialect) for c in column_values.keys()]
        data_params: dict[str, object] = {
            "oid": object_id,
            **{f"d_{i}": v for i, v in enumerate(column_values.values())},
        }

        sys_columns = [_q("id", dialect), "expire_at", _q("size", dialect), "accessed_at"]
        sys_placeholders = [":oid", ":expire_at", ":sz", ":accessed_at"]
        sys_update = ["expire_at", _q("size", dialect), "accessed_at"]
        sys_params: dict[str, object] = {
            "oid": object_id,
            "expire_at": expire_at,
            "sz": len(_json_dumps_bytes(remap_payload_to_db(normalized_payload, self._get_field_name_map(collection_name)))),
            "accessed_at": ts,
        }

        async with engine.begin() as conn:
            await conn.execute(
                self._sql_text(self._upsert_sql(table, columns=data_columns, placeholders=data_placeholders, update_columns=data_update)),
                data_params,
            )
            await conn.execute(
                self._sql_text(self._upsert_sql(sys_table, columns=sys_columns, placeholders=sys_placeholders, update_columns=sys_update)),
                sys_params,
            )

        self._schedule_cleanup()
        return object_id

    async def drop_collection(self, collection: CollectionLike[ORMModel]) -> None:
        collection, model_cls = self._normalize_collection(collection)
        engine = await self._ensure_schema_ready()
        async with engine.begin() as conn:
            await conn.execute(self._sql_text(f"DROP TABLE IF EXISTS {self._table_sql(collection)}"))
            await conn.execute(self._sql_text(f"DROP TABLE IF EXISTS {self._sys_table_sql(collection)}"))
            await conn.execute(self._sql_text("DELETE FROM _orm_collections WHERE collection_name = :c"), {"c": collection})
        self._collection_models.pop(collection, None)
        self._forget_collection(collection)
        if model_cls is not None:
            self.register_model(model_cls)

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
        engine = await self._ensure_schema_ready()
        collection, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection):
            return
        dialect = str(engine.dialect.name).lower()
        native_fields = self._get_native_field_specs(collection)
        fnmap = self._get_field_name_map(collection)
        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        counter = _ParamCounter()
        now = _now_ts()
        conditions, params = _require_sql_query_conditions(
            query,
            dialect,
            counter=counter,
            native_fields=native_field_names(native_fields),
            field_name_map=fnmap,
            operation="search",
        )
        params["_sq_now"] = now
        where_parts: list[str] = ["(s.expire_at IS NULL OR s.expire_at > :_sq_now)"]
        where_parts.extend(conditions)

        query_sql = (
            f"SELECT d.*, s.expire_at, s.accessed_at AS _sys_accessed_at"
            f" FROM {table} d LEFT JOIN {sys_table} s ON d.{_q('id', dialect)} = s.{_q('id', dialect)}"
            f" WHERE {' AND '.join(where_parts)} ORDER BY s.accessed_at DESC"
        )
        if limit is not None:
            query_sql += " LIMIT :_sq_limit"
            params["_sq_limit"] = int(limit)
        if offset > 0:
            query_sql += " OFFSET :_sq_offset"
            params["_sq_offset"] = int(offset)
        async with engine.connect() as conn:
            result = await conn.stream(self._sql_text(query_sql), params)
            async for row in result:
                payload = _deserialize_row(self._row_mapping_dict(row._mapping), native_fields, field_name_map=fnmap)
                yield await self._hydrate_with_foreign(collection, payload, as_model=as_model)

    async def selected_search(
        self,
        collection: CollectionLike[ModelT],
        *,
        fields: Sequence[str],
        query: "QueryLike" = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> AsyncGenerator[ORMPayload, None]:
        collection, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection):
            return
        normalized_fields = _normalize_selected_fields(fields)
        engine = await self._ensure_schema_ready()
        dialect = str(engine.dialect.name).lower()
        native_fields = self._get_native_field_specs(collection)
        fnmap = self._get_field_name_map(collection)
        selected_columns = _build_sql_selected_columns(normalized_fields, dialect=dialect, native_fields=native_fields, field_name_map=fnmap, table_alias="d")
        counter = _ParamCounter()
        q_conds, q_params = _require_sql_query_conditions(
            query,
            dialect,
            counter=counter,
            native_fields=native_field_names(native_fields),
            field_name_map=fnmap,
            operation="selected_search",
        )
        if selected_columns is None:
            async for item in self._selected_search_fallback(collection, fields=normalized_fields, query=query, limit=limit, offset=offset):
                yield item
            return
        columns, aliases = selected_columns
        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        now = _now_ts()
        all_conds = ["(s.expire_at IS NULL OR s.expire_at > :_sel_now)"] + q_conds
        params: dict[str, object] = {"_sel_now": now, **q_params}

        sel_expr = ", ".join(columns)
        query_sql = (
            f"SELECT {sel_expr} FROM {table} d"
            f" LEFT JOIN {sys_table} s ON d.{_q('id', dialect)} = s.{_q('id', dialect)}"
            f" WHERE {' AND '.join(all_conds)} ORDER BY s.accessed_at DESC"
        )
        if limit is not None:
            query_sql += " LIMIT :_sel_limit"
            params["_sel_limit"] = int(limit)
        if offset > 0:
            query_sql += " OFFSET :_sel_offset"
            params["_sel_offset"] = int(offset)
        async with engine.connect() as conn:
            result = await conn.stream(self._sql_text(query_sql), params)
            async for row in result:
                yield _project_selected_pairs([(field, row._mapping[alias]) for field, alias in aliases])

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

    def _upsert_sql(
        self,
        table: str,
        *,
        columns: Sequence[str],
        placeholders: Sequence[str],
        update_columns: Sequence[str],
        pk: str = '"id"',
    ) -> str:
        dialect = str(self._require_engine().dialect.name).lower()
        if dialect in {"mysql", "mariadb"}:
            update_sql = ", ".join(f"{column}=VALUES({column})" for column in update_columns)
            return (
                f"INSERT INTO {table}({', '.join(columns)}) "
                f"VALUES ({', '.join(placeholders)}) "
                f"ON DUPLICATE KEY UPDATE {update_sql}"
            )
        update_sql = ", ".join(f"{column}=excluded.{column}" for column in update_columns)
        return (
            f"INSERT INTO {table}({', '.join(columns)}) "
            f"VALUES ({', '.join(placeholders)}) "
            f"ON CONFLICT({pk}) DO UPDATE SET {update_sql}"
        )

    async def set(self, value: ORMModel | ORMPayloadLike, *, collection: CollectionLike[ORMModel] | None = None, expire: float | int | None = None, create_collection: bool = True) -> str:
        engine = await self._ensure_schema_ready()
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
        column_values = _normalize_sql_column_values(_native_column_values(payload, specs), specs)

        # ── file_id ref counting on overwrite ──
        file_id_specs = [s for s in (specs or {}).values() if s.kind == "file_id"]
        if file_id_specs:
            try:
                old = await self.get(collection_name, object_id)
                old_payload = old if isinstance(old, dict) else (old._serialize_for_storage() if old else None)
            except Exception:
                old_payload = None
            await self._handle_file_id_ref_on_overwrite(collection_name, old_payload, payload)

        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)

        # ── data table upsert ──
        data_columns = [_q("id", dialect), *[_q(c, dialect) for c in column_values.keys()]]
        data_placeholders = [":oid", *[f":d_{i}" for i in range(len(column_values))]]
        data_update = [_q(c, dialect) for c in column_values.keys()]
        data_params: dict[str, object] = {
            "oid": object_id,
            **{f"d_{i}": v for i, v in enumerate(column_values.values())},
        }

        # ── sys table upsert ──
        payload_bytes = _json_dumps_bytes(payload)
        sys_columns = [_q("id", dialect), "expire_at", _q("size", dialect), "accessed_at"]
        sys_placeholders = [":oid", ":expire_at", ":sz", ":accessed_at"]
        sys_update = ["expire_at", _q("size", dialect), "accessed_at"]
        sys_params: dict[str, object] = {
            "oid": object_id,
            "expire_at": expire_at,
            "sz": len(payload_bytes),
            "accessed_at": ts,
        }

        # blob_union → {col}_type in sys table
        for spec in (specs or {}).values():
            if spec.kind == "blob_union":
                type_col = f"{spec.column_name}_type"
                raw_val = payload.get(spec.field_name)
                type_val = type(raw_val).__name__ if raw_val is not None else None
                sys_columns.append(_q(type_col, dialect))
                sys_placeholders.append(f":bt_{spec.column_name}")
                sys_update.append(_q(type_col, dialect))
                sys_params[f"bt_{spec.column_name}"] = type_val

        async with engine.begin() as conn:
            await conn.execute(
                self._sql_text(self._upsert_sql(table, columns=data_columns, placeholders=data_placeholders, update_columns=data_update)),
                data_params,
            )
            await conn.execute(
                self._sql_text(self._upsert_sql(sys_table, columns=sys_columns, placeholders=sys_placeholders, update_columns=sys_update)),
                sys_params,
            )

        self._schedule_cleanup()
        return object_id

    async def _background_cleanup(self) -> None:
        try:
            await self.cleanup()
        except Exception:
            pass

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

        engine = await self._ensure_schema_ready()
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
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        ts = _now_ts()
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)

        # Build column templates from first payload
        sample_col_values = _normalize_sql_column_values(_native_column_values(payloads[0], specs), specs)
        native_columns = list(sample_col_values.keys())
        data_columns = [_q("id", dialect), *[_q(c, dialect) for c in native_columns]]
        data_placeholders = [":oid", *[f":d_{i}" for i in range(len(native_columns))]]
        data_update = [_q(c, dialect) for c in native_columns]

        sys_columns = [_q("id", dialect), "expire_at", _q("size", dialect), "accessed_at"]
        sys_placeholders = [":oid", ":expire_at", ":sz", ":accessed_at"]
        sys_update = ["expire_at", _q("size", dialect), "accessed_at"]

        # blob_union type columns
        blob_union_specs = [s for s in (specs or {}).values() if s.kind == "blob_union"]
        for spec in blob_union_specs:
            type_col = f"{spec.column_name}_type"
            sys_columns.append(_q(type_col, dialect))
            sys_placeholders.append(f":bt_{spec.column_name}")
            sys_update.append(_q(type_col, dialect))

        data_params_list: list[dict[str, object]] = []
        sys_params_list: list[dict[str, object]] = []
        object_ids: list[str] = []

        for payload in payloads:
            object_id = str(payload.get("id") or payload.get("_id"))
            object_ids.append(object_id)
            col_values = _normalize_sql_column_values(_native_column_values(payload, specs), specs)
            payload_bytes = _json_dumps_bytes(payload)

            data_params_list.append({
                "oid": object_id,
                **{f"d_{i}": v for i, v in enumerate(col_values.values())},
            })

            sp: dict[str, object] = {
                "oid": object_id,
                "expire_at": expire_at,
                "sz": len(payload_bytes),
                "accessed_at": ts,
            }
            for spec in blob_union_specs:
                raw_val = payload.get(spec.field_name)
                sp[f"bt_{spec.column_name}"] = type(raw_val).__name__ if raw_val is not None else None
            sys_params_list.append(sp)

        data_sql = self._upsert_sql(table, columns=data_columns, placeholders=data_placeholders, update_columns=data_update)
        sys_sql = self._upsert_sql(sys_table, columns=sys_columns, placeholders=sys_placeholders, update_columns=sys_update)

        async with engine.begin() as conn:
            await conn.execute(self._sql_text(data_sql), data_params_list)
            await conn.execute(self._sql_text(sys_sql), sys_params_list)

        self._schedule_cleanup()
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
        engine = await self._ensure_schema_ready()
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return
        dialect = str(engine.dialect.name).lower()
        native_fields = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)
        counter = _ParamCounter()
        q_result = _query_to_sql_conditions(query, dialect, counter=counter, native_fields=native_field_names(native_fields), field_name_map=fnmap)
        if q_result is None:
            raise ValueError(f"{dialect} sorted search requires a query that can be pushed down to SQL.")
        sort_clauses = _build_sql_sort_clauses(sort, dialect=dialect, native_fields=native_fields, field_name_map=fnmap)
        if not sort_clauses:
            async for item in self.search(collection, query, limit=limit, offset=offset, as_model=as_model):
                yield item
            return

        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        conditions, params = q_result
        params["_sq_now"] = _now_ts()
        where_parts: list[str] = ["(s.expire_at IS NULL OR s.expire_at > :_sq_now)"]
        where_parts.extend(conditions)

        query_sql = (
            f"SELECT d.*, s.expire_at, s.accessed_at AS _sys_accessed_at"
            f" FROM {table} d LEFT JOIN {sys_table} s ON d.{_q('id', dialect)} = s.{_q('id', dialect)}"
            f" WHERE {' AND '.join(where_parts)} ORDER BY {', '.join(sort_clauses)}"
        )
        if limit is not None:
            query_sql += " LIMIT :_sq_limit"
            params["_sq_limit"] = int(limit)
        if offset > 0:
            query_sql += " OFFSET :_sq_offset"
            params["_sq_offset"] = int(offset)
        async with engine.connect() as conn:
            result = await conn.execute(self._sql_text(query_sql), params)
            rows = result.fetchall()
        for row in rows:
            payload = _deserialize_row(self._row_mapping_dict(row._mapping), native_fields, field_name_map=fnmap)
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
        engine = await self._ensure_schema_ready()
        collection_name, _ = self._normalize_collection(collection)
        object_id_str = str(object_id)
        if not await self._async_collection_exists(collection_name):
            return None
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        native_fields = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)
        async with engine.begin() as conn:
            result = await conn.execute(self._sql_text(
                f"SELECT d.*, s.expire_at, s.accessed_at AS _sys_accessed_at"
                f" FROM {table} d LEFT JOIN {sys_table} s ON d.{_q('id', dialect)} = s.{_q('id', dialect)}"
                f" WHERE d.{_q('id', dialect)} = :oid"
            ), {"oid": object_id_str})
            row = result.fetchone()
            if row is None:
                return None
            mapping = self._row_mapping_dict(row._mapping)
            raw_expire_at = mapping.get("expire_at")
            expire_at = float(raw_expire_at) if isinstance(raw_expire_at, (int, float)) else None
            if expire_at is not None and expire_at <= _now_ts():
                await conn.execute(self._sql_text(
                    f"DELETE FROM {table} WHERE {_q('id', dialect)} = :oid"
                ), {"oid": object_id_str})
                await conn.execute(self._sql_text(
                    f"DELETE FROM {sys_table} WHERE {_q('id', dialect)} = :oid"
                ), {"oid": object_id_str})
                return None
        payload = _deserialize_row(mapping, native_fields, field_name_map=fnmap)
        return await self._hydrate_with_foreign(collection_name, payload, as_model=as_model)

    async def delete(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> bool:
        engine = await self._ensure_schema_ready()
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return False
        object_id_str = str(object_id)
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)

        # cascade cleanup: fetch file_id fields before deleting
        specs = self._get_native_field_specs(collection_name)
        has_file_id = specs and any(s.kind == "file_id" for s in specs.values())
        if has_file_id:
            async with engine.connect() as rconn:
                r = await rconn.execute(self._sql_text(
                    f"SELECT * FROM {table} WHERE {_q('id', dialect)} = :oid"
                ), {"oid": object_id_str})
                row = r.fetchone()
            if row is not None:
                payload = _deserialize_row(
                    self._row_mapping_dict(row._mapping), specs,
                    field_name_map=self._get_field_name_map(collection_name),
                )
                await self._cleanup_foreign_on_delete(collection_name, payload)

        async with engine.begin() as conn:
            result = await conn.execute(self._sql_text(
                f"DELETE FROM {table} WHERE {_q('id', dialect)} = :oid"
            ), {"oid": object_id_str})
            await conn.execute(self._sql_text(
                f"DELETE FROM {sys_table} WHERE {_q('id', dialect)} = :oid"
            ), {"oid": object_id_str})
            return result.rowcount > 0

    async def delete_many(self, collection: CollectionLike[ORMModel], object_ids: Sequence[str | ObjectId]) -> dict[str, bool]:
        engine = await self._ensure_schema_ready()
        collection_name, _ = self._normalize_collection(collection)
        ids = [str(object_id or "").strip() for object_id in object_ids]
        ids = [object_id for object_id in ids if object_id]
        if not ids:
            return {}
        if not await self._async_collection_exists(collection_name):
            return {object_id: False for object_id in ids}
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        specs = self._get_native_field_specs(collection_name)
        fnmap = self._get_field_name_map(collection_name)

        def _batch_params(batch: Sequence[str], prefix: str) -> tuple[str, dict[str, str]]:
            placeholders = ", ".join(f":{prefix}{index}" for index in range(len(batch)))
            params = {f"{prefix}{index}": object_id for index, object_id in enumerate(batch)}
            return placeholders, params

        existing_ids: set[str] = set()
        has_file_id = bool(specs and any(spec.kind == "file_id" for spec in specs.values()))
        if not has_file_id:
            deleted_count = 0
            async with engine.begin() as conn:
                for start in range(0, len(ids), 500):
                    batch = ids[start:start + 500]
                    placeholders, params = _batch_params(batch, "d")
                    result = await conn.execute(self._sql_text(
                        f"DELETE FROM {table} WHERE {_q('id', dialect)} IN ({placeholders})"
                    ), params)
                    await conn.execute(self._sql_text(
                        f"DELETE FROM {sys_table} WHERE {_q('id', dialect)} IN ({placeholders})"
                    ), params)
                    deleted_count += int(result.rowcount or 0)
            if deleted_count == len(ids):
                return {object_id: True for object_id in ids}
            async with engine.connect() as rconn:
                for start in range(0, len(ids), 500):
                    batch = ids[start:start + 500]
                    placeholders, params = _batch_params(batch, "s")
                    result = await rconn.execute(self._sql_text(
                        f"SELECT {_q('id', dialect)} FROM {table} WHERE {_q('id', dialect)} IN ({placeholders})"
                    ), params)
                    existing_ids.update(str(row[0]) for row in result.fetchall())
            return {object_id: object_id not in existing_ids for object_id in ids}

        if has_file_id:
            async with engine.connect() as rconn:
                for start in range(0, len(ids), 500):
                    batch = ids[start:start + 500]
                    placeholders, params = _batch_params(batch, "s")
                    result = await rconn.execute(self._sql_text(
                        f"SELECT * FROM {table} WHERE {_q('id', dialect)} IN ({placeholders})"
                    ), params)
                    rows = result.fetchall()
                    for row in rows:
                        payload = _deserialize_row(
                            self._row_mapping_dict(row._mapping), specs,
                            field_name_map=fnmap,
                        )
                        existing_id = str(payload.get("id") or payload.get("_id") or "")
                        if not existing_id:
                            continue
                        existing_ids.add(existing_id)
                        await self._cleanup_foreign_on_delete(collection_name, payload)

        if not existing_ids:
            return {object_id: False for object_id in ids}

        existing_list = sorted(existing_ids)
        async with engine.begin() as conn:
            for start in range(0, len(existing_list), 500):
                batch = existing_list[start:start + 500]
                placeholders, params = _batch_params(batch, "d")
                await conn.execute(self._sql_text(
                    f"DELETE FROM {table} WHERE {_q('id', dialect)} IN ({placeholders})"
                ), params)
                await conn.execute(self._sql_text(
                    f"DELETE FROM {sys_table} WHERE {_q('id', dialect)} IN ({placeholders})"
                ), params)
        return {object_id: object_id in existing_ids for object_id in ids}

    async def set_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId, expire: float | int | None) -> bool:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return False
        engine = await self._ensure_schema_ready()
        object_id_str = str(object_id)
        expire_at = _normalize_expire_at(expire)
        dialect = str(engine.dialect.name).lower()
        sys_table = self._sys_table_sql(collection_name)
        async with engine.begin() as conn:
            result = await conn.execute(self._sql_text(
                f"UPDATE {sys_table} SET expire_at = :ea WHERE {_q('id', dialect)} = :oid"
            ), {"ea": expire_at, "oid": object_id_str})
            return result.rowcount > 0

    async def get_expire(self, collection: CollectionLike[ORMModel], object_id: str | ObjectId) -> float | None:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return None
        engine = await self._ensure_schema_ready()
        object_id_str = str(object_id)
        dialect = str(engine.dialect.name).lower()
        sys_table = self._sys_table_sql(collection_name)
        async with engine.begin() as conn:
            result = await conn.execute(self._sql_text(
                f"SELECT expire_at FROM {sys_table} WHERE {_q('id', dialect)} = :oid"
            ), {"oid": object_id_str})
            row = result.fetchone()
        if row is None:
            return None
        ttl = _ttl_from_expire_at(row[0])
        if ttl == 0.0:
            await self.delete(collection_name, object_id_str)
        return ttl

    async def collection_count(self, collection: str) -> int:
        if not await self._async_collection_exists(collection):
            return 0
        engine = await self._ensure_schema_ready()
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        async with engine.connect() as conn:
            result = await conn.execute(
                self._sql_text(
                    f"SELECT COUNT(*) FROM {table} d"
                    f" LEFT JOIN {sys_table} s ON d.{_q('id', dialect)} = s.{_q('id', dialect)}"
                    f" WHERE s.expire_at IS NULL OR s.expire_at > :now"
                ),
                {"now": _now_ts()},
            )
            row = result.fetchone()
        return int(row[0] if row else 0)

    async def query_count(self, collection: CollectionLike[ORMModel], query: "QueryLike" = None) -> int:
        collection_name, _ = self._normalize_collection(collection)
        if not await self._async_collection_exists(collection_name):
            return 0
        engine = await self._ensure_schema_ready()
        native_fields = self._get_native_field_specs(collection_name)
        dialect = str(engine.dialect.name).lower()
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)
        counter = _ParamCounter()
        q_result = _query_to_sql_conditions(query, dialect, counter=counter, native_fields=native_field_names(native_fields), field_name_map=self._get_field_name_map(collection_name))
        if q_result is None:
            raise ValueError(f"{dialect} query_count only supports pushdown-compatible filters.")
        conditions, params = q_result
        params = {"_now": _now_ts(), **params}
        where_parts: list[str] = ["(s.expire_at IS NULL OR s.expire_at > :_now)"]
        where_parts.extend(conditions)
        async with engine.connect() as conn:
            result = await conn.execute(
                self._sql_text(
                    f"SELECT COUNT(*) FROM {table} d"
                    f" LEFT JOIN {sys_table} s ON d.{_q('id', dialect)} = s.{_q('id', dialect)}"
                    f" WHERE {' AND '.join(where_parts)}"
                ),
                params,
            )
            row = result.fetchone()
        return int(row[0] if row else 0)

    async def cleanup(self, *, force: bool = False) -> int:
        if not await self._should_cleanup_async(force=force):
            return 0
        async with self._cleanup_async_lock():
            if not await self._should_cleanup_async(force=force):
                return 0
            engine = await self._ensure_schema_ready()
            removed = 0
            total_size = 0
            rows_all: list[tuple[str, str, int, float]] = []
            now = _now_ts()
            dialect = str(engine.dialect.name).lower()
            async with engine.begin() as conn:
                coll_result = await conn.execute(self._sql_text("SELECT collection_name FROM _orm_collections"))
                collections = [row[0] for row in coll_result.fetchall()]
                for coll in collections:
                    table = self._table_sql(coll)
                    sys_table = self._sys_table_sql(coll)
                    exp_result = await conn.execute(self._sql_text(
                        f'SELECT {_q("id", dialect)} FROM {sys_table} WHERE expire_at IS NOT NULL AND expire_at <= :ts'
                    ), {"ts": now})
                    expired_ids = [row[0] for row in exp_result.fetchall()]
                    if expired_ids:
                        for i in range(0, len(expired_ids), 500):
                            batch = expired_ids[i:i + 500]
                            ph = ", ".join(f":e{j}" for j in range(len(batch)))
                            params = {f"e{j}": oid for j, oid in enumerate(batch)}
                            await conn.execute(self._sql_text(
                                f'DELETE FROM {table} WHERE {_q("id", dialect)} IN ({ph})'
                            ), params)
                            await conn.execute(self._sql_text(
                                f'DELETE FROM {sys_table} WHERE {_q("id", dialect)} IN ({ph})'
                            ), params)
                        removed += len(expired_ids)
                    if self._max_size is not None:
                        size_result = await conn.execute(self._sql_text(
                            f'SELECT {_q("id", dialect)}, {_q("size", dialect)}, accessed_at FROM {sys_table}'
                        ))
                        for row in size_result.fetchall():
                            sz = int(row[1])
                            total_size += sz
                            rows_all.append((coll, row[0], sz, float(row[2])))
                total_count = len(rows_all)
                if self._max_size is not None and total_count > self._max_size:
                    target = max(0, int(self._max_size * 0.9))
                    evict_by_coll: dict[str, list[str]] = {}
                    for coll, oid, sz, _ in sorted(rows_all, key=lambda item: item[3]):
                        if total_count <= target:
                            break
                        evict_by_coll.setdefault(coll, []).append(oid)
                        total_count -= 1
                        removed += 1
                    for coll, oids in evict_by_coll.items():
                        for i in range(0, len(oids), 500):
                            batch = oids[i:i + 500]
                            ph = ", ".join(f":v{j}" for j in range(len(batch)))
                            params = {f"v{j}": oid for j, oid in enumerate(batch)}
                            await conn.execute(self._sql_text(
                                f'DELETE FROM {self._table_sql(coll)} WHERE {_q("id", dialect)} IN ({ph})'
                            ), params)
                            await conn.execute(self._sql_text(
                                f'DELETE FROM {self._sys_table_sql(coll)} WHERE {_q("id", dialect)} IN ({ph})'
                            ), params)
            await self._mark_cleanup_async()
            return removed



__all__ = ['SQL_ORM_Client']
