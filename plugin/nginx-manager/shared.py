from datetime import datetime, timezone

from core.utils.concurrent_utils.shared_obj import CrossProcessSharedObject


class NginxManagerSharedData(CrossProcessSharedObject):
    def __init__(self, id: str, /):
        self.sudo_password: str | None = None
        self.ui_http_port: int | None = None
        self.ui_https_port: int | None = None
        self.updated_at: str | None = None

    def has_sudo_password(self) -> bool:
        return bool(self.sudo_password)

    def get_sudo_password(self) -> str | None:
        return self.sudo_password

    def set_sudo_password(self, password: str) -> None:
        self.sudo_password = str(password)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def clear_sudo_password(self) -> None:
        self.sudo_password = None
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_ui_http_port(self) -> int | None:
        return int(self.ui_http_port) if self.ui_http_port is not None else None

    def set_ui_http_port(self, port: int | None) -> None:
        self.ui_http_port = int(port) if port is not None else None
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_ui_https_port(self) -> int | None:
        return int(self.ui_https_port) if self.ui_https_port is not None else None

    def set_ui_https_port(self, port: int | None) -> None:
        self.ui_https_port = int(port) if port is not None else None
        self.updated_at = datetime.now(timezone.utc).isoformat()


__all__ = ["NginxManagerSharedData"]