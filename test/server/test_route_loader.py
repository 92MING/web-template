# -*- coding: utf-8 -*-

import sys
import asyncio
import os
from pathlib import Path

import httpx
from fastapi import FastAPI
import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_DIR = _PROJECT_ROOT / "app"
for _path in (str(_PROJECT_ROOT), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.server.route import RouteLoader
from core.server.data_types.apikey import create_apikey, delete_apikey
from core.storage.config import StorageConfig
from _test_helpers import _make_storage_config


def _clear_api_modules() -> None:
    for name in list(sys.modules):
        if name == "api" or name.startswith("api."):
            sys.modules.pop(name, None)


async def _get(app: FastAPI, path: str, *, client_host: str, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers)


def test_route_loader_inherits_package_route_metadata_and_allowed_ips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api_root = tmp_path / "api"
    (api_root / "a" / "nested").mkdir(parents=True)
    (api_root / "__init__.py").write_text(
        """
from core.server import Route

class RootRoute(Route):
    Tags = ["root"]
    AllowedIPs = ["172.16.*"]

    async def get(self):
        return {"route": "root"}
""",
        encoding="utf-8",
    )
    (api_root / "a" / "__init__.py").write_text(
        """
from fastapi import Depends, Header
from core.server import Route

async def require_parent_marker(x_parent: str = Header(...)):
    return None

class ARoute(Route):
    Tags = ["parent"]
    Dependencies = Depends(require_parent_marker)
    AllowedIPs = "127.0.*"

    async def get(self):
        return {"route": "a"}
""",
        encoding="utf-8",
    )
    (api_root / "a" / "b.py").write_text(
        """
from core.server import Route

class BRoute(Route):
    Tags = "child"
    AllowedIPs = ["10.0.*"]

    async def get(self):
        return {"route": "b"}

    async def get_all(self):
        return {"route": "b-all"}
""",
        encoding="utf-8",
    )
    (api_root / "a" / "_item_id_.py").write_text(
        """
from core.server import Route

class ItemRoute(Route):
    async def get(self, item_id: str):
        return {"item_id": item_id}
""",
        encoding="utf-8",
    )
    (api_root / "a" / "nested" / "c.py").write_text(
        """
from core.server import Route

class CRoute(Route):
    async def get(self):
        return {"route": "c"}
""",
        encoding="utf-8",
    )

    _clear_api_modules()
    monkeypatch.syspath_prepend(str(tmp_path))
    app = FastAPI()
    RouteLoader(tmp_path, app).load_all()

    async def _run_checks() -> None:
        root_response = await _get(app, "/api", client_host="172.16.0.1", headers={"x-parent": "1"})
        assert root_response.status_code == 200
        assert root_response.json() == {"route": "root"}

        parent_response = await _get(app, "/api/a", client_host="127.0.0.9", headers={"x-parent": "1"})
        assert parent_response.status_code == 200
        assert parent_response.json() == {"route": "a"}

        inherited_response = await _get(app, "/api/a/b", client_host="127.0.0.9", headers={"x-parent": "1"})
        assert inherited_response.status_code == 200
        assert inherited_response.json() == {"route": "b"}

        suffix_response = await _get(app, "/api/a/b/all", client_host="127.0.0.9", headers={"x-parent": "1"})
        assert suffix_response.status_code == 200
        assert suffix_response.json() == {"route": "b-all"}

        param_response = await _get(app, "/api/a/example-item", client_host="127.0.0.9", headers={"x-parent": "1"})
        assert param_response.status_code == 200
        assert param_response.json() == {"item_id": "example-item"}

        appended_ip_response = await _get(app, "/api/a/b", client_host="10.0.0.5", headers={"x-parent": "1"})
        assert appended_ip_response.status_code == 200

        root_ip_response = await _get(app, "/api/a/b", client_host="172.16.0.5", headers={"x-parent": "1"})
        assert root_ip_response.status_code == 200

        missing_dependency_response = await _get(app, "/api/a/b", client_host="127.0.0.9")
        assert missing_dependency_response.status_code == 422

        denied_response = await _get(app, "/api/a/b", client_host="192.168.0.5", headers={"x-parent": "1"})
        assert denied_response.status_code == 403

        nested_response = await _get(app, "/api/a/nested/c", client_host="127.0.0.9", headers={"x-parent": "1"})
        assert nested_response.status_code == 200

    asyncio.run(_run_checks())

    schema = app.openapi()
    assert schema["paths"]["/api/a/b"]["get"]["tags"] == ["root", "parent", "child"]


def test_route_loader_apikey_protected_is_inherited_and_checks_route_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    previous_storage_config = StorageConfig.__Instance__
    previous_storage_env = os.environ.get("__STORAGE_CONFIG__")
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    storage_config = _make_storage_config(str(storage_dir))
    StorageConfig.SetGlobal(storage_config)

    api_root = tmp_path / "api"
    (api_root / "a").mkdir(parents=True)
    (api_root / "__init__.py").write_text(
        """
from core.server import Route

class RootRoute(Route):
    ApikeyProtected = True

    async def get(self):
        return {"route": "root"}
""",
        encoding="utf-8",
    )
    (api_root / "a" / "b.py").write_text(
        """
from fastapi import Request
from core.server import Route

class BRoute(Route):
    async def get(self, request: Request):
        return {"route": "b", "apikey": getattr(request, "apikey", None)}
""",
        encoding="utf-8",
    )
    (api_root / "a" / "public.py").write_text(
        """
from core.server import Route

class PublicRoute(Route):
    ApikeyProtected = False

    async def get(self):
        return {"route": "public"}
""",
        encoding="utf-8",
    )

    _clear_api_modules()
    monkeypatch.syspath_prepend(str(tmp_path))
    app = FastAPI()
    RouteLoader(tmp_path, app).load_all()

    async def _run_checks() -> None:
        allowed_key = await create_apikey(
            key=f"proj_route_loader_allowed_{id(app)}",
            whitelist_routes=["/api/a/b"],
            blacklist_routes=[],
        )
        other_key = await create_apikey(
            key=f"proj_route_loader_other_{id(app)}",
            whitelist_routes=["/api/other/*"],
            blacklist_routes=[],
        )
        try:
            missing_response = await _get(app, "/api/a/b", client_host="127.0.0.1")
            assert missing_response.status_code == 401

            invalid_response = await _get(
                app,
                "/api/a/b",
                client_host="127.0.0.1",
                headers={"x-api-key": "missing"},
            )
            assert invalid_response.status_code == 401

            allowed_response = await _get(
                app,
                "/api/a/b",
                client_host="127.0.0.1",
                headers={"x-api-key": allowed_key.key},
            )
            assert allowed_response.status_code == 200
            assert allowed_response.json() == {"route": "b", "apikey": allowed_key.key}

            bearer_response = await _get(
                app,
                "/api/a/b",
                client_host="127.0.0.1",
                headers={"authorization": f"Bearer {allowed_key.key}"},
            )
            assert bearer_response.status_code == 200
            assert bearer_response.json() == {"route": "b", "apikey": allowed_key.key}

            cookie_response = await _get(
                app,
                "/api/a/b",
                client_host="127.0.0.1",
                headers={"cookie": f"x-api-key={allowed_key.key}"},
            )
            assert cookie_response.status_code == 200
            assert cookie_response.json() == {"route": "b", "apikey": allowed_key.key}

            denied_response = await _get(
                app,
                "/api/a/b",
                client_host="127.0.0.1",
                headers={"x-api-key": other_key.key},
            )
            assert denied_response.status_code == 403

            public_response = await _get(app, "/api/a/public", client_host="127.0.0.1")
            assert public_response.status_code == 200
            assert public_response.json() == {"route": "public"}
        finally:
            await delete_apikey(str(getattr(allowed_key, "id", "") or ""))
            await delete_apikey(str(getattr(other_key, "id", "") or ""))

    try:
        asyncio.run(_run_checks())
    finally:
        for attr in ("kv", "orm", "vector", "object"):
            section = getattr(storage_config, attr, None)
            if section is None:
                continue
            for client in section._client_singletons.values():
                stop = getattr(client, "stop", None) or getattr(client, "close", None)
                if callable(stop):
                    stop()
            section._client_singletons.clear()
        if previous_storage_config is not None:
            StorageConfig.SetGlobal(previous_storage_config)
        else:
            StorageConfig.__Instance__ = None
            if previous_storage_env is None:
                os.environ.pop("__STORAGE_CONFIG__", None)
            else:
                os.environ["__STORAGE_CONFIG__"] = previous_storage_env
