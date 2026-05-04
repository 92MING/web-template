# -*- coding: utf-8 -*-

import asyncio
from pathlib import Path

import httpx

from core.server.app import create_app
from core.server.data_types.config import Config


async def _get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def _create_isolated_app(extra_app_dir: Path):
    import core.server.app as core_app_module

    core_app_module._app = None
    cfg = Config()
    cfg.server_config.extra_app_paths = [str(extra_app_dir)]
    cfg.server_config.extra_public_paths = []
    return create_app(config=cfg)


def test_nearest_route_error_code_handler_handles_404(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "errors" / "nested").mkdir(parents=True)
    (extra_app_dir / "errors" / "__init__.py").write_text(
        """
from core.server import Route

class ErrorsRoute(Route):
    def on_error_code(self, code, exception, context):
        return {
            "scope": "errors",
            "code": code,
            "path": context.path,
            "route_path": context.route_path,
            "has_traceback": context.traceback is not None,
        }
""",
        encoding="utf-8",
    )
    (extra_app_dir / "errors" / "nested" / "__init__.py").write_text(
        """
from core.server import Route

class NestedErrorsRoute(Route):
    def on_error_code(self, code, exception, context):
        return {"scope": "nested", "code": code, "path": context.path, "route_path": context.route_path}
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)

    parent_response = asyncio.run(_get(app, "/errors/missing"))
    nested_response = asyncio.run(_get(app, "/errors/nested/missing"))

    assert parent_response.status_code == 404
    assert parent_response.json() == {
        "scope": "errors",
        "code": 404,
        "path": "/errors/missing",
        "route_path": "/errors",
        "has_traceback": False,
    }
    assert nested_response.status_code == 404
    assert nested_response.json() == {
        "scope": "nested",
        "code": 404,
        "path": "/errors/nested/missing",
        "route_path": "/errors/nested",
    }


def test_route_on_exception_handles_endpoint_exception(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "errors").mkdir(parents=True)
    (extra_app_dir / "errors" / "boom.py").write_text(
        """
from core.server import Route

class BoomRoute(Route):
    async def get(self):
        raise ValueError("boom")

    def on_exception(self, exception, context):
        return {
            "handled": type(exception).__name__,
            "path": context.path,
            "route_path": context.route_path,
            "has_traceback": context.traceback is not None,
        }
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)
    response = asyncio.run(_get(app, "/errors/boom"))

    assert response.status_code == 500
    assert response.json() == {
        "handled": "ValueError",
        "path": "/errors/boom",
        "route_path": "/errors/boom",
        "has_traceback": True,
    }


def test_on_exception_override_may_skip_on_error_code(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "errors" / "both").mkdir(parents=True)
    (extra_app_dir / "errors" / "both" / "__init__.py").write_text(
        """
from core.server import Route

class BothRoute(Route):
    def on_exception(self, exception, context):
        return {"handler": "on_exception"}

    def on_error_code(self, code, exception, context):
        return {"handler": "on_error_code"}
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)
    response = asyncio.run(_get(app, "/errors/both/missing"))

    assert response.status_code == 404
    assert response.json() == {"handler": "on_exception"}


def test_dynamic_route_error_handler_matches_subpath(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "users" / "_user_id_").mkdir(parents=True)
    (extra_app_dir / "users" / "_user_id_" / "__init__.py").write_text(
        """
from core.server import Route

class UserRoute(Route):
    def on_error_code(self, code, exception, context):
        return {"route_path": context.route_path, "path": context.path}
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)
    response = asyncio.run(_get(app, "/users/42/missing"))

    assert response.status_code == 404
    assert response.json() == {"route_path": "/users/{user_id:path}", "path": "/users/42/missing"}


def test_error_handler_returning_exception_keeps_original_error(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "pass-through").mkdir(parents=True)
    (extra_app_dir / "pass-through" / "__init__.py").write_text(
        """
from core.server import Route

class PassThroughRoute(Route):
    def on_error_code(self, code, exception, context):
        return exception
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)
    response = asyncio.run(_get(app, "/pass-through/missing"))

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_error_handler_can_return_html_response(tmp_path: Path) -> None:
    extra_app_dir = tmp_path / "extra-app"
    (extra_app_dir / "html-errors").mkdir(parents=True)
    (extra_app_dir / "html-errors" / "__init__.py").write_text(
        """
from core.server import Route
from starlette.responses import HTMLResponse

class HtmlErrorsRoute(Route):
    def on_error_code(self, code, exception, context):
        return HTMLResponse(f"<h1>{code}</h1><p>{context.path}</p>", status_code=code)
""",
        encoding="utf-8",
    )

    app = _create_isolated_app(extra_app_dir)
    response = asyncio.run(_get(app, "/html-errors/missing"))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>404</h1>" in response.text
    assert "/html-errors/missing" in response.text