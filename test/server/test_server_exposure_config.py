# -*- coding: utf-8 -*-

import sys
from pathlib import Path

from fastapi import FastAPI

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_DIR = _PROJECT_ROOT / "app"
for _path in (str(_PROJECT_ROOT), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.server.data_types.config import Config, ServerConfig
from core.server.routes.ai_services.api import register_ai_service_routes


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_ai_service_routes_default_to_admin_prefix_only() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(expose_ai_service=False, expose_internal_prefix=True)))
    app = FastAPI()
    register_ai_service_routes(app)
    paths = _route_paths(app)
    assert "/_internal/ai/services" in paths
    assert "/ai/services" not in paths


def test_ai_service_public_alias_when_exposed() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(expose_ai_service=True, expose_internal_prefix=True)))
    app = FastAPI()
    register_ai_service_routes(app)
    paths = _route_paths(app)
    assert "/_internal/ai/services" in paths
    assert "/ai/services" not in paths
    assert "/_internal/ai/complete" in paths
    assert "/ai/complete" in paths


def test_internal_path_allowed_ip_normalization() -> None:
    cfg = ServerConfig(internal_path_allowed_ip=["localhost", "10.0.*"])
    assert cfg.get_internal_path_allowed_ip_patterns() == ["127.0.0.1", "::1", "localhost", "10.0.*"]
    assert ServerConfig(internal_path_allowed_ip="all").get_internal_path_allowed_ip_patterns() is None


def test_internal_path_defaults_to_internal_prefix() -> None:
    cfg = ServerConfig()
    assert cfg.internal_path_prefix == "/_internal"
    assert cfg.get_internal_path("ai/services") == "/_internal/ai/services"
    assert cfg.get_internal_admin_path("api/rooms") == "/_internal/admin/api/rooms"


def test_internal_path_does_not_guess_admin_or_ai() -> None:
    cfg = ServerConfig(internal_path_prefix="")
    assert cfg.internal_path_prefix == "/_internal"
    assert cfg.is_internal_path("/_internal/admin") is True
    assert cfg.is_internal_path("/_internal/ai/services") is True
    assert cfg.is_internal_path("/admin") is False
    assert cfg.is_internal_path("/admin/api/rooms") is False
    assert cfg.is_internal_path("/ai") is False
    assert cfg.is_internal_path("/ai/complete") is False


def test_current_config_names_work() -> None:
    cfg = ServerConfig.model_validate({
        "expose_ai_service": True,
        "internal_path_allowed_ip": "10.1.*",
    })
    assert cfg.is_ai_service_exposed() is True
    assert cfg.get_internal_path_allowed_ip_patterns() == ["10.1.*"]
