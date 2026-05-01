"""ORM-backed log handler & log-store protocol"""
import contextvars
import logging
import traceback

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal, Optional, Protocol, TypedDict, overload, runtime_checkable

from ..concurrent_utils.async_helpers import is_async_runner_bootstrapping


_DB_LOG_WRITE_RECURSIVE = contextvars.ContextVar("db_log_write_recursive", default=False)


@contextmanager
def db_log_write_scope():
    """Mark the current *context* as inside a DB log write.

    The flag is checked by :meth:`ORMLogHandler.emit` to prevent
    same-context recursion.  ``run_in_background`` copies the context to
    the pool thread, so the flag propagates automatically.

    Cross-thread recursion (e.g. aiosqlite's internal worker thread) is
    handled separately by silencing the driver logger in
    ``DefaultORMLogStore`` – see ``_silence_driver_loggers``.
    """
    token = _DB_LOG_WRITE_RECURSIVE.set(True)
    try:
        yield
    finally:
        _DB_LOG_WRITE_RECURSIVE.reset(token)

class LogRecord(TypedDict):
    timestamp: str
    level: str
    levelno: int
    name: str
    process: int
    message: str
    exc_info: str | None


LogQueryRows = list[dict[str, Any]]
LogQueryRowsWithTotal = tuple[LogQueryRows, int]

# -- LogStoreProtocol ---------------------------------------------------------
@runtime_checkable
class LogStoreProtocol(Protocol):
    """抽象日志存储协议。

    遵循此协议的任何对象均可作为 :class:`ORMLogHandler` 的后端注入。
    写入方法为同步（fire-and-forget 可接受），查询方法为异步。
    """

    def write(self, record: "LogRecord") -> None:
        """写入一条日志记录（同步，实现中可 fire-and-forget）。"""
        ...

    @overload
    async def query(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        level: Optional[str] = None,
        min_levelno: Optional[int] = None,
        name_filter: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        order: str = "DESC",
        include_total: Literal[False] = False,
    ) -> LogQueryRows:
        ...

    @overload
    async def query(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        level: Optional[str] = None,
        min_levelno: Optional[int] = None,
        name_filter: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        order: str = "DESC",
        include_total: Literal[True],
    ) -> LogQueryRowsWithTotal:
        ...

    async def query(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        level: Optional[str] = None,
        min_levelno: Optional[int] = None,
        name_filter: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        order: str = "DESC",
        include_total: bool = False,
    ) -> LogQueryRows | LogQueryRowsWithTotal:
        """异步查询日志；include_total=True 时返回 (rows, total)。"""
        ...

    async def count(self) -> int:
        """返回当前日志总数。"""
        ...

    async def count_filtered(
        self,
        *,
        level: Optional[str] = None,
        min_levelno: Optional[int] = None,
        name_filter: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> int:
        """返回过滤后的日志总数。"""
        ...

    async def delete_all(self) -> None:
        """删除全部日志记录。"""
        ...

    async def delete_before(self, timestamp: str) -> None:
        """删除指定时间戳之前的日志记录。"""
        ...


# -- ORMLogHandler ------------------------------------------------------------

class ORMLogHandler(logging.Handler):
    """通过 :class:`LogStoreProtocol` 持久化日志的 logging Handler。
    只要传入满足协议的存储对象即可，便于在不同环境下使用不同的存储后端（例如测试环境使用 SQLite，生产环境使用 MongoDB）。
    """

    def __init__(self, store: "LogStoreProtocol", level: int = logging.NOTSET) -> None:
        """
        Args:
            store:  实现 :class:`LogStoreProtocol` 的存储后端实例。
            level:  日志最低输出级别（同标准 logging）。
        """
        super().__init__(level)
        self._store: LogStoreProtocol = store

    def _should_skip_record(self, record: logging.LogRecord) -> bool:
        if is_async_runner_bootstrapping():
            return True
        return _DB_LOG_WRITE_RECURSIVE.get(False)

    def filter(self, record: logging.LogRecord) -> bool:
        """Prevent same-context recursion (ContextVar-based)."""
        if self._should_skip_record(record):
            return False
        return bool(super().filter(record))

    # -- emit -----------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._should_skip_record(record):
                return
            msg = record.getMessage()
            exc_text: Optional[str] = None
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
            ts = datetime.fromtimestamp(record.created).astimezone().strftime("%Y-%m-%d %H:%M:%S")

            log_record: LogRecord = {
                "timestamp": ts,
                "level": record.levelname,
                "levelno": record.levelno,
                "name": record.name,
                "process": record.process or 0,
                "message": msg,
                "exc_info": exc_text,
            }
            with db_log_write_scope():
                self._store.write(log_record)
        except Exception:
            self.handleError(record)

    # -- convenience accessors (delegate to store) ----------------------------

    async def async_query(self, **kwargs: Any) -> LogQueryRows | LogQueryRowsWithTotal:
        """异步查询日志（委托给底层 store）。"""
        return await self._store.query(**kwargs)

    async def async_count(self) -> int:
        """异步获取日志总数。"""
        return await self._store.count()

    async def async_delete_all(self) -> None:
        """异步删除全部日志。"""
        await self._store.delete_all()

    async def async_delete_before(self, timestamp: str) -> None:
        """异步删除指定时间前的日志。"""
        await self._store.delete_before(timestamp)


__all__ = [
    "db_log_write_scope",
    "LogRecord",
    "LogStoreProtocol",
    "ORMLogHandler",
]
