import asyncio
from datetime import datetime, timedelta
from typing import Callable, Literal, Mapping, Sequence, cast, overload
from pydantic import Field

from ...utils.concurrent_utils import run_any_func, run_in_background
from ...utils.type_utils import AdvancedBaseModel
from ...utils.log_utils import LogRecord
from .field_schema import extract_field_specs
from .field_metadata import ORMField, build_field_name_mapping
from ..base import (
    _now_ts,
    _validate_collection_name,
)
from .model import ORMModel
from .client_base import (
    ORM_ClientBase,
    _q,
    _deserialize_row,
)
from .sqlite_client import SQLiteORMClient
from .sql_client import SQL_ORM_Client

# ──────────────────────────────────────────────────────────────────────────────
LOG_RECORD_TEXT_MAX_LENGTH = 16 * 1024


class LogRecordModel(ORMModel, collection_name="proj_log"):
    """单条应用日志记录模型（存储于 ORM log_db）。"""
    timestamp: str
    """日志时间，格式 `YYYY-MM-DD HH:MM:SS`。"""
    level: str
    """日志级别字符串，例如 `INFO`。"""
    levelno: int
    """数值级别，例如 20 表示 INFO。"""
    name: str
    """Logger 名称。"""
    process: int
    """写入时的进程 ID。"""
    message: str = ORMField(default="", max_length=LOG_RECORD_TEXT_MAX_LENGTH)
    """格式化后的日志消息。"""
    exc_info: str | None = ORMField(default=None, max_length=LOG_RECORD_TEXT_MAX_LENGTH)
    """异常堆栈字符串；无异常时为 `None`。"""

_LOG_RECORD_MODEL_CACHE: dict[str, type[LogRecordModel]] = {
    LogRecordModel.CollectionName: LogRecordModel,
}

def get_log_record_model(collection_name: str = "proj_log") -> type[LogRecordModel]:
    """Return a `LogRecordModel` subclass bound to the configured collection."""
    _validate_collection_name(collection_name)
    cached = _LOG_RECORD_MODEL_CACHE.get(collection_name)
    if cached is not None:
        return cached

    class ConfiguredLogRecordModel(LogRecordModel, full_collection_name=collection_name):
        pass

    ConfiguredLogRecordModel.__name__ = f"LogRecordModel_{collection_name}"
    ConfiguredLogRecordModel.__qualname__ = ConfiguredLogRecordModel.__name__
    _LOG_RECORD_MODEL_CACHE[collection_name] = ConfiguredLogRecordModel
    return ConfiguredLogRecordModel


class SystemMetricRecord(ORMModel, collection_name="system_metrics"):
    """单条系统指标快照。

    默认写入 ``orm.system_metrics`` 客户端；若未配置则回退到 ``orm.log``。
    """

    class DiskMetricData(AdvancedBaseModel):
        used_gb: float = 0.0
        total_gb: float = 0.0
        percent: float = 0.0

    class NetworkInterfaceMetricData(AdvancedBaseModel):
        bytes_sent: int = 0
        bytes_recv: int = 0
        packets_sent: int = 0
        packets_recv: int = 0

    class DiskIOMetricData(AdvancedBaseModel):
        read_bytes: int = 0
        write_bytes: int = 0
        read_count: int = 0
        write_count: int = 0

    timestamp: str
    """采集时间，格式 `YYYY-MM-DD HH:MM:SS`。"""
    cpu_avg: float = 0.0
    """所有核心的平均 CPU 使用率（%）。"""
    cpu_cores: list[float] = Field(default_factory=list)
    """各核心 CPU 使用率列表。"""
    cpu_freq: float | None = None
    """当前 CPU 频率（MHz）；不支持时为 `None`。"""
    cpu_temp: float | None = None
    """当前 CPU 温度（°C）；不支持时为 `None`。"""
    mem_used: int = 0
    """已用内存（MB）。"""
    mem_total: int = 0
    """总内存（MB）。"""
    mem_pct: float = 0.0
    """内存使用率（%）。"""
    disk_data: dict[str, DiskMetricData] = Field(default_factory=dict)
    """各挂载点磁盘信息，格式：`{mount: {used_gb, total_gb, percent}}`。"""
    network_data: dict[str, NetworkInterfaceMetricData] = Field(default_factory=dict)
    """网卡累计 IO 指标，格式：`{nic_id: {bytes_sent, bytes_recv, packets_sent, packets_recv}}`。"""
    disk_io_data: dict[str, DiskIOMetricData] = Field(default_factory=dict)
    """磁盘累计 IO 指标，格式：`{disk_id: {read_bytes, write_bytes, read_count, write_count}}`。"""
    process_count: int = 0
    """当前进程总数。"""


