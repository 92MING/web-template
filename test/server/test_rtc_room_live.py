# -*- coding: utf-8 -*-
"""Live integration tests for RTC room multi-worker behavior and media flow.

Starts the real server via ``python scripts/run.py`` with 2 workers and an
explicit ``webrtc-chatroom`` plugin config, then uses aiortc peers to validate:

- room allocation across workers
- join affinity to the room-owning worker
- real audio/video frame delivery after renegotiation
- creator-leave auto close
- room-worker mapping cleanup after the owning worker exits
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx
from av import AudioFrame, VideoFrame
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCDataChannel, RTCSessionDescription


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from _test_helpers import _load_webrtc_chatroom_module
from core.server.security.jwt import ensure_jwt_keys_or_warn

_chatroom_module = _load_webrtc_chatroom_module()
create_room_invite_token = _chatroom_module.create_room_invite_token
create_room_token = _chatroom_module.create_room_token


SERVER_PORT = 0
BASE_URL = "http://127.0.0.1:0"
RUN_PY = PROJECT_ROOT / "scripts" / "run.py"
STOP_PY = PROJECT_ROOT / "scripts" / "stop.py"
ADMIN_PW = "rtc-room-live-secret"
REQUEST_TIMEOUT = 45.0


def _set_server_port(port: int) -> None:
    global SERVER_PORT, BASE_URL
    SERVER_PORT = int(port)
    BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


def _choose_server_port() -> int:
    for port in range(19041, 19141):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(port)
    raise RuntimeError("No free local port available for RTC live tests.")


def _server_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ADMIN_PW"] = ADMIN_PW
    env["__SKIP_AI_PRELOAD__"] = "1"
    return env


def _write_chatroom_plugin_config() -> str:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as file:
        json.dump({"enabled": True}, file, ensure_ascii=False)
        file.write("\n")
        return file.name


def _wait_for_server_ready(timeout: float = 90.0) -> None:
    print(f"[rtc-live] waiting for server ready on {BASE_URL}", flush=True)
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(f"{BASE_URL}/_internal/admin/session", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    print("[rtc-live] server ready", flush=True)
                    return
        except Exception:
            pass
        if attempt % 10 == 0:
            elapsed = int(timeout - max(0.0, deadline - time.time()))
            print(f"[rtc-live] still waiting for server ready... {elapsed}s", flush=True)
        time.sleep(0.5)


def _list_listening_pids(port: int) -> set[int]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    pids: set[int] = set()
    local_suffix = f":{int(port)}"
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local_addr = parts[1]
        state = parts[3].upper()
        pid_text = parts[4]
        if state != "LISTENING" or not local_addr.endswith(local_suffix):
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return pids


def _force_kill_server_by_port(port: int) -> set[int]:
    pids = _list_listening_pids(port)
    for pid in sorted(pids):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    return pids

def _pid_is_alive(pid: int) -> bool:
    try:
        import psutil

        process = psutil.Process(int(pid))
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except Exception:
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False


def _stop_server(port: int) -> None:
    try:
        result = subprocess.run(
            [sys.executable, str(STOP_PY), "-p", str(port), "-y"],
            cwd=str(PROJECT_ROOT),
            env=_server_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        if result.returncode == 0:
            return
    except subprocess.TimeoutExpired:
        print(f"[rtc-live] stop.py timed out on port {port}, forcing process cleanup", flush=True)

    killed_pids = _force_kill_server_by_port(port)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        remaining_pids = _list_listening_pids(port)
        if not remaining_pids:
            return
        time.sleep(0.5)

    remaining_pids = _list_listening_pids(port)
    raise RuntimeError(
        f"Failed to stop live RTC server on port {port}; killed={sorted(killed_pids)} remaining={sorted(remaining_pids)}"
    )


def _login_admin() -> str:
    print("[rtc-live] logging in admin", flush=True)
    login_req = urllib.request.Request(
        f"{BASE_URL}/_internal/admin/login",
        data=json.dumps({"password": ADMIN_PW, "next_path": "/_internal/admin/panel"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(login_req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("[rtc-live] admin login ok", flush=True)
        return str(data["api_key"])


class SyntheticAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, *, sample_rate: int = 48000, samples_per_frame: int = 960):
        super().__init__()
        self._sample_rate = sample_rate
        self._samples_per_frame = samples_per_frame
        self._pts = 0
        self._polarity = 1

    async def recv(self) -> AudioFrame:
        await asyncio.sleep(self._samples_per_frame / self._sample_rate)
        frame = AudioFrame(format="s16", layout="mono", samples=self._samples_per_frame)
        frame.sample_rate = self._sample_rate
        amplitude = 1200 * self._polarity
        raw = bytearray()
        for _ in range(self._samples_per_frame):
            raw.extend(int(amplitude).to_bytes(2, "little", signed=True))
        frame.planes[0].update(bytes(raw))
        frame.pts = self._pts
        frame.time_base = Fraction(1, self._sample_rate)
        self._pts += self._samples_per_frame
        self._polarity *= -1
        return frame


class SyntheticVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, *, width: int = 160, height: int = 120, fps: int = 12):
        super().__init__()
        self._width = width
        self._height = height
        self._fps = fps
        self._pts = 0
        self._luma = 32

    async def recv(self) -> VideoFrame:
        await asyncio.sleep(1 / self._fps)
        frame = VideoFrame(width=self._width, height=self._height, format="yuv420p")
        frame.planes[0].update(bytes([self._luma]) * frame.planes[0].buffer_size)
        frame.planes[1].update(bytes([128]) * frame.planes[1].buffer_size)
        frame.planes[2].update(bytes([128]) * frame.planes[2].buffer_size)
        frame.pts = self._pts
        frame.time_base = Fraction(1, self._fps)
        self._pts += 1
        self._luma = 32 + ((self._luma + 17) % 160)
        return frame


class LiveRtcPeer:
    def __init__(self, name: str, *, want_audio: bool = True, want_video: bool = True):
        self.name = name
        self.want_audio = want_audio
        self.want_video = want_video
        self.pc = RTCPeerConnection()
        self.negotiation_channel = self.pc.createDataChannel("__negotiation__")
        self.server_channel: RTCDataChannel | None = None
        self.server_channel_open = asyncio.Event()
        self.connection_ready = asyncio.Event()
        self.remote_frame_events = {
            "audio": asyncio.Event(),
            "video": asyncio.Event(),
        }
        self.remote_frame_counts = {
            "audio": 0,
            "video": 0,
        }
        self.room_id: str | None = None
        self.room_password: str | None = None
        self.candidate_id: str | None = None
        self.room_worker: int | None = None
        self._local_tracks: list[MediaStreamTrack] = []
        self._consumer_tasks: list[asyncio.Task[None]] = []
        self._closed = False

        if self.want_audio:
            track = SyntheticAudioTrack()
            self._local_tracks.append(track)
            self.pc.addTrack(track)
        if self.want_video:
            track = SyntheticVideoTrack()
            self._local_tracks.append(track)
            self.pc.addTrack(track)

        self.negotiation_channel.on("open")(lambda: None)
        self.negotiation_channel.on("close")(lambda: None)
        self.pc.on("datachannel")(self._on_datachannel)
        self.pc.on("connectionstatechange")(self._on_connectionstatechange)
        self.pc.on("track")(self._on_track)

    async def _on_connectionstatechange(self) -> None:
        print(f"[rtc-live] {self.name}: connection state -> {self.pc.connectionState}", flush=True)
        if self.pc.connectionState in {"connected", "completed"}:
            self.connection_ready.set()

    def _on_datachannel(self, channel: RTCDataChannel) -> None:
        print(f"[rtc-live] {self.name}: received datachannel {channel.label}", flush=True)
        self.server_channel = channel

        @channel.on("open")
        def _on_open() -> None:
            print(f"[rtc-live] {self.name}: server datachannel open", flush=True)
            self.server_channel_open.set()

        @channel.on("message")
        def _on_message(message: Any) -> None:
            asyncio.create_task(self._handle_server_message(message))

    def _on_track(self, track: MediaStreamTrack) -> None:
        print(f"[rtc-live] {self.name}: remote track {track.kind}", flush=True)
        self._consumer_tasks.append(asyncio.create_task(self._consume_remote_track(track)))

    async def _consume_remote_track(self, track: MediaStreamTrack) -> None:
        kind = str(track.kind)
        while not self._closed:
            try:
                await asyncio.wait_for(track.recv(), timeout=10.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                return
            self.remote_frame_counts[kind] = int(self.remote_frame_counts.get(kind, 0)) + 1
            if kind in self.remote_frame_events:
                self.remote_frame_events[kind].set()
                return

    async def _handle_server_message(self, message: Any) -> None:
        raw: str
        if isinstance(message, str):
            raw = message
        elif isinstance(message, bytes):
            raw = message.decode("utf-8", errors="ignore")
        else:
            raw = str(message)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        msg_type = str(payload.get("type") or "")
        print(f"[rtc-live] {self.name}: server message {msg_type}", flush=True)
        if msg_type == "renegotiate_needed":
            await self._handle_renegotiate_needed(payload)
        elif msg_type == "renegotiate_answer":
            await self._handle_renegotiate_answer(payload)

    async def _handle_renegotiate_needed(self, payload: dict[str, Any]) -> None:
        if self.server_channel is None:
            return
        print(f"[rtc-live] {self.name}: handle renegotiate_needed", flush=True)
        add_transceivers = payload.get("add_transceivers")
        if isinstance(add_transceivers, list):
            for item in add_transceivers:
                kind = str((item or {}).get("kind") or "").strip()
                if kind in {"audio", "video"}:
                    self.pc.addTransceiver(kind, direction="recvonly")
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        self.server_channel.send(json.dumps({"type": "renegotiate_offer", "sdp": self.pc.localDescription.sdp}))

    async def _handle_renegotiate_answer(self, payload: dict[str, Any]) -> None:
        sdp = str(payload.get("sdp") or "").strip()
        if not sdp:
            return
        print(f"[rtc-live] {self.name}: handle renegotiate_answer", flush=True)
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))

    async def _wait_ice_done(self, timeout: float = 8.0) -> None:
        if self.pc.iceGatheringState == "complete":
            return
        loop = asyncio.get_running_loop()
        finished = loop.create_future()

        @self.pc.on("icegatheringstatechange")
        async def _on_gather_state() -> None:
            if self.pc.iceGatheringState == "complete" and not finished.done():
                finished.set_result(None)

        try:
            await asyncio.wait_for(finished, timeout=timeout)
        except asyncio.TimeoutError:
            pass

    @staticmethod
    async def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            trust_env=False,
            timeout=REQUEST_TIMEOUT,
            headers={"Connection": "close"},
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        ) as client:
            response = await client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    async def create_room(self, *, close_room_on_creator_left: bool = True, room_name: str | None = None) -> dict[str, Any]:
        print(f"[rtc-live] {self.name}: create room begin", flush=True)
        try:
            token = create_room_token(
                name=room_name or f"{self.name}-room",
                user_name=self.name,
                close_room_on_creator_left=close_room_on_creator_left,
            )
            print(f"[rtc-live] {self.name}: create token ready", flush=True)
            offer = await self.pc.createOffer()
            print(f"[rtc-live] {self.name}: local offer created", flush=True)
            await self.pc.setLocalDescription(offer)
            print(f"[rtc-live] {self.name}: local description set", flush=True)
            await self._wait_ice_done()
            print(f"[rtc-live] {self.name}: ice gather done", flush=True)
            response = await self._post_json(
                "/rtc_room/create",
                {
                    "token": token,
                    "sdp": self.pc.localDescription.sdp,
                    "type": self.pc.localDescription.type,
                    "name": room_name or f"{self.name}-room",
                },
            )
            print(f"[rtc-live] {self.name}: create API returned", flush=True)
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp=response["sdp"], type=response["type"]))
            print(f"[rtc-live] {self.name}: remote description set", flush=True)
            room_info = response["room_info"]
            candidate_info = response["candidate_info"]
            self.room_id = str(room_info["id"])
            self.room_password = room_info.get("password")
            self.room_worker = int(room_info["worker"])
            self.candidate_id = str(candidate_info["id"])
            print(f"[rtc-live] {self.name}: create room ok room={self.room_id} worker={self.room_worker}", flush=True)
            return response
        except Exception as exc:
            print(f"[rtc-live] {self.name}: create room failed {type(exc).__name__}: {exc}", flush=True)
            raise

    async def join_room(self, *, room_id: str, password: str | None = None) -> dict[str, Any]:
        print(f"[rtc-live] {self.name}: join room begin room={room_id}", flush=True)
        try:
            token = create_room_invite_token(room_id=room_id, password=password, user_name=self.name)
            print(f"[rtc-live] {self.name}: join token ready", flush=True)
            offer = await self.pc.createOffer()
            print(f"[rtc-live] {self.name}: join local offer created", flush=True)
            await self.pc.setLocalDescription(offer)
            print(f"[rtc-live] {self.name}: join local description set", flush=True)
            await self._wait_ice_done()
            print(f"[rtc-live] {self.name}: join ice gather done", flush=True)
            response = await self._post_json(
                "/rtc_room/join",
                {
                    "token": token,
                    "room_id": room_id,
                    "sdp": self.pc.localDescription.sdp,
                    "type": self.pc.localDescription.type,
                },
            )
            print(f"[rtc-live] {self.name}: join API returned", flush=True)
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp=response["sdp"], type=response["type"]))
            print(f"[rtc-live] {self.name}: join remote description set", flush=True)
            room_info = response["room_info"]
            candidate_info = response["candidate_info"]
            self.room_id = str(room_info["id"])
            self.room_password = room_info.get("password")
            self.room_worker = int(room_info["worker"])
            self.candidate_id = str(candidate_info["id"])
            print(f"[rtc-live] {self.name}: join room ok room={self.room_id} worker={self.room_worker}", flush=True)
            return response
        except Exception as exc:
            print(f"[rtc-live] {self.name}: join room failed {type(exc).__name__}: {exc}", flush=True)
            raise

    async def wait_for_server_channel(self, timeout: float = 15.0) -> None:
        print(f"[rtc-live] {self.name}: wait for server channel", flush=True)
        await asyncio.wait_for(self.server_channel_open.wait(), timeout=timeout)
        print(f"[rtc-live] {self.name}: server channel ready", flush=True)

    async def wait_for_connection(self, timeout: float = 15.0) -> None:
        print(f"[rtc-live] {self.name}: wait for connection", flush=True)
        await asyncio.wait_for(self.connection_ready.wait(), timeout=timeout)
        print(f"[rtc-live] {self.name}: connection ready", flush=True)

    async def wait_for_remote_media(self, *, timeout: float = 25.0) -> None:
        print(f"[rtc-live] {self.name}: wait for remote media", flush=True)
        events = []
        if self.want_audio:
            events.append(self.remote_frame_events["audio"].wait())
        if self.want_video:
            events.append(self.remote_frame_events["video"].wait())
        if not events:
            return
        await asyncio.wait_for(asyncio.gather(*events), timeout=timeout)
        print(f"[rtc-live] {self.name}: remote media ready", flush=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._consumer_tasks:
            task.cancel()
        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        if self.server_channel is not None:
            try:
                self.server_channel.close()
            except Exception:
                pass
        try:
            self.negotiation_channel.close()
        except Exception:
            pass
        for track in self._local_tracks:
            try:
                track.stop()
            except Exception:
                pass
        try:
            await asyncio.wait_for(self.pc.close(), timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            pass


class TestRTCRoomLive(unittest.IsolatedAsyncioTestCase):
    _api_key: str = ""
    _plugin_config_path: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_jwt_keys_or_warn(PROJECT_ROOT)
        _set_server_port(_choose_server_port())
        cls._plugin_config_path = _write_chatroom_plugin_config()
        print(f"[rtc-live] class setup: use port {SERVER_PORT}", flush=True)
        result = subprocess.run(
            [
                sys.executable,
                str(RUN_PY),
                "--server-port",
                str(SERVER_PORT),
                "--server-worker",
                "2",
                "--plugin",
                str(PROJECT_ROOT / "plugin" / "webrtc-chatroom"),
                "--plugin-config",
                cls._plugin_config_path,
            ],
            cwd=str(PROJECT_ROOT),
            env=_server_env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or f"run.py exited with {result.returncode}")
        print("[rtc-live] class setup: launched run.py", flush=True)
        _wait_for_server_ready()
        cls._api_key = _login_admin()

    @classmethod
    def tearDownClass(cls) -> None:
        _stop_server(SERVER_PORT)
        if cls._plugin_config_path:
            Path(cls._plugin_config_path).unlink(missing_ok=True)

    async def asyncTearDown(self) -> None:
        await asyncio.sleep(0)

    def _admin_cookies(self) -> dict[str, str]:
        return {"proj_admin_apikey": self._api_key}

    async def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        admin: bool = False,
        expected_status: int = 200,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Any:
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            trust_env=False,
            timeout=timeout,
            headers={"Connection": "close"},
            cookies=self._admin_cookies() if admin else None,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        ) as client:
            response = await client.request(method, path, json=body)
            self.assertEqual(response.status_code, expected_status, response.text)
            if not response.content:
                return None
            content_type = str(response.headers.get("content-type") or "")
            if "application/json" in content_type:
                return response.json()
            return response.text

    async def _eventually(self, predicate, *, timeout: float = 25.0, interval: float = 0.25, label: str = "condition"):
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                result = await predicate()
                if result:
                    return result
            except AssertionError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(interval)
        if last_error is not None:
            raise AssertionError(f"Timed out waiting for {label}: {last_error}") from last_error
        raise AssertionError(f"Timed out waiting for {label}")

    async def _backend_runtime(self) -> dict[str, Any]:
        data = await self._request_json("/_internal/admin/api/backend/runtime", admin=True)
        assert isinstance(data, dict)
        return data

    async def _backend_runtime_with_workers(self, min_workers: int = 2) -> dict[str, Any]:
        async def _predicate() -> dict[str, Any] | None:
            runtime = await self._backend_runtime()
            worker_pids = [int(row["pid"]) for row in runtime.get("workers") or [] if row.get("pid")]
            if len(worker_pids) >= min_workers:
                return runtime
            return None

        return await self._eventually(
            _predicate,
            timeout=30.0,
            interval=0.5,
            label=f"backend runtime with >= {min_workers} workers",
        )

    async def _room_list(self) -> list[dict[str, Any]]:
        data = await self._request_json("/_internal/admin/api/rooms", admin=True)
        assert isinstance(data, dict)
        return list(data.get("items") or [])

    async def _room_detail(self, room_id: str, *, expected_status: int = 200) -> dict[str, Any] | None:
        data = await self._request_json(
            f"/_internal/admin/api/rooms/{room_id}",
            admin=True,
            expected_status=expected_status,
            timeout=5.0,
        )
        return data if isinstance(data, dict) else None

    async def _room_ids(self) -> set[str]:
        return {str(item["id"]) for item in await self._room_list()}

    async def _delete_room(self, room_id: str) -> dict[str, Any]:
        data = await self._request_json(f"/_internal/admin/api/rooms/{room_id}", method="DELETE", admin=True)
        assert isinstance(data, dict)
        return data

    async def _assert_join_404(self, room_id: str) -> None:
        peer = LiveRtcPeer("join-after-close", want_audio=False, want_video=False)
        try:
            with self.assertRaises(httpx.HTTPStatusError) as ctx:
                await peer.join_room(room_id=room_id)
            self.assertEqual(ctx.exception.response.status_code, 404)
        finally:
            await peer.close()

    async def test_multi_worker_room_management_and_affinity(self) -> None:
        print("[rtc-live] test affinity: fetch runtime", flush=True)
        runtime = await self._backend_runtime_with_workers(2)
        worker_pids = [int(row["pid"]) for row in runtime["workers"] if row.get("pid")]
        self.assertGreaterEqual(len(worker_pids), 2, runtime)

        owner_a = LiveRtcPeer("owner-a", want_audio=False, want_video=False)
        owner_b = LiveRtcPeer("owner-b", want_audio=False, want_video=False)
        guest = LiveRtcPeer("guest-c", want_audio=False, want_video=False)
        self.addAsyncCleanup(owner_a.close)
        self.addAsyncCleanup(owner_b.close)
        self.addAsyncCleanup(guest.close)

        print("[rtc-live] test affinity: create two rooms", flush=True)
        create_a = await owner_a.create_room(room_name="room-a")
        create_b = await owner_b.create_room(room_name="room-b")
        room_a = create_a["room_info"]
        room_b = create_b["room_info"]
        self.assertNotEqual(int(room_a["worker"]), int(room_b["worker"]), {"room_a": room_a, "room_b": room_b})

        list_payload = await self._room_list()
        indexed = {str(item["id"]): item for item in list_payload}
        self.assertIn(owner_a.room_id, indexed)
        self.assertIn(owner_b.room_id, indexed)
        self.assertEqual(int(indexed[str(owner_a.room_id)]["worker"]), owner_a.room_worker)
        self.assertEqual(int(indexed[str(owner_b.room_id)]["worker"]), owner_b.room_worker)

        print("[rtc-live] test affinity: join room-a", flush=True)
        join_resp = await guest.join_room(room_id=str(owner_a.room_id), password=owner_a.room_password)
        self.assertEqual(str(join_resp["room_info"]["id"]), owner_a.room_id)
        self.assertEqual(int(join_resp["room_info"]["worker"]), owner_a.room_worker)

        detail = await self._eventually(
            lambda: self._room_detail(str(owner_a.room_id)),
            label="room detail after guest join",
        )
        assert isinstance(detail, dict)
        self.assertEqual(int(detail["worker"]), owner_a.room_worker)
        self.assertEqual(int(detail["candidate_count"]), 2)

        print("[rtc-live] test affinity: delete room-a", flush=True)
        delete_payload = await self._delete_room(str(owner_a.room_id))
        self.assertTrue(delete_payload["ok"])
        await self._eventually(
            lambda: self._room_detail(str(owner_a.room_id), expected_status=404),
            label="room removal after admin delete",
        )
        await self._assert_join_404(str(owner_a.room_id))

    async def test_real_audio_video_flow_between_two_peers(self) -> None:
        print("[rtc-live] test media: create/join peers", flush=True)
        creator = LiveRtcPeer("media-owner", want_audio=True, want_video=True)
        guest = LiveRtcPeer("media-guest", want_audio=True, want_video=True)
        self.addAsyncCleanup(creator.close)
        self.addAsyncCleanup(guest.close)

        await creator.create_room(room_name="media-room")
        await guest.join_room(room_id=str(creator.room_id), password=creator.room_password)

        print("[rtc-live] test media: wait for connection", flush=True)
        await asyncio.gather(
            creator.wait_for_connection(),
            guest.wait_for_connection(),
        )
        print("[rtc-live] test media: wait for media", flush=True)
        await asyncio.gather(
            creator.wait_for_remote_media(timeout=35.0),
            guest.wait_for_remote_media(timeout=35.0),
        )

        self.assertGreaterEqual(creator.remote_frame_counts["audio"], 1)
        self.assertGreaterEqual(creator.remote_frame_counts["video"], 1)
        self.assertGreaterEqual(guest.remote_frame_counts["audio"], 1)
        self.assertGreaterEqual(guest.remote_frame_counts["video"], 1)

        detail = await self._room_detail(str(creator.room_id))
        assert isinstance(detail, dict)
        self.assertEqual(int(detail["candidate_count"]), 2)
        self.assertEqual(int(detail["worker"]), creator.room_worker)

    async def test_creator_leave_and_owner_worker_exit_cleanup(self) -> None:
        print("[rtc-live] test cleanup: creator leave scenario", flush=True)
        creator = LiveRtcPeer("creator-leave", want_audio=False, want_video=False)
        guest = LiveRtcPeer("creator-guest", want_audio=False, want_video=False)
        self.addAsyncCleanup(creator.close)
        self.addAsyncCleanup(guest.close)

        await creator.create_room(close_room_on_creator_left=True, room_name="creator-leave-room")
        await guest.join_room(room_id=str(creator.room_id), password=creator.room_password)
        creator_room_id = str(creator.room_id)

        await self._eventually(
            self._room_has_candidate_count(creator_room_id, 2),
            timeout=25.0,
            interval=0.5,
            label="creator-leave room candidate_count == 2",
        )

        await creator.close()
        await self._eventually(
            lambda: self._room_detail(creator_room_id, expected_status=404),
            timeout=25.0,
            label="room close after creator leaves",
        )
        await self._assert_join_404(creator_room_id)

        print("[rtc-live] test cleanup: kill owner worker scenario", flush=True)
        owner = LiveRtcPeer("worker-owner", want_audio=False, want_video=False)
        self.addAsyncCleanup(owner.close)
        await owner.create_room(close_room_on_creator_left=False, room_name="worker-death-room")
        dead_room_id = str(owner.room_id)
        owner_worker = int(owner.room_worker or 0)
        self.assertGreater(owner_worker, 0)

        print(f"[rtc-live] test cleanup: killing worker {owner_worker}", flush=True)
        os.kill(owner_worker, signal.SIGTERM)

        await self._eventually(
            self._owner_worker_replaced(owner_worker),
            timeout=45.0,
            interval=0.5,
            label=f"worker {owner_worker} to exit and be replaced",
        )
        await self._eventually(
            lambda: self._room_detail(dead_room_id, expected_status=404),
            timeout=25.0,
            label="room mapping cleanup after owner worker exit",
        )
        await self._eventually(
            self._room_absent(dead_room_id),
            timeout=25.0,
            label="room removed from admin list after owner worker exit",
        )
        await self._assert_join_404(dead_room_id)

    def _owner_worker_replaced(self, old_pid: int):
        async def _predicate() -> bool:
            runtime = await self._backend_runtime()
            worker_pids = [int(row["pid"]) for row in runtime["workers"] if row.get("pid")]
            replacement_pids = [pid for pid in worker_pids if pid != old_pid]
            return not _pid_is_alive(old_pid) and len(replacement_pids) >= 2

        return _predicate

    def _room_absent(self, room_id: str):
        async def _predicate() -> bool:
            return room_id not in await self._room_ids()

        return _predicate

    def _room_has_candidate_count(self, room_id: str, expected_count: int):
        async def _predicate() -> bool:
            detail = await self._room_detail(room_id)
            if not isinstance(detail, dict):
                return False
            return int(detail.get("candidate_count") or 0) == int(expected_count)

        return _predicate
