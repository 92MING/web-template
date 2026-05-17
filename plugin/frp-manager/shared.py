from datetime import datetime, timezone

from core.utils.concurrent_utils.shared_obj import CrossProcessSharedObject


class FrpManagerSharedData(CrossProcessSharedObject):
    def __init__(self, id: str, /):
        self.frps_pid: int | None = None
        self.frpc_pid: int | None = None
        self.frps_ui_port: int | None = None
        self.frpc_ui_port: int | None = None
        self.installed_release_tag: str | None = None
        self.updated_at: str | None = None

    def _touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_frps_pid(self) -> int | None:
        return int(self.frps_pid) if self.frps_pid is not None else None

    def set_frps_pid(self, pid: int | None) -> None:
        self.frps_pid = int(pid) if pid is not None else None
        self._touch()

    def get_frpc_pid(self) -> int | None:
        return int(self.frpc_pid) if self.frpc_pid is not None else None

    def set_frpc_pid(self, pid: int | None) -> None:
        self.frpc_pid = int(pid) if pid is not None else None
        self._touch()

    def get_frps_ui_port(self) -> int | None:
        return int(self.frps_ui_port) if self.frps_ui_port is not None else None

    def set_frps_ui_port(self, port: int | None) -> None:
        self.frps_ui_port = int(port) if port is not None else None
        self._touch()

    def get_frpc_ui_port(self) -> int | None:
        return int(self.frpc_ui_port) if self.frpc_ui_port is not None else None

    def set_frpc_ui_port(self, port: int | None) -> None:
        self.frpc_ui_port = int(port) if port is not None else None
        self._touch()

    def get_installed_release_tag(self) -> str | None:
        return str(self.installed_release_tag) if self.installed_release_tag else None

    def set_installed_release_tag(self, tag: str | None) -> None:
        self.installed_release_tag = str(tag) if tag else None
        self._touch()


__all__ = ["FrpManagerSharedData"]