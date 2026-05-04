# -*- coding: utf-8 -*-

from pathlib import Path
import asyncio

import httpx

from core.server.app import create_app
from core.server.data_types.config import Config


async def _get(
    app,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers)


def _create_isolated_app(extra_app_dir: Path):
    import core.server.app as core_app_module

    core_app_module._app = None
    cfg = Config()
    cfg.server_config.extra_app_paths = [str(extra_app_dir)]
    cfg.server_config.extra_public_paths = []
    return create_app(config=cfg)


def test_app_index_html_precedes_same_pattern_py_route(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "a" / "b" / "c").mkdir(parents=True)
    (extra_app_dir / "a" / "b" / "c" / "index.html").write_text(
        "<html><body>APP INDEX HTML</body></html>",
        encoding="utf-8",
    )
    (extra_app_dir / "a" / "b" / "c.py").write_text(
        """
from core.server import Route

class CRoute(Route):
    async def get(self):
        return {"source": "c.py"}
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)
    response = asyncio.run(_get(app, "/a/b/c"))

    assert response.status_code == 200
    assert "APP INDEX HTML" in response.text
    assert "c.py" not in response.text


def test_parent_route_protects_static_html_and_child_index_overrides(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "secure" / "page").mkdir(parents=True)
    (extra_app_dir / "secure" / "public").mkdir(parents=True)
    (extra_app_dir / "secure" / "public" / "deeper").mkdir(parents=True)
    (extra_app_dir / "secure" / "__init__.py").write_text(
        """
from core.server import Route

class SecureRoute(Route):
    ApikeyProtected = True
""",
        encoding="utf-8",
    )
    (extra_app_dir / "secure" / "page" / "index.html").write_text(
        "<html><body>PROTECTED PAGE</body></html>",
        encoding="utf-8",
    )
    (extra_app_dir / "secure" / "public" / "index.py").write_text(
        """
from core.server import Route

class PublicRoute(Route):
    ApikeyProtected = False
""",
        encoding="utf-8",
    )
    (extra_app_dir / "secure" / "public" / "index.html").write_text(
        "<html><body>PUBLIC PAGE</body></html>",
        encoding="utf-8",
    )
    (extra_app_dir / "secure" / "public" / "deeper" / "index.html").write_text(
        "<html><body>DEEP PUBLIC PAGE</body></html>",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)

    protected_response = asyncio.run(_get(app, "/secure/page"))
    public_response = asyncio.run(_get(app, "/secure/public"))
    deep_public_response = asyncio.run(_get(app, "/secure/public/deeper"))

    assert protected_response.status_code == 401
    assert public_response.status_code == 200
    assert "PUBLIC PAGE" in public_response.text
    assert deep_public_response.status_code == 200
    assert "DEEP PUBLIC PAGE" in deep_public_response.text


def test_parent_route_dependencies_and_allowed_ips_protect_static_html(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "guarded" / "page").mkdir(parents=True)
    (extra_app_dir / "guarded" / "__init__.py").write_text(
        """
from fastapi import Depends, Header, HTTPException
from core.server import Route

async def require_static_guard(x_static_guard: str | None = Header(default=None)) -> None:
    if x_static_guard != "ok":
        raise HTTPException(status_code=403, detail="Missing static guard.")

class GuardedRoute(Route):
    Dependencies = Depends(require_static_guard)
    AllowedIPs = "127.0.0.9"
""",
        encoding="utf-8",
    )
    (extra_app_dir / "guarded" / "page" / "index.html").write_text(
        "<html><body>GUARDED PAGE</body></html>",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)

    missing_header_response = asyncio.run(_get(app, "/guarded/page", client_host="127.0.0.9"))
    wrong_ip_response = asyncio.run(
        _get(app, "/guarded/page", headers={"x-static-guard": "ok"}, client_host="127.0.0.1")
    )
    allowed_response = asyncio.run(
        _get(app, "/guarded/page", headers={"x-static-guard": "ok"}, client_host="127.0.0.9")
    )

    assert missing_header_response.status_code == 403
    assert wrong_ip_response.status_code == 403
    assert allowed_response.status_code == 200
    assert "GUARDED PAGE" in allowed_response.text