class ORMSystemMetricsStore:
    """将 ``SystemMetricRecord`` 写入 ORM 客户端的系统指标存储后端。
    实现了 ``SystemMetricsStoreProtocol``：提供同步写入（fire-and-forget）与异步查询接口。
    """

    def __init__(self, client: "ORM_ClientBase", *, retention_seconds: float | int | None = None) -> None:
        self._client = client
        self._retention_seconds = None if retention_seconds is None else max(0.0, float(retention_seconds))

    def write(self, record: SystemMetricRecord) -> None:
        """写入一条系统指标快照（同步，fire-and-forget）。"""
        run_any_func(self._async_write, record)

    async def _async_write(self, record: SystemMetricRecord) -> None:
        from ...utils.log_utils.db_log_handler import db_log_write_scope
        try:
            with db_log_write_scope():
                expire = self._retention_seconds if self._retention_seconds and self._retention_seconds > 0 else None
                await self._client.set(record, expire=expire)
        except Exception:
            pass

    async def query_latest(self) -> dict[str, object] | None:
        """返回最新一条系统指标快照，表不存在或为空时返回 ``None``。"""
        latest: dict[str, object] | None = None
        async for item in self._client.search(SystemMetricRecord, as_model=False):
            row = dict(cast(Mapping[str, object], item))
            if latest is None or str(row.get("timestamp", "")) > str(latest.get("timestamp", "")):
                latest = row
        return latest

    async def query_last_n(self, seconds: int = 60) -> list[dict[str, object]]:
        """返回最近 *seconds* 秒内的系统指标列表（按时间升序）。"""
        cutoff = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        results: list[dict[str, object]] = []
        async for item in self._client.search(SystemMetricRecord, as_model=False):
            row = dict(cast(Mapping[str, object], item))
            if str(row.get("timestamp", "")) >= cutoff:
                results.append(row)
        results.sort(key=lambda r: str(r.get("timestamp", "")))
        return results


def make_orm_system_metrics_store(client: "ORM_ClientBase", *, retention_seconds: float | int | None = None) -> "ORMSystemMetricsStore":
    """从 ORM 客户端创建 :class:`ORMSystemMetricsStore` 实例。

    调用方应传入 ``cfg.orm.get_client('system_metrics', fallback='log')``
    以优先使用独立的 system_metrics 客户端，未配置时回退到 log 客户端。

    Args:
        client: 已初始化的 ORM 客户端。
        retention_seconds: 单条系统指标的 TTL 秒数；``None`` 或 ``0`` 表示不设置过期时间。

    Returns:
        可被 system_metrics worker 使用的指标存储对象。
    """
    return ORMSystemMetricsStore(client, retention_seconds=retention_seconds)



