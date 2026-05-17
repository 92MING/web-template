from datetime import datetime, timezone

from core.utils.concurrent_utils.shared_obj import CrossProcessSharedObject


class DockerManagerSharedData(CrossProcessSharedObject):
    def __init__(self, id: str, /):
        self.sudo_password: str | None = None
        self.yacht_port: int | None = None
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

    def get_yacht_port(self) -> int | None:
        return int(self.yacht_port) if self.yacht_port is not None else None

    def set_yacht_port(self, port: int | None) -> None:
        self.yacht_port = int(port) if port is not None else None
        self.updated_at = datetime.now(timezone.utc).isoformat()


__all__ = ["DockerManagerSharedData"]