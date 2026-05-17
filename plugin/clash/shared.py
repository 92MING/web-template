from datetime import datetime, timezone

from core.utils.concurrent_utils.shared_obj import CrossProcessSharedObject


class ClashSharedData(CrossProcessSharedObject):
    def __init__(self, id: str, /):
        self.sudo_password: str | None = None
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


__all__ = ["ClashSharedData"]