# ──────────────────────────────────────────────────────────────────────────────
class DefaultORMLogStore:
    """基于 ORM 客户端的日志存储实现。

    Parameters
    ----------
    client:
        已初始化的 ORM 客户端实例。
    model_cls_factory:
        返回日志 ORM Model 类的无参可调用对象，例如
        ``lambda: get_log_record_model("log")``。
    """

    def __init__(
        self,
        client: ORM_ClientBase,
        model_cls_factory: Callable[[], type[LogRecordModel]],
    ) -> None:
        self._client = client
        self._model_cls_factory = model_cls_factory
        self._model_cls: type[LogRecordModel] | None = None
        self._silence_driver_loggers()

    @staticmethod
    def _silence_driver_loggers() -> None:
        """Prevent driver-level debug logs from creating infinite recursion.

        aiosqlite processes SQL on a dedicated worker thread.  If that thread
        emits a debug log, it hits ORMLogHandler.emit() → write() →
        _async_write() → aiosqlite → worker thread → debug log → ∞.
        Stopping propagation of the driver logger breaks this cycle.
        """
        import logging as _logging
        for name in ("aiosqlite",):
            lg = _logging.getLogger(name)
            if not lg.handlers:
                lg.addHandler(_logging.NullHandler())
            lg.propagate = False

    def _get_client(self) -> ORM_ClientBase:
        return self._client

    def _get_model_cls(self) -> type[LogRecordModel]:
        if self._model_cls is None:
            self._model_cls = self._model_cls_factory()
        return self._model_cls

    async def _ensure_collection(self) -> type[LogRecordModel]:
        client = self._get_client()
        model_cls = self._get_model_cls()
        await client.ensure_collection(model_cls)
        return model_cls

    @staticmethod
    def _matches_filters(
        row: Mapping[str, object],
        *,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> bool:
        if level and str(row.get("level", "")).upper() != level.upper():
            return False
        if min_levelno is not None and int(row.get("levelno", 0) or 0) < min_levelno:
            return False
        if name_filter and name_filter.lower() not in str(row.get("name", "")).lower():
            return False
        if search and search.lower() not in str(row.get("message", "")).lower():
            return False
        if since and str(row.get("timestamp", "")) < since:
            return False
        if until and str(row.get("timestamp", "")) > until:
            return False
        return True

    def _sql_json_field_expr(self, client: SQL_ORM_Client | SQLiteORMClient, field: str) -> str | None:
        if isinstance(client, SQLiteORMClient):
            dialect = "sqlite"
        else:
            dialect = str(client._engine.dialect.name).lower()
        return f"d.{_q(field, dialect)}"

    @staticmethod
    def _parse_log_timestamp(value: str | None) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _sql_row_to_dict(row: object) -> dict[str, object]:
        mapping = getattr(row, "_mapping", None)
        if isinstance(mapping, Mapping):
            return dict(mapping)
        return dict(cast(Mapping[str, object], row))

    @staticmethod
    def _sql_row_index_value(row: object, index: int) -> object | None:
        return cast(Sequence[object], row)[index]

    def _build_sql_filter_parts(
        self,
        *,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
        order: str = "DESC",
    ) -> tuple[SQL_ORM_Client | SQLiteORMClient, str, str, list[str], dict[str, object], str] | None:
        client = self._get_client()
        if isinstance(client, SQL_ORM_Client):
            dialect = str(client._engine.dialect.name).lower()
        elif isinstance(client, SQLiteORMClient):
            dialect = "sqlite"
        else:
            return None
        model_cls = self._get_model_cls()
        collection, _ = client._normalize_collection(model_cls)
        if not client._started:
            client.start()
        if not client._collection_exists(collection):
            return client, collection, dialect, [], {"__table_missing__": True}, "accessed_at DESC"

        timestamp_expr = self._sql_json_field_expr(client, "timestamp")
        level_expr = self._sql_json_field_expr(client, "level")
        levelno_expr = self._sql_json_field_expr(client, "levelno")
        name_expr = self._sql_json_field_expr(client, "name")
        message_expr = self._sql_json_field_expr(client, "message")
        if not all((timestamp_expr, level_expr, levelno_expr, name_expr, message_expr)):
            return None

        direction = "ASC" if str(order).upper() == "ASC" else "DESC"
        conditions = ["(s.expire_at IS NULL OR s.expire_at > :now)"]
        params: dict[str, object] = {"now": _now_ts()}
        if level:
            params["level"] = str(level).upper()
            conditions.append(f"UPPER(COALESCE({level_expr}, '')) = :level")
        if min_levelno is not None:
            params["min_levelno"] = int(min_levelno)
            conditions.append(f"CAST(COALESCE({levelno_expr}, 0) AS INTEGER) >= :min_levelno")
        if name_filter:
            params["name_filter"] = f"%{str(name_filter).lower()}%"
            conditions.append(f"LOWER(COALESCE({name_expr}, '')) LIKE :name_filter")
        if search:
            params["search"] = f"%{str(search).lower()}%"
            conditions.append(f"LOWER(COALESCE({message_expr}, '')) LIKE :search")
        since_ts = self._parse_log_timestamp(since)
        if since_ts is not None:
            params["since_ts"] = since_ts
            conditions.append("s.accessed_at >= :since_ts")
        elif since:
            params["since"] = str(since)
            conditions.append(f"COALESCE({timestamp_expr}, '') >= :since")
        until_ts = self._parse_log_timestamp(until)
        if until_ts is not None:
            params["until_ts"] = until_ts
            conditions.append("s.accessed_at <= :until_ts")
        elif until:
            params["until"] = str(until)
            conditions.append(f"COALESCE({timestamp_expr}, '') <= :until")
        order_clause = f"s.accessed_at {direction}"
        return client, collection, dialect, conditions, params, order_clause

    async def _execute_sql_fetchall(self, client: SQL_ORM_Client | SQLiteORMClient, query_sql: str, params: dict[str, object]) -> list[object]:
        if isinstance(client, SQL_ORM_Client):
            await client._ensure_schema_ready()
            async with client._engine.connect() as conn:
                result = await conn.execute(client._sql_text(query_sql), params)
                return list(result.fetchall())
        if isinstance(client, SQLiteORMClient):
            conn = await client._get_conn()
            cursor = await conn.execute(query_sql, params)
            return list(await cursor.fetchall())
        raise TypeError(f"DefaultORMLogStore SQL helpers require a SQL ORM client, got {type(client).__name__}.")

    async def _execute_sql_fetchone(self, client: SQL_ORM_Client | SQLiteORMClient, query_sql: str, params: dict[str, object]) -> object | None:
        if isinstance(client, SQL_ORM_Client):
            await client._ensure_schema_ready()
            async with client._engine.connect() as conn:
                result = await conn.execute(client._sql_text(query_sql), params)
                return result.fetchone()
        if isinstance(client, SQLiteORMClient):
            conn = await client._get_conn()
            cursor = await conn.execute(query_sql, params)
            return await cursor.fetchone()
        raise TypeError(f"DefaultORMLogStore SQL helpers require a SQL ORM client, got {type(client).__name__}.")

    # 日志写入是 fire-and-forget；外层 timeout 仅会产生噪音 ERROR
    # （内层已 except Exception: pass）。将外层 timeout 关闭，
    # 由内层 asyncio.wait_for 把单条写入封顶到 10s，避免 SQLite 文件锁
    # 竞争时的 120s 阻塞误报。
    _LOG_WRITE_TIMEOUT_SECONDS = 10

    def write(self, record: LogRecord) -> None:
        run_in_background(self._async_write, args=(record,), timeout=None)

    async def _async_write(self, record: LogRecord) -> None:
        from ...utils.log_utils.db_log_handler import db_log_write_scope
        try:
            with db_log_write_scope():
                client = self._get_client()
                model_cls = await self._ensure_collection()
                await asyncio.wait_for(
                    client.set(model_cls.model_validate(record)),
                    timeout=self._LOG_WRITE_TIMEOUT_SECONDS,
                )
        except Exception:
            pass

    @overload
    async def query(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
        order: str = "DESC",
        include_total: Literal[False] = False,
    ) -> list[dict[str, object]]:
        ...

    @overload
    async def query(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
        order: str = "DESC",
        include_total: Literal[True] = True,
    ) -> tuple[list[dict[str, object]], int]:
        ...

    async def query(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
        order: str = "DESC",
        include_total: bool = False,
    ) -> list[dict[str, object]] | tuple[list[dict[str, object]], int]:
        sql_parts = self._build_sql_filter_parts(
            level=level,
            min_levelno=min_levelno,
            name_filter=name_filter,
            search=search,
            since=since,
            until=until,
            order=order,
        )
        if sql_parts is not None:
            client, collection, dialect, conditions, params, order_clause = sql_parts
            if params.pop("__table_missing__", False):
                return ([], 0) if include_total else []
            table = client._table_sql(collection)
            sys_table = client._sys_table_sql(collection)
            id_q = _q("id", dialect)
            select_columns = "d.*"
            if include_total:
                select_columns += ", COUNT(*) OVER() AS total_count"
            query_sql = (
                f"SELECT {select_columns} FROM {table} d"
                f" LEFT JOIN {sys_table} s ON d.{id_q} = s.{id_q}"
                f" WHERE {' AND '.join(conditions)} ORDER BY {order_clause}"
            )
            query_params = dict(params)
            if limit is not None:
                query_sql += " LIMIT :limit"
                query_params["limit"] = int(limit)
            if offset > 0:
                query_sql += " OFFSET :offset"
                query_params["offset"] = int(offset)
            rows = await self._execute_sql_fetchall(client, query_sql, query_params)
            model_cls = self._get_model_cls()
            specs = extract_field_specs(model_cls)
            fnmap = build_field_name_mapping(model_cls)
            results: list[dict[str, object]] = []
            total = 0
            for row in rows:
                if include_total and total == 0:
                    # total_count is the last column in the row
                    total_value = self._sql_row_index_value(row, -1)
                    total = int(total_value or 0) if total_value is not None else 0
                row_dict = self._sql_row_to_dict(row)
                payload = _deserialize_row(row_dict, specs, field_name_map=fnmap)
                results.append(dict(cast(Mapping[str, object], payload)))
            if include_total:
                if not rows and offset > 0:
                    total = await self.count_filtered(
                        level=level,
                        min_levelno=min_levelno,
                        name_filter=name_filter,
                        search=search,
                        since=since,
                        until=until,
                    )
                return results, total
            return results

        client = self._get_client()
        model_cls = await self._ensure_collection()
        results: list[dict[str, object]] = []
        async for item in client.search(model_cls, as_model=False):
            row = dict(cast(Mapping[str, object], item))
            if not self._matches_filters(
                row,
                level=level,
                min_levelno=min_levelno,
                name_filter=name_filter,
                search=search,
                since=since,
                until=until,
            ):
                continue
            results.append(row)
        results.sort(key=lambda r: str(r.get("timestamp", "")), reverse=(order.upper() == "DESC"))
        total = len(results)
        paged_results = results[offset: offset + limit]
        if include_total:
            return paged_results, total
        return paged_results

    async def count(self) -> int:
        return await self.count_filtered()

    async def count_filtered(
        self,
        *,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> int:
        sql_parts = self._build_sql_filter_parts(
            level=level,
            min_levelno=min_levelno,
            name_filter=name_filter,
            search=search,
            since=since,
            until=until,
        )
        if sql_parts is not None:
            client, collection, dialect, conditions, params, _order_clause = sql_parts
            if params.pop("__table_missing__", False):
                return 0
            table = client._table_sql(collection)
            sys_table = client._sys_table_sql(collection)
            id_q = _q("id", dialect)
            query_sql = (
                f"SELECT COUNT(*) FROM {table} d"
                f" LEFT JOIN {sys_table} s ON d.{id_q} = s.{id_q}"
                f" WHERE {' AND '.join(conditions)}"
            )
            row = await self._execute_sql_fetchone(client, query_sql, params)
            return int(self._sql_row_index_value(row, 0) or 0) if row else 0

        client = self._get_client()
        model_cls = await self._ensure_collection()
        total = 0
        async for item in client.search(model_cls, as_model=False):
            row = dict(cast(Mapping[str, object], item))
            if not self._matches_filters(
                row,
                level=level,
                min_levelno=min_levelno,
                name_filter=name_filter,
                search=search,
                since=since,
                until=until,
            ):
                continue
            total += 1
        return total

    async def aggregate_buckets(
        self,
        *,
        since: str,
        until: str,
        bucket_minutes: int,
        level: str | None = None,
        min_levelno: int | None = None,
        name_filter: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, object]]:
        """聚合 ``[since, until)`` 时段内的日志，按 ``bucket_minutes`` 分桶。

        返回每个用户分桶的 ``{bucket: 'YYYY-MM-DD HH:MM', total, level_dist, name_counts}``。
        SQL 端按分钟（或小时，当 bucket_minutes>=60 时）GROUP BY，再在 Python 重分桶到
        用户指定的桶宽，从而避开方言差异。
        """
        sql_parts = self._build_sql_filter_parts(
            level=level,
            min_levelno=min_levelno,
            name_filter=name_filter,
            search=search,
            since=since,
            until=until,
        )
        if sql_parts is None:
            raise TypeError("aggregate_buckets requires SQL ORM client.")
        client, _collection, dialect, conditions, params, _order_clause = sql_parts
        if params.pop("__table_missing__", False):
            return []
        timestamp_expr = self._sql_json_field_expr(client, "timestamp")
        level_expr = self._sql_json_field_expr(client, "level")
        name_expr = self._sql_json_field_expr(client, "name")
        sql_bucket_chars = 13 if (bucket_minutes >= 60 and bucket_minutes % 60 == 0) else 16
        bucket_expr = f"substr(COALESCE({timestamp_expr}, ''), 1, {sql_bucket_chars})"
        # Reuse the table/sys_table joining used elsewhere in this class.
        table = client._table_sql(_collection)
        sys_table = client._sys_table_sql(_collection)
        id_q = _q("id", dialect)
        query_sql = (
            f"SELECT {bucket_expr} AS bkt, COALESCE({level_expr}, '') AS lvl, "
            f"COALESCE({name_expr}, '') AS nm, COUNT(*) AS cnt "
            f"FROM {table} d LEFT JOIN {sys_table} s ON d.{id_q} = s.{id_q} "
            f"WHERE {' AND '.join(conditions)} "
            f"GROUP BY bkt, lvl, nm"
        )
        rows = await self._execute_sql_fetchall(client, query_sql, params)
        # Re-bucket SQL rows (minute or hour granularity) to user bucket_minutes.
        from collections import defaultdict
        buckets: dict[str, dict[str, object]] = {}
        for row in rows:
            bkt_raw = self._sql_row_index_value(row, 0)
            lvl = str(self._sql_row_index_value(row, 1) or "")
            nm = str(self._sql_row_index_value(row, 2) or "")
            cnt = int(self._sql_row_index_value(row, 3) or 0)
            user_bucket_iso = self._snap_bucket_iso(str(bkt_raw or ""), bucket_minutes)
            if not user_bucket_iso:
                continue
            slot = buckets.setdefault(user_bucket_iso, {
                "bucket": user_bucket_iso,
                "total": 0,
                "level_dist": defaultdict(int),
                "name_counts": defaultdict(int),
                "name_level": defaultdict(lambda: defaultdict(int)),
                "last_seen": "",
            })
            slot["total"] = int(slot["total"]) + cnt  # type: ignore[arg-type]
            slot["level_dist"][lvl] += cnt  # type: ignore[index]
            slot["name_counts"][nm] += cnt  # type: ignore[index]
            slot["name_level"][nm][lvl] += cnt  # type: ignore[index]
            # bucket itself (minute or hour) is the best last-seen timestamp we have here.
            if str(bkt_raw or "") > str(slot["last_seen"] or ""):
                slot["last_seen"] = str(bkt_raw or "")
        # Convert defaultdicts to plain dicts for serialization/caching.
        result: list[dict[str, object]] = []
        for slot in sorted(buckets.values(), key=lambda x: str(x["bucket"])):
            slot["level_dist"] = dict(slot["level_dist"])
            slot["name_counts"] = dict(slot["name_counts"])
            slot["name_level"] = {n: dict(lv) for n, lv in slot["name_level"].items()}  # type: ignore[union-attr]
            result.append(slot)
        return result

    @staticmethod
    def _snap_bucket_iso(raw: str, bucket_minutes: int) -> str:
        """将 SQL 端的 'YYYY-MM-DD HH' 或 'YYYY-MM-DD HH:MM' 字符串吸附到用户桶宽起点。"""
        if not raw:
            return ""
        text = raw.replace("T", " ")
        try:
            if len(text) <= 13:  # 'YYYY-MM-DD HH'
                dt = datetime.strptime(text, "%Y-%m-%d %H")
            else:
                dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return ""
        if bucket_minutes >= 60 and bucket_minutes % 60 == 0:
            hours = bucket_minutes // 60
            snapped = dt.replace(minute=0, second=0, microsecond=0)
            snapped = snapped.replace(hour=(snapped.hour // hours) * hours)
        else:
            snapped = dt.replace(second=0, microsecond=0)
            snapped = snapped.replace(minute=(snapped.minute // bucket_minutes) * bucket_minutes)
        return snapped.strftime("%Y-%m-%d %H:%M")

    async def delete_all(self) -> None:
        client = self._get_client()
        model_cls = await self._ensure_collection()
        await client.drop_collection(model_cls)
        await client.create_collection(model_cls)

    async def delete_before(self, timestamp: str) -> None:
        client = self._get_client()
        model_cls = await self._ensure_collection()
        to_delete: list[str] = []
        async for item in client.search(model_cls, as_model=False):
            row = dict(cast(Mapping[str, object], item))
            if str(row.get("timestamp", "")) < timestamp:
                to_delete.append(str(row.get("id", row.get("_id", ""))))
        for oid in to_delete:
            await client.delete(model_cls, oid)


def get_default_log_store(
    client: ORM_ClientBase,
    model_cls_factory: Callable[[], type[LogRecordModel]],
) -> DefaultORMLogStore:
    """创建基于 ORM 客户端的默认日志存储。"""
    return DefaultORMLogStore(client=client, model_cls_factory=model_cls_factory)



__all__ = ['LogRecordModel', 'get_log_record_model', 'SystemMetricRecord', 'ORMSystemMetricsStore', 'make_orm_system_metrics_store', 'DefaultORMLogStore', 'get_default_log_store']
