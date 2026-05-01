from urllib.parse import quote_plus
from typing_extensions import Unpack

from .client_base import PostgreSQLORMClientInitParams
from .sql_client import SQL_ORM_Client

class PostgreSQLORMClient(SQL_ORM_Client, type="postgresql"):
    def __init__(self, **params: Unpack[PostgreSQLORMClientInitParams]) -> None:
        url = params.get("url")
        if not url:
            url = self.build_url(
                host=str(params.get("host", "127.0.0.1")),
                port=int(params.get("port", 5432)),
                username=str(params.get("username", "postgres")),
                password=params.get("password"),
                database=str(params.get("database", "postgres")),
            )
        params["url"] = url
        super().__init__(**params)

    @staticmethod
    def build_url(*, host: str, port: int = 5432, username: str = "postgres", password: str | None = None, database: str = "postgres") -> str:
        user_part = quote_plus(username)
        password_part = "" if password in (None, "") else f":{quote_plus(str(password))}"
        database_part = quote_plus(database)
        return f"postgresql+asyncpg://{user_part}{password_part}@{host}:{int(port)}/{database_part}"



__all__ = ['PostgreSQLORMClient']
