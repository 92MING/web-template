import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_DIR = _PROJECT_ROOT / "app"
for _path in (str(_PROJECT_ROOT), str(_APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.server.data_types.config import Config, ServerConfig
from core.server.routes.ai_services import api as ai_api
from core.server.routes.ai_services.api import register_ai_service_routes


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _api_route(app: FastAPI, path: str, method: str = "POST") -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method.upper() in route.methods:
            return route
    raise AssertionError(f"route not found: {method} {path}")


def _has_exposed_ai_apikey_dependency(route: APIRoute) -> bool:
    return any(
        dependency.call is ai_api._require_exposed_ai_service_apikey
        for dependency in route.dependant.dependencies
    )


def test_ai_service_routes_default_to_admin_prefix_only() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(expose_ai_service=False, expose_internal_prefix=True)))
    app = FastAPI()
    register_ai_service_routes(app)
    paths = _route_paths(app)
    assert "/_internal/ai/services" in paths
    assert "/ai/services" not in paths
    assert "/_internal/ai/completion/service/{service_key}/complete" in paths
    assert "/_internal/ai/completion/service/default" in paths
    assert "/_internal/ai/completion/service" in paths
    assert "/_internal/ai/completion/service/{service_key}/translate" in paths
    assert "/ai/completion/service/{service_key}/complete" not in paths
    assert "/ai/completion/service/default" not in paths
    assert "/ai/completion/service" not in paths
    assert "/ai/completion/service/{service_key}/translate" not in paths


def test_ai_service_public_alias_when_exposed() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(expose_ai_service=True, expose_internal_prefix=True)))
    app = FastAPI()
    register_ai_service_routes(app)
    paths = _route_paths(app)
    assert "/_internal/ai/services" in paths
    assert "/ai/services" not in paths
    assert "/_internal/ai/completion/service/{service_key}/complete" in paths
    assert "/ai/completion/service/{service_key}/complete" in paths
    assert "/_internal/ai/completion/service/default" in paths
    assert "/ai/completion/service/default" in paths
    assert "/_internal/ai/completion/service" in paths
    assert "/ai/completion/service" in paths
    assert "/_internal/ai/completion/service/{service_key}/translate" in paths
    assert "/ai/completion/service/{service_key}/translate" in paths


def test_ai_service_public_alias_is_apikey_protected() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(expose_ai_service=True, expose_internal_prefix=True)))
    app = FastAPI()
    register_ai_service_routes(app)

    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/ai/completion/service")) is True
    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/_internal/ai/completion/service")) is False
    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/ai/completion/service/{service_key}/translate")) is True
    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/_internal/ai/completion/service/{service_key}/translate")) is False

    with TestClient(app) as client:
        response = client.post("/ai/completion/service", json={
            "messages": [{"role": "user", "content": "hi"}],
        })

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


def test_compatible_ai_service_routes_can_be_exposed_alone() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(
        expose_ai_service=False,
        expose_internal_prefix=False,
        expose_compatible_ai_services=True,
    )))
    app = FastAPI()
    register_ai_service_routes(app)
    paths = _route_paths(app)
    for kind in ("completion", "embedding", "s2t", "t2s", "t2img"):
        assert f"/ai/{kind}/service/{{service_key}}/openai" in paths
        assert f"/ai/{kind}/service/{{service_key}}/openai/{{path:path}}" in paths
        assert f"/ai/{kind}/client/{{client_key}}/openai" in paths
        assert f"/ai/{kind}/client/{{client_key}}/openai/{{path:path}}" in paths
    assert "/ai/completion/service/{service_key}/anthropic" in paths
    assert "/ai/completion/service/{service_key}/anthropic/{path:path}" in paths
    assert "/ai/completion/client/{client_key}/anthropic" in paths
    assert "/ai/completion/client/{client_key}/anthropic/{path:path}" in paths
    old_segment = "openai" + "-liked"
    assert all(old_segment not in path for path in paths)
    old_service_prefix = "/ai/" + "service/"
    old_client_prefix = "/ai/" + "client/"
    assert all(not path.startswith(old_service_prefix) for path in paths)
    assert all(not path.startswith(old_client_prefix) for path in paths)
    assert "/ai/services" not in paths
    assert "/_internal/ai/services" not in paths


