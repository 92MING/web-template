from core.server.shared import AppSharedData
from core.utils.concurrent_utils.shared_obj import CrossProcessSharedObject


class WebRTCChatroomSharedData(CrossProcessSharedObject):
    def __init__(self, id: str, /):
        self.room_worker_map: dict[str, int] = {}
        self.last_assigned_worker_pid: int | None = None
        self.active_worker_pids: list[int] = []
        self.active_worker_ports: dict[int, int] = {}

    def register_worker(self, worker_pid: int, msg_port: int | None = None) -> None:
        pid = int(worker_pid)
        if pid > 0 and pid not in self.active_worker_pids:
            self.active_worker_pids.append(pid)
        if pid > 0 and msg_port is not None and int(msg_port) > 0:
            self.active_worker_ports[pid] = int(msg_port)

    def unregister_worker(self, worker_pid: int) -> None:
        pid = int(worker_pid)
        self.active_worker_pids = [item for item in self.active_worker_pids if item != pid]
        self.active_worker_ports.pop(pid, None)
        self.cleanup_worker_rooms(pid)

    def get_active_workers(self) -> list[int]:
        return list(self.active_worker_pids)

    def get_worker_port(self, worker_pid: int) -> int | None:
        return self.active_worker_ports.get(int(worker_pid))

    def update_room_worker(self, room_id: str, worker_pid: int) -> None:
        try:
            AppSharedData.Get().get_worker(worker_pid)
        except Exception:
            pass
        self.room_worker_map[room_id] = worker_pid

    def delete_room_worker(self, room_id: str) -> int | None:
        return self.room_worker_map.pop(room_id, None)

    def get_room_worker(self, room_id: str) -> int | None:
        return self.room_worker_map.get(room_id)

    def cleanup_worker_rooms(self, worker_pid: int) -> int:
        room_ids = [room_id for room_id, pid in self.room_worker_map.items() if pid == worker_pid]
        for room_id in room_ids:
            self.room_worker_map.pop(room_id, None)
        return len(room_ids)

    def get_all_room_info(self) -> list[dict[str, int | str]]:
        infos: list[dict[str, int | str]] = []
        for room_id, worker_id in list(self.room_worker_map.items()):
            infos.append({"id": room_id, "worker": worker_id})
        return infos

    def worker_running_room_count(self, worker_pid: int) -> int:
        count = 0
        for wid in self.room_worker_map.values():
            if wid == worker_pid:
                count += 1
        return count

    def pick_worker(self, worker_pids: list[int], prefer_pid: int | None = None) -> int | None:
        candidates_in_order = list(dict.fromkeys(int(pid) for pid in worker_pids if int(pid) > 0))
        if not candidates_in_order:
            return prefer_pid

        min_count: int | None = None
        least_loaded: list[int] = []
        for pid in candidates_in_order:
            room_count = self.worker_running_room_count(pid)
            if min_count is None or room_count < min_count:
                min_count = room_count
                least_loaded = [pid]
            elif room_count == min_count:
                least_loaded.append(pid)

        if not least_loaded:
            selected = prefer_pid if prefer_pid is not None else candidates_in_order[0]
        elif self.last_assigned_worker_pid is None and prefer_pid in least_loaded:
            selected = int(prefer_pid)
        else:
            start_index = -1
            if self.last_assigned_worker_pid in candidates_in_order:
                start_index = candidates_in_order.index(int(self.last_assigned_worker_pid))
            selected = least_loaded[0]
            for offset in range(1, len(candidates_in_order) + 1):
                candidate = candidates_in_order[(start_index + offset) % len(candidates_in_order)]
                if candidate in least_loaded:
                    selected = candidate
                    break
        self.last_assigned_worker_pid = int(selected)
        return int(selected)

    def pick_least_room_running_worker(self, prefer_pid: int | None = None) -> int | None:
        workers = AppSharedData.Get().get_workers_snapshot()
        if not workers:
            return prefer_pid
        min_count: int | None = None
        candidates: list[int] = []
        for worker in workers:
            pid = int(worker["pid"])
            room_count = self.worker_running_room_count(pid)
            if min_count is None or room_count < min_count:
                min_count = room_count
                candidates = [pid]
            elif room_count == min_count:
                candidates.append(pid)
        if prefer_pid is not None and prefer_pid in candidates:
            return prefer_pid
        return candidates[0] if candidates else prefer_pid


__all__ = ["WebRTCChatroomSharedData"]
