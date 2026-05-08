# -*- coding: utf-8 -*-
"""Live three-node gallery smoke for distributed networking."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GALLERY_RUN = PROJECT_ROOT / "example" / "gallery" / "run.py"
STOP_PY = PROJECT_ROOT / "scripts" / "stop.py"
ADMIN_PW = "distributed-gallery-smoke-secret"
PORTS = {
    "A": 19431,
    "B": 19432,
    "C": 19433,
}


def _server_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ADMIN_PW"] = ADMIN_PW
    env["FRIEND_NODE_CONN_PASS"] = ADMIN_PW
    env["PARENT_CHILD_NODE_CONN_PASS"] = ADMIN_PW
    env["__SKIP_AI_PRELOAD__"] = "1"
    return env


def _base(port: int) -> str:
    return f"http://127.0.0.1:{port}/_internal/admin"


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: dict[str, Any] | bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any, dict[str, str]]:
    data: bytes | None
    req_headers = dict(headers or {})
    if isinstance(body, bytes):
        data = body
    elif body is None:
        data = None
    else:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        _base(port) + path,
        data=data,
        headers=req_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                payload: Any = json.loads(raw.decode("utf-8") or "{}")
            else:
                payload = raw
            return resp.status, payload, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = raw.decode("utf-8", errors="replace")
        return exc.code, payload, dict(exc.headers)


def _wait_ready(port: int, timeout: float = 75.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _, _ = _request(port, "/session", timeout=3.0)
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"gallery server on {port} did not become ready")


def _login(port: int) -> str:
    status, data, _ = _request(
        port,
        "/login",
        method="POST",
        body={"password": ADMIN_PW, "next_path": "/_internal/admin/panel"},
    )
    if status != 200:
        raise AssertionError(f"login failed on {port}: {status} {data}")
    return str(data["api_key"])


def _poll_json(
    port: int,
    path: str,
    *,
    token: str,
    timeout: float = 20.0,
    predicate,
) -> Any:
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        status, data, _ = _request(port, path, token=token, timeout=5.0)
        last = {"status": status, "data": data}
        if predicate(status, data):
            return data
        time.sleep(0.25)
    raise AssertionError(f"condition not met for {path} on {port}: {last}")


def _start_gallery(label: str, port: int) -> subprocess.Popen[bytes]:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        [
            sys.executable,
            str(GALLERY_RUN),
            "--server-port",
            str(port),
            "--server-worker",
            "1",
            "--server-name",
            f"gallery-{label}",
        ],
        cwd=str(PROJECT_ROOT),
        env=_server_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _stop_port(port: int) -> None:
    subprocess.run(
        [sys.executable, str(STOP_PY), "-p", str(port), "-y"],
        cwd=str(PROJECT_ROOT),
        env=_server_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
        check=False,
    )


class TestDistributedGalleryLive(unittest.TestCase):
    processes: list[subprocess.Popen[bytes]] = []
    tokens: dict[str, str] = {}
    self_info: dict[str, dict[str, Any]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        for port in PORTS.values():
            _stop_port(port)
        cls.processes = [_start_gallery(label, port) for label, port in PORTS.items()]
        try:
            for port in PORTS.values():
                _wait_ready(port)
            cls.tokens = {label: _login(port) for label, port in PORTS.items()}
            cls.self_info = {
                label: _request(port, "/api/distributed/self", token=cls.tokens[label])[1]
                for label, port in PORTS.items()
            }
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        for port in PORTS.values():
            try:
                _stop_port(port)
            except Exception:
                pass
        for proc in cls.processes:
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        cls.processes = []

    def _connect(self, source: str, target: str, *, relation: str = "pc") -> dict[str, Any]:
        source_info = self.self_info[source]
        target_port = PORTS[target]
        status, data, _ = _request(
            PORTS[source],
            "/api/distributed/connect-to",
            method="POST",
            token=self.tokens[source],
            body={
                "target_host": "127.0.0.1",
                "target_port": target_port,
                "password": ADMIN_PW,
                "relation": relation,
                "self_host": "127.0.0.1",
                "self_port": PORTS[source],
                "self_gsd_port": source_info["gsd_port"],
                "metadata": {"smoke": "gallery-live"},
            },
        )
        self.assertEqual(status, 200, data)
        self.assertTrue(data["ok"])
        return data

    def test_three_node_connect_forward_gsd_and_control(self) -> None:
        self._connect("A", "B", relation="pc")
        self._connect("B", "C", relation="pc")

        b_id = str(self.self_info["B"]["node_id"])
        c_id = str(self.self_info["C"]["node_id"])

        nodes_a = _poll_json(
            PORTS["A"],
            "/api/distributed/nodes",
            token=self.tokens["A"],
            predicate=lambda status, data: status == 200 and any(row["node_id"] == b_id for row in data),
        )
        self.assertTrue(any(row["node_id"] == b_id and row["relation"] == "pc" for row in nodes_a))

        nodes_b = _poll_json(
            PORTS["B"],
            "/api/distributed/nodes",
            token=self.tokens["B"],
            predicate=lambda status, data: status == 200 and any(row["node_id"] == c_id for row in data),
        )
        self.assertTrue(any(row["node_id"] == c_id and row["relation"] == "pc" for row in nodes_b))

        status, forwarded, headers = _request(
            PORTS["A"],
            "/api/distributed/forward/distributed-probe?value=from-a",
            token=self.tokens["A"],
            headers={"x-distributed-target-nodes": b_id},
        )
        self.assertEqual(status, 200, forwarded)
        self.assertEqual(forwarded["node_id"], b_id)
        self.assertEqual(headers.get("x-distributed-node-id"), b_id)

        stream_req = urllib.request.Request(
            _base(PORTS["A"]) + "/api/distributed/forward/distributed-probe/stream?chunks=3",
            headers={
                "Authorization": f"Bearer {self.tokens['A']}",
                "x-distributed-target-nodes": b_id,
                "x-distributed-stream-output": "1",
            },
            method="GET",
        )
        started = time.perf_counter()
        with urllib.request.urlopen(stream_req, timeout=20) as resp:
            first = resp.read(9)
            first_elapsed = time.perf_counter() - started
            rest = resp.read()
        self.assertLess(first_elapsed, 1.5)
        self.assertIn(b"data: 0", first)
        self.assertIn(b"data: 2", first + rest)

        namespace = "gallery-live-smoke"
        key = f"k-{int(time.time() * 1000)}"
        quoted_ns = urllib.parse.quote(namespace)
        quoted_key = urllib.parse.quote(key)
        status, data, _ = _request(
            PORTS["A"],
            f"/api/distributed/gsd/item?namespace={quoted_ns}&key={quoted_key}",
            method="PUT",
            token=self.tokens["A"],
            body={"value": {"source": "A", "target": "C"}},
        )
        self.assertEqual(status, 200, data)
        item_c = _poll_json(
            PORTS["C"],
            f"/api/distributed/gsd/item?namespace={quoted_ns}&key={quoted_key}",
            token=self.tokens["C"],
            timeout=15.0,
            predicate=lambda status, data: status == 200 and data.get("value", {}).get("source") == "A",
        )
        self.assertEqual(item_c["value"]["target"], "C")

        status, data, _ = _request(
            PORTS["C"],
            f"/api/distributed/gsd/item?namespace={quoted_ns}&key={quoted_key}",
            method="DELETE",
            token=self.tokens["C"],
        )
        self.assertEqual(status, 200, data)
        _poll_json(
            PORTS["A"],
            f"/api/distributed/gsd/item?namespace={quoted_ns}&key={quoted_key}",
            token=self.tokens["A"],
            timeout=15.0,
            predicate=lambda status, data: status == 404,
        )

        status, patched_node, _ = _request(
            PORTS["B"],
            f"/api/distributed/nodes/{urllib.parse.quote(c_id)}",
            method="PATCH",
            token=self.tokens["B"],
            body={"metadata": {"admin_api_key": self.tokens["C"]}},
        )
        self.assertEqual(status, 200, patched_node)

        status, command_result, _ = _request(
            PORTS["B"],
            f"/api/distributed/nodes/{urllib.parse.quote(c_id)}/command",
            method="POST",
            token=self.tokens["B"],
            body={"command": "rename", "args": {"name": "gallery-C-renamed"}},
        )
        self.assertEqual(status, 200, command_result)
        self.assertTrue(command_result["ok"])
        renamed = _poll_json(
            PORTS["C"],
            "/api/distributed/self",
            token=self.tokens["C"],
            predicate=lambda status, data: status == 200 and data.get("name") == "gallery-C-renamed",
        )
        self.assertEqual(renamed["name"], "gallery-C-renamed")


if __name__ == "__main__":
    unittest.main()
