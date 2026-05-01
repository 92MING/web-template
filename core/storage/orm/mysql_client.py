import asyncio

from urllib.parse import quote_plus
from typing import TYPE_CHECKING
from typing_extensions import Unpack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine as _AsyncEngine

from .field_schema import (
    sql_column_type,
)
from ..base import (
    _json_dumps,
    _json_dumps_bytes,
    _normalize_expire_at,
    _now_ts,
)
from .model import ORMModel, CollectionLike
from .client_base import (
    ORMPayloadLike,
    SQLORMClientInitParams,
    _get_schema_lock,
    _q,
    _native_column_values,
    _safe_model_schema,
)
from .sql_client import SQL_ORM_Client

class MySQLORMClientInitParams(SQLORMClientInitParams, total=False):
    host: str
    port: int
    username: str
    password: str | None
    database: str


class MySQLORMClient(SQL_ORM_Client, type="mysql"):
    """SQLAlchemy-based async ORM client for MySQL / MariaDB.

    Uses the ``aiomysql`` driver (``mysql+aiomysql://``).
    Install: ``pip install aiomysql``
    """

    def __init__(self, **params: Unpack["MySQLORMClientInitParams"]) -> None:  # type: ignore[override]
        url = params.get("url")
        if not url:
            url = self.build_url(
                host=str(params.get("host", "127.0.0.1")),
                port=int(params.get("port", 3306)),
                username=str(params.get("username", "root")),
                password=params.get("password"),
                database=str(params.get("database", "app_backend")),
            )
        params["url"] = url
        super().__init__(**params)

    @staticmethod
    def build_url(*, host: str, port: int = 3306, username: str = "root", password: str | None = None, database: str = "app_backend") -> str:
        user_part = quote_plus(username)
        password_part = "" if password in (None, "") else f":{quote_plus(str(password))}"
        database_part = quote_plus(database)
        return f"mysql+aiomysql://{user_part}{password_part}@{host}:{int(port)}/{database_part}"

    # ── MySQL-specific DDL overrides ─────────────────────────────────
    # MySQL does not support:
    #   - TEXT PRIMARY KEY without explicit key length
    #   - ON CONFLICT ... DO UPDATE (use ON DUPLICATE KEY UPDATE instead)

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
                    collection_name VARCHAR(255) NOT NULL,
                    model_module TEXT,
                    model_name TEXT,
                    schema_json LONGTEXT,
                    PRIMARY KEY (collection_name)
                )
                """
            ))
            # Migration: drop legacy created_at column
            for _legacy_col in ("created_at",):
                try:
                    await conn.execute(self._sql_text(f"ALTER TABLE _orm_collections DROP COLUMN {_legacy_col}"))
                except Exception:
                    pass
        self._schema_ready = True
        return engine

    async def create_collection(self, model_cls: type[ORMModel]) -> None:
        await self._ensure_schema_ready()
        self.register_model(model_cls)
        collection = model_cls.CollectionName
        table = self._table_sql(collection)
        sys_table = self._sys_table_sql(collection)
        new_schema = _safe_model_schema(model_cls)
        specs = self._get_native_field_specs(collection)

        # Build column definitions from field specs
        col_defs: list[str] = ["`id` VARCHAR(255) NOT NULL"]
        for spec in (specs or {}).values():
            col_defs.append(f"{_q(spec.column_name, 'mysql')} {sql_column_type(spec, 'mysql')}")
        col_defs.append("PRIMARY KEY (`id`)")

        with _get_schema_lock(collection):
            async with self._engine.begin() as conn:
                # ── data table ──
                await conn.execute(self._sql_text(
                    f"CREATE TABLE IF NOT EXISTS `{table}` ({', '.join(col_defs)})"
                ))
                # ── sys table ──
                sys_col_defs = [
                    "`id` VARCHAR(255) NOT NULL",
                    "expire_at DOUBLE",
                    "`size` INTEGER NOT NULL",
                    "accessed_at DOUBLE NOT NULL",
                    "PRIMARY KEY (`id`)",
                ]
                # blob_union → {col}_type column in sys table
                for spec in (specs or {}).values():
                    if spec.kind == "blob_union":
                        type_col = f"{spec.column_name}_type"
                        sys_col_defs.insert(-1, f"{_q(type_col, 'mysql')} VARCHAR(64)")
                await conn.execute(self._sql_text(
                    f"CREATE TABLE IF NOT EXISTS `{sys_table}` ({', '.join(sys_col_defs)})"
                ))
                # Migration: drop legacy created_at/updated_at from sys table
                for _legacy_col in ("created_at", "updated_at"):
                    try:
                        await conn.execute(self._sql_text(f"ALTER TABLE `{sys_table}` DROP COLUMN {_legacy_col}"))
                    except Exception:
                        pass
                # ── collection registry ──
                await conn.execute(self._sql_text(
                    """
                    INSERT INTO _orm_collections(collection_name, model_module, model_name, schema_json)
                    VALUES (:collection_name, :model_module, :model_name, :schema_json)
                    ON DUPLICATE KEY UPDATE
                        model_module=VALUES(model_module),
                        model_name=VALUES(model_name),
                        schema_json=VALUES(schema_json)
                    """
                ), {
                    "collection_name": collection,
                    "model_module": model_cls.__module__,
                    "model_name": model_cls.__name__,
                    "schema_json": _json_dumps(new_schema),
                })
                # ── sys table indexes (MySQL has no CREATE INDEX IF NOT EXISTS; catch 1061) ──
                for idx_sql in [
                    f"CREATE INDEX idx_{collection}_sys_expire ON `{sys_table}` (expire_at)",
                    f"CREATE INDEX idx_{collection}_sys_access ON `{sys_table}` (accessed_at)",
                ]:
                    try:
                        await conn.execute(self._sql_text(idx_sql))
                    except Exception as _idx_err:
                        if "1061" not in str(_idx_err):
                            raise
                # ── schema evolution (adds missing columns + their indexes) ──
                await self._ensure_field_schema(conn, collection)
        self._mark_collection_known(collection)
        self._bootstrapped_collections.add(collection)

    async def set(self, value: ORMModel | ORMPayloadLike, *, collection: CollectionLike[ORMModel] | None = None, expire: float | int | None = None, create_collection: bool = True) -> str:  # type: ignore[override]
        await self._ensure_schema_ready()
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

        # Delegate to base class for dual-table upsert (base _upsert_sql handles MySQL dialect)
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

        ts = _now_ts()
        expire_at = _normalize_expire_at(expire if expire is not None else self._default_expire)
        table = self._table_sql(collection_name)
        sys_table = self._sys_table_sql(collection_name)

        # ── data table upsert ──
        data_columns = [_q("id", "mysql"), *[_q(c, "mysql") for c in column_values.keys()]]
        data_placeholders = [":oid", *[f":d_{i}" for i in range(len(column_values))]]
        data_update = [_q(c, "mysql") for c in column_values.keys()]
        data_params: dict[str, object] = {
            "oid": object_id,
            **{f"d_{i}": v for i, v in enumerate(column_values.values())},
        }

        # ── sys table upsert ──
        payload_bytes = _json_dumps_bytes(payload)
        sys_columns = [_q("id", "mysql"), "expire_at", _q("size", "mysql"), "accessed_at"]
        sys_placeholders = [":oid", ":expire_at", ":sz", ":accessed_at"]
        sys_update = ["expire_at", _q("size", "mysql"), "accessed_at"]
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
                sys_columns.append(_q(type_col, "mysql"))
                sys_placeholders.append(f":bt_{spec.column_name}")
                sys_update.append(_q(type_col, "mysql"))
                sys_params[f"bt_{spec.column_name}"] = type_val

        async with self._engine.begin() as conn:
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



__all__ = ['MySQLORMClientInitParams', 'MySQLORMClient']