def test_compatible_ai_service_routes_are_apikey_protected() -> None:
    Config.SetConfig(Config(server_config=ServerConfig(
        expose_ai_service=False,
        expose_internal_prefix=False,
        expose_compatible_ai_services=True,
    )))
    app = FastAPI()
    register_ai_service_routes(app)

    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/ai/completion/service/{service_key}/openai/{path:path}")) is True
    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/ai/completion/client/{client_key}/openai/{path:path}")) is True
    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/ai/completion/service/{service_key}/anthropic/{path:path}")) is True
    assert _has_exposed_ai_apikey_dependency(_api_route(app, "/ai/completion/client/{client_key}/anthropic/{path:path}")) is True

    with TestClient(app) as client:
        response = client.post("/ai/completion/service/default/openai/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


def test_dashboard_mode_defaults_ai_service_exposure(monkeypatch) -> None:
    monkeypatch.setenv("__DASHBOARD_MODE__", "1")
    monkeypatch.delenv("EXPOSE_AI_SERVICE", raising=False)
    monkeypatch.delenv("EXPOSE_COMPATIBLE_AI_SERVICES", raising=False)

    cfg = ServerConfig()

    assert cfg.is_ai_service_exposed() is True
    assert cfg.is_compatible_ai_services_exposed() is True


def test_dashboard_mode_keeps_explicit_ai_service_exposure_config_false(monkeypatch) -> None:
    monkeypatch.setenv("__DASHBOARD_MODE__", "1")
    monkeypatch.delenv("EXPOSE_AI_SERVICE", raising=False)
    monkeypatch.delenv("EXPOSE_COMPATIBLE_AI_SERVICES", raising=False)

    cfg = ServerConfig.model_validate({
        "expose_ai_service": False,
        "expose_compatible_ai_services": False,
    })

    assert cfg.is_ai_service_exposed() is False
    assert cfg.is_compatible_ai_services_exposed() is False


def test_internal_path_allowed_ip_normalization() -> None:
    cfg = ServerConfig(internal_path_allowed_ip=["localhost", "10.0.*"])
    assert cfg.get_internal_path_allowed_ip_patterns() == ["127.0.0.1", "::1", "localhost", "10.0.*"]
    assert ServerConfig(internal_path_allowed_ip="all").get_internal_path_allowed_ip_patterns() is None


def test_extra_paths_support_env(monkeypatch) -> None:
    monkeypatch.setenv("EXTRA_APP_PATHS", "C:/apps/a,C:/apps/b")
    monkeypatch.setenv("EXTRA_PUBLIC_PATHS", "C:/public/a;C:/public/b")
    monkeypatch.setenv("EXTRA_RESOURCES_PATHS", '["C:/resources/a", "C:/resources/b"]')

    cfg = ServerConfig()

    assert cfg.extra_app_paths == ["C:/apps/a", "C:/apps/b"]
    assert cfg.extra_public_paths == ["C:/public/a", "C:/public/b"]
    assert cfg.extra_resources_paths == ["C:/resources/a", "C:/resources/b"]


def test_internal_path_defaults_to_internal_prefix() -> None:
    cfg = ServerConfig()
    assert cfg.internal_path_prefix == "/_internal"
    assert cfg.get_internal_path("ai/services") == "/_internal/ai/services"
    assert cfg.get_internal_admin_path("api/logs") == "/_internal/admin/api/logs"


def test_internal_path_does_not_guess_admin_or_ai() -> None:
    cfg = ServerConfig(internal_path_prefix="")
    assert cfg.internal_path_prefix == "/_internal"
    assert cfg.is_internal_path("/_internal/admin") is True
    assert cfg.is_internal_path("/_internal/ai/services") is True
    assert cfg.is_internal_path("/admin") is False
    assert cfg.is_internal_path("/admin/api/logs") is False
    assert cfg.is_internal_path("/ai") is False
    assert cfg.is_internal_path("/ai/completion/service") is False


def test_current_config_names_work() -> None:
    cfg = ServerConfig.model_validate({
        "expose_ai_service": True,
        "internal_path_allowed_ip": "10.1.*",
    })
    assert cfg.is_ai_service_exposed() is True
    assert cfg.get_internal_path_allowed_ip_patterns() == ["10.1.*"]
