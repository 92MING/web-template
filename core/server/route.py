# -*- coding: utf-8 -*-
"""Base Route class for auto-discovered API handlers.

Any ``.py`` file under an app directory (recursively, skipping private
``_``-prefixed names except ``_param_`` path segments) may contain a class
inheriting from ``Route``.  Each public method named after an HTTP verb
(``get``, ``post``, ``put``, ``patch``, ``delete``, ``head``, ``options``)
or ``websocket`` is automatically wired as a FastAPI route endpoint.

Path parameters are derived from ``_xxx_.py`` file names.
"""

from __future__ import annotations

import os
import sys
import inspect
import importlib
import importlib.util
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from traceback import TracebackException
from typing import Annotated, Any, Callable, ClassVar, Literal, Sequence, TypedDict, Unpack, get_args, get_origin, get_type_hints, overload

from fastapi import FastAPI, HTTPException, Request, WebSocketException, status
from fastapi.params import Depends
from starlette.requests import HTTPConnection

from core.server.data_types.apikey import validate_apikey_route

from .request import AdvanceRequest
from .shared import AppSharedData
from .shared_dict import SharedDict, GlobalSharedDict


_Default = Annotated
type RouteMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "WEBSOCKET"]
ROUTE_METHODS: tuple[RouteMethod, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "WEBSOCKET")


class _RouteParams(TypedDict, total=False):
    path: _Default[str, Literal[""]]
    apikey_protected: _Default[bool | None, None]
    tags: _Default[str | Sequence[str] | None, None]
    dependencies: _Default[Depends | Sequence[Depends] | None, None]
    response_model: _Default[Any | None, None]
    status_code: _Default[int | None, None]
    response_class: _Default[Any | None, None]
    responses: _Default[dict[int | str, dict[str, Any]] | None, None]
    summary: _Default[str | None, None]
    description: _Default[str | None, None]
    response_description: _Default[str | None, None]
    deprecated: _Default[bool | None, None]
    include_in_schema: _Default[bool | None, None]
    operation_id: _Default[str | None, None]
    name: _Default[str | None, None]
    response_model_include: _Default[Any | None, None]
    response_model_exclude: _Default[Any | None, None]
    response_model_by_alias: _Default[bool | None, None]
    response_model_exclude_unset: _Default[bool | None, None]
    response_model_exclude_defaults: _Default[bool | None, None]
    response_model_exclude_none: _Default[bool | None, None]
    callbacks: _Default[list[Any] | None, None]
    openapi_extra: _Default[dict[str, Any] | None, None]
    generate_unique_id_function: _Default[Callable[..., str] | None, None]
    allowed_ips: _Default[str | Sequence[str] | None, None]


class _RouteParamsWithMethod(_RouteParams, total=False):
    method: _Default[RouteMethod, Literal["GET"]]


@dataclass(frozen=True)
class _DecoratedRouteDefinition:
    method: RouteMethod
    path: str
    route_attrs: dict[str, Any]


@dataclass
class ErrorContext:
    request: Request | None
    path: str
    method: str
    route_path: str | None = None
    route_cls: type["Route"] | None = None
    traceback: TracebackException | None = None


_FUNCTION_ROUTE_DEFINITIONS = "__route_definitions__"

_PARAM_DEFAULTS: dict[str, Any] = {
    "path": "",
    "method": "GET",
    "apikey_protected": None,
    "tags": None,
    "dependencies": None,
    "response_model": None,
    "status_code": None,
    "response_class": None,
    "responses": None,
    "summary": None,
    "description": None,
    "response_description": None,
    "deprecated": None,
    "include_in_schema": None,
    "operation_id": None,
    "name": None,
    "response_model_include": None,
    "response_model_exclude": None,
    "response_model_by_alias": None,
    "response_model_exclude_unset": None,
    "response_model_exclude_defaults": None,
    "response_model_exclude_none": None,
    "callbacks": None,
    "openapi_extra": None,
    "generate_unique_id_function": None,
    "allowed_ips": None,
}

_DECORATOR_PARAM_TO_ROUTE_ATTR = {
    "apikey_protected": "ApikeyProtected",
    "tags": "Tags",
    "dependencies": "Dependencies",
    "response_model": "ResponseModel",
    "status_code": "StatusCode",
    "response_class": "ResponseClass",
    "responses": "Responses",
    "summary": "Summary",
    "description": "Description",
    "response_description": "ResponseDescription",
    "deprecated": "Deprecated",
    "include_in_schema": "IncludeInSchema",
    "operation_id": "OperationId",
    "name": "Name",
    "response_model_include": "ResponseModelInclude",
    "response_model_exclude": "ResponseModelExclude",
    "response_model_by_alias": "ResponseModelByAlias",
    "response_model_exclude_unset": "ResponseModelExcludeUnset",
    "response_model_exclude_defaults": "ResponseModelExcludeDefaults",
    "response_model_exclude_none": "ResponseModelExcludeNone",
    "callbacks": "Callbacks",
    "openapi_extra": "OpenapiExtra",
    "generate_unique_id_function": "GenerateUniqueIdFunction",
    "allowed_ips": "AllowedIPs",
}


def _tidy_default_params(typed_dict: type, **kwargs: Any) -> dict[str, Any]:
    hints = get_type_hints(typed_dict, include_extras=True)
    unknown = set(kwargs) - set(hints)
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise TypeError(f"Unknown route parameter(s): {joined}")

    tidied: dict[str, Any] = {}
    for key, value in kwargs.items():
        hint = hints[key]
        default = _PARAM_DEFAULTS.get(key)
        has_default = key in _PARAM_DEFAULTS
        if get_origin(hint) is Annotated:
            metadata = get_args(hint)[1:]
            if metadata and key not in _PARAM_DEFAULTS:
                default = metadata[0]
                has_default = True
        if has_default and value == default:
            continue
        tidied[key] = value
    return tidied


def _route_attrs_from_params(params: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for key, value in params.items():
        route_attr = _DECORATOR_PARAM_TO_ROUTE_ATTR.get(key)
        if route_attr is not None:
            attrs[route_attr] = value
    return attrs


def _decorated_route_definition(method: RouteMethod, path: str = "", **kwargs: Any) -> _DecoratedRouteDefinition:
    params = _tidy_default_params(_RouteParams, path=path, **kwargs)
    route_path = str(params.pop("path", "") or "")
    return _DecoratedRouteDefinition(method=method, path=route_path, route_attrs=_route_attrs_from_params(params))


def _attach_route_definition[F: Callable[..., Any]](func: F, definition: _DecoratedRouteDefinition) -> F:
    definitions: list[_DecoratedRouteDefinition] = list(getattr(func, _FUNCTION_ROUTE_DEFINITIONS, ()))
    definitions.append(definition)
    setattr(func, _FUNCTION_ROUTE_DEFINITIONS, definitions)
    return func


def _route_decorator_call(default_method: RouteMethod | None, *args: Any, **kwargs: Any) -> Any:
    if args and callable(args[0]) and len(args) == 1 and "path" not in kwargs:
        method = default_method or "GET"
        return _attach_route_definition(args[0], _decorated_route_definition(method, **kwargs))
    if len(args) > 1:
        raise TypeError("Route decorator accepts at most one positional argument.")

    path = ""
    if args:
        if not isinstance(args[0], str):
            raise TypeError("Route decorator positional argument must be a path string or callable.")
        path = args[0]
    elif "path" in kwargs:
        path = str(kwargs.pop("path") or "")

    if default_method is None:
        method = str(kwargs.pop("method", "GET") or "GET").upper()
        if method not in ROUTE_METHODS:
            raise ValueError(f"Unsupported route method: {method}")
    else:
        method = default_method

    definition = _decorated_route_definition(method, path, **kwargs)

    def _decorator[F: Callable[..., Any]](func: F) -> F:
        return _attach_route_definition(func, definition)

    return _decorator


@overload
def route[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def route[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParamsWithMethod]) -> Callable[[F], F]: ...


@overload
def route[F: Callable[..., Any]](**kwargs: Unpack[_RouteParamsWithMethod]) -> Callable[[F], F]: ...


def route(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call(None, *args, **kwargs)


def _method_decorator(default_method: RouteMethod) -> Callable[..., Any]:
    def _decorator(*args: Any, **kwargs: Any) -> Any:
        return _route_decorator_call(default_method, *args, **kwargs)
    return _decorator


@overload
def get[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def get[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def get[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def get(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("GET", *args, **kwargs)


@overload
def post[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def post[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def post[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def post(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("POST", *args, **kwargs)


@overload
def put[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def put[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def put[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def put(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("PUT", *args, **kwargs)


@overload
def patch[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def patch[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def patch[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def patch(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("PATCH", *args, **kwargs)


@overload
def delete[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def delete[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def delete[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def delete(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("DELETE", *args, **kwargs)


@overload
def head[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def head[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def head[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def head(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("HEAD", *args, **kwargs)


@overload
def options[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def options[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def options[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def options(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("OPTIONS", *args, **kwargs)


@overload
def websocket[F: Callable[..., Any]](f: F, /) -> F: ...


@overload
def websocket[F: Callable[..., Any]](path: str, /, **kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


@overload
def websocket[F: Callable[..., Any]](**kwargs: Unpack[_RouteParams]) -> Callable[[F], F]: ...


def websocket(*args: Any, **kwargs: Any) -> Any:
    return _route_decorator_call("WEBSOCKET", *args, **kwargs)


class Route:
    """Inherit from this class to declare a discoverable API route."""

    Tags: ClassVar[str | Sequence[str] | None] = None
    Dependencies: ClassVar[Depends | Sequence[Depends] | None] = None
    ResponseModel: ClassVar[Any | None] = None
    StatusCode: ClassVar[int | None] = None
    ResponseClass: ClassVar[Any | None] = None
    Responses: ClassVar[dict[int | str, dict[str, Any]] | None] = None
    Summary: ClassVar[str | None] = None
    Description: ClassVar[str | None] = None
    ResponseDescription: ClassVar[str | None] = None
    Deprecated: ClassVar[bool | None] = None
    IncludeInSchema: ClassVar[bool | None] = None
    OperationId: ClassVar[str | None] = None
    ResponseModelInclude: ClassVar[Any | None] = None
    ResponseModelExclude: ClassVar[Any | None] = None
    ResponseModelByAlias: ClassVar[bool | None] = None
    ResponseModelExcludeUnset: ClassVar[bool | None] = None
    ResponseModelExcludeDefaults: ClassVar[bool | None] = None
    ResponseModelExcludeNone: ClassVar[bool | None] = None
    Callbacks: ClassVar[list[Any] | None] = None
    OpenapiExtra: ClassVar[dict[str, Any] | None] = None
    GenerateUniqueIdFunction: ClassVar[Callable[..., str] | None] = None
    Name: ClassVar[str | None] = None
    RoutePath: ClassVar[str | None] = None
    Abstract: ClassVar[bool] = False
    ApikeyProtected: ClassVar[bool | None] = None
    AllowedIPs: ClassVar[str | Sequence[str] | None] = None

    def __init__(self) -> None:
        self._app: FastAPI | None = None

    async def init(self, app: FastAPI) -> None:
        """Called once per worker during application startup."""
        self._app = app

    async def on_exception(self, exception: Exception, context: ErrorContext) -> Any:
        if isinstance(exception, HTTPException):
            result = self.on_error_code(exception.status_code, exception, context)
            if inspect.isawaitable(result):
                return await result
            return result
        return exception

    async def on_error_code(self, code: int, exception: Exception, context: ErrorContext) -> Any:
        return exception

    @property
    def shared_data(self) -> AppSharedData:
        return AppSharedData.Get()

    @property
    def shared_dict(self) -> SharedDict:
        return SharedDict(self.shared_data, namespace=self.__class__.__name__)

    @property
    def global_shared_dict(self) -> GlobalSharedDict:
        return GlobalSharedDict.get_instance()

    # ── redirect helper ────────────────────────────────────────────────────

    @overload
    async def redirect(
        self,
        target: int | tuple[str, int],
        route: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...

    @overload
    async def redirect(
        self,
        target: int | tuple[str, int],
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...

    async def redirect( # type: ignore[override]
        self,
        target: int | tuple[str, int],
        func_or_route: Callable[..., Any] | str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Forward execution to another worker or remote node.

        Args:
            target: Another worker's pid, or (server_id, worker_id) for
                distributed forwarding.
            func_or_route: A public callable, a Route method (e.g.
                ``SomeRoute.get``), or a route path string.
        """
        from .app import redirect_to_worker, get_app
        from .shared import WorkerRedirectMessage

        # Resolve target
        if isinstance(target, int):
            worker_id = target
        elif isinstance(target, tuple) and len(target) == 2:
            # Distributed forwarding — not yet fully implemented for remote nodes
            server_id, worker_id = target
            if server_id == self.shared_data.instance_uuid:
                # Same node, treat as local worker redirect
                target = worker_id  # type: ignore[assignment]
            else:
                raise NotImplementedError(
                    f"Distributed redirect to remote node {server_id} is not yet implemented."
                )
        else:
            raise TypeError(f"Invalid redirect target: {target}")

        # Resolve func_or_route to path + params
        if isinstance(func_or_route, str):
            path = func_or_route
            method = kwargs.pop("method", "GET").upper()
            request_params: dict[str, object] = dict(kwargs)
            if args:
                raise ValueError("Positional args are not supported when redirecting by path string.")
        elif callable(func_or_route):
            # Try to resolve the callable to a route path
            path, method, request_params = self._resolve_callable_to_route(
                func_or_route, args, kwargs
            )
        else:
            raise TypeError(f"Invalid redirect func_or_route: {func_or_route}")

        if worker_id == os.getpid():
            # Local — direct handle
            msg = WorkerRedirectMessage(
                sender=os.getpid(),
                path=path,
                method=method,
                request_params=request_params,
            )
            r = await msg.handle(get_app())
            if r.error is not None:
                raise r.error
            return r.result

        # Cross-worker redirect
        from starlette.requests import Request as StarletteRequest
        scope = {
            "type": "http",
            "path": path,
            "method": method,
            "headers": [],
        }
        request = StarletteRequest(scope)
        return await redirect_to_worker(worker_id, request, request_params)

    def _resolve_callable_to_route(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[str, str, dict[str, object]]:
        """Try to map a callable back to its mounted route path."""
        from starlette.routing import Route as StarletteRoute
        from .app import get_app
        app = get_app()

        # Try to find the route by matching endpoint
        for route in app.routes:
            if isinstance(route, StarletteRoute) and route.endpoint is func:
                path = route.path
                method = route.methods[0] if route.methods else "GET"   # type: ignore[union-attr]
                # Build params from signature
                sig = inspect.signature(func)
                params: dict[str, object] = {}
                bound = sig.bind(None, *args, **kwargs)
                bound.apply_defaults()
                for name, value in bound.arguments.items():
                    if name == "self":
                        continue
                    params[name] = value
                return path, method, params

        # Fallback: treat as direct call if same process
        if os.getpid() == os.getpid():  # always true locally
            raise RuntimeError(
                f"Could not resolve {func!r} to a mounted route. "
                "When redirecting across workers, only path strings or "
                "mounted Route methods are supported."
            )
        return "", "GET", {}  # unreachable

    # ── HTTP verb stubs ──
    async def get(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def put(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def patch(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def head(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def options(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class RouteLoader:
    """Auto-discover Route subclasses and mount them on a FastAPI app."""

    _HTTP_VERBS = ("get", "post", "put", "patch", "delete", "head", "options")
    _SCALAR_ROUTE_KWARGS = {
        "ResponseModel": "response_model",
        "StatusCode": "status_code",
        "ResponseClass": "response_class",
        "Responses": "responses",
        "Summary": "summary",
        "Description": "description",
        "ResponseDescription": "response_description",
        "Deprecated": "deprecated",
        "IncludeInSchema": "include_in_schema",
        "OperationId": "operation_id",
        "ResponseModelInclude": "response_model_include",
        "ResponseModelExclude": "response_model_exclude",
        "ResponseModelByAlias": "response_model_by_alias",
        "ResponseModelExcludeUnset": "response_model_exclude_unset",
        "ResponseModelExcludeDefaults": "response_model_exclude_defaults",
        "ResponseModelExcludeNone": "response_model_exclude_none",
        "Callbacks": "callbacks",
        "OpenapiExtra": "openapi_extra",
        "GenerateUniqueIdFunction": "generate_unique_id_function",
        "Name": "name",
    }

    def __init__(self, api_root: Path, app: FastAPI) -> None:
        self.api_root = api_root
        self.app = app
        try:
            root_key = str(api_root.resolve()).replace("\\", "/")
        except Exception:
            root_key = str(api_root).replace("\\", "/")
        self._module_prefix = "_app_routes_" + str(abs(hash(root_key)))

    def load_all(self) -> None:
        if not self.api_root.is_dir():
            return
        self._register_app_root()
        for import_root in (self.api_root, self.api_root / "api"):
            root_text = str(import_root)
            if import_root.is_dir() and root_text not in sys.path:
                sys.path.insert(0, root_text)
        discovered: list[tuple[type[Route], Path]] = []
        decorated_routes: list[tuple[Callable[..., Any], Path, _DecoratedRouteDefinition]] = []
        for py_file in sorted(self.api_root.rglob("*.py")):
            rel = py_file.relative_to(self.api_root)
            if self._should_skip_rel_path(rel):
                continue
            full_module = self._module_name_for_rel_path(rel)
            try:
                spec = importlib.util.spec_from_file_location(full_module, str(py_file))
                if spec is None or spec.loader is None:
                    print(f"[RouteLoader] spec failed: {full_module}")
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[full_module] = mod
                spec.loader.exec_module(mod)
            except Exception as exc:
                print(f"[RouteLoader] import failed: {full_module}: {exc}")
                continue
            for name in sorted(dir(mod)):
                obj = getattr(mod, name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, Route)
                    and obj is not Route
                    and not bool(obj.__dict__.get("Abstract", False))
                ):
                    discovered.append((obj, rel))
                if callable(obj) and getattr(obj, "__module__", None) == mod.__name__:
                    for definition in getattr(obj, _FUNCTION_ROUTE_DEFINITIONS, ()):
                        decorated_routes.append((obj, rel, definition))

        by_rel_path: dict[Path, list[type[Route]]] = {}
        for route_cls, rel in discovered:
            by_rel_path.setdefault(rel, []).append(route_cls)

        mount_items: list[tuple[tuple[tuple[int, str], ...], int, object]] = []
        for route_cls, rel in discovered:
            mount_items.append((self._route_sort_key(rel), 0, (route_cls, rel)))
        for func, rel, definition in decorated_routes:
            mounted_path = self._function_route_url_path(rel, definition.path)
            order_rel_path = self._order_rel_path_for_url_path(mounted_path)
            mount_items.append((self._route_sort_key(order_rel_path), 1, (func, rel, definition, mounted_path, order_rel_path)))

        for _, kind, payload in sorted(mount_items, key=lambda item: (item[0], item[1])):
            if kind == 0:
                route_cls, rel = payload  # type: ignore[misc]
                parent_route_classes = self._parent_route_classes(rel, by_rel_path) # type: ignore[arg-type]
                self._mount(route_cls, rel, parent_route_classes) # type: ignore[arg-type]
            else:
                func, rel, definition, mounted_path, order_rel_path = payload  # type: ignore[misc]
                parent_route_classes = [
                    *self._parent_route_classes(rel, by_rel_path), # type: ignore[arg-type]
                    *by_rel_path.get(rel, ()), # type: ignore[arg-type]
                ]
                self._mount_function_route(
                    func, # type: ignore[arg-type]
                    rel, # type: ignore[arg-type]
                    definition, # type: ignore[arg-type]
                    mounted_path, # type: ignore[arg-type]
                    order_rel_path, # type: ignore[arg-type]
                    parent_route_classes,
                )

    def _register_app_root(self) -> None:
        roots = getattr(self.app.state, "route_loader_app_roots", None)
        if roots is None:
            roots = []
            self.app.state.route_loader_app_roots = roots
        root_text = str(self.api_root.resolve())
        if root_text not in roots:
            roots.append(root_text)

    def _mount(
        self,
        route_cls: type[Route],
        rel_path: Path,
        parent_route_classes: Sequence[type[Route]] | None = None,
    ) -> None:
        import logging

        logger = logging.getLogger(__name__)
        instance = route_cls()
        explicit_route_path = getattr(route_cls, "RoutePath", None)
        url_path = explicit_route_path if explicit_route_path else self._build_url_path(rel_path)
        route_kwargs = self._build_route_kwargs(route_cls, parent_route_classes or ())
        self._register_route_class_entry(route_cls, rel_path, parent_route_classes or (), url_path, instance)

        for method_name in sorted(dir(instance)):
            method = self._route_kind_from_method_name(method_name)
            if method is None:
                continue
            if method_name not in route_cls.__dict__:
                continue
            handler = getattr(instance, method_name, None)
            if handler is None or not callable(handler):
                continue
            if not self._is_route_handler_overridden(method_name, handler):
                continue

            sig = inspect.signature(handler)
            params = list(sig.parameters.values())
            # Remove 'self' from FastAPI signature
            if params and params[0].name == "self":
                params = params[1:]

            # Re-build endpoint with stripped self
            async def _endpoint(*args: Any, __handler=handler, **kwargs: Any) -> Any:
                return await __handler(*args, **kwargs)

            # Copy signature
            _endpoint.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]
            _endpoint.__annotations__ = dict(getattr(handler, "__annotations__", {}))

            mounted_path = url_path
            self._register_route_entry(
                route_cls,
                rel_path,
                parent_route_classes or (),
                method,
                mounted_path,
            )
            if method == "websocket":
                self.app.add_api_websocket_route(
                    mounted_path,
                    _endpoint,
                    **self._websocket_route_kwargs(route_kwargs),
                )
                logger.debug("Mounted WEBSOCKET %s -> %s", mounted_path, route_cls.__name__)
            else:
                self.app.add_api_route(
                    mounted_path,
                    _endpoint,
                    methods=[method.upper()],
                    **route_kwargs,
                )
                logger.debug("Mounted %s %s -> %s", method.upper(), mounted_path, route_cls.__name__)

        # Register init callback
        from .app import on_before_app_created

        @on_before_app_created
        async def _init_route(app: FastAPI) -> None:
            await instance.init(app)

    def _mount_function_route(
        self,
        func: Callable[..., Any],
        rel_path: Path,
        definition: _DecoratedRouteDefinition,
        mounted_path: str,
        order_rel_path: Path,
        parent_route_classes: Sequence[type[Route]],
    ) -> None:
        import logging

        logger = logging.getLogger(__name__)
        route_cls = type(
            f"_{getattr(func, '__name__', 'Function').title().replace('_', '')}DecoratedRoute",
            (Route,),
            {"Abstract": False, **definition.route_attrs},
        )
        instance = route_cls()
        route_kwargs = self._build_route_kwargs(route_cls, parent_route_classes)

        sig = inspect.signature(func)

        async def _endpoint(*args: Any, __handler=func, **kwargs: Any) -> Any:
            result = __handler(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        _endpoint.__signature__ = sig  # type: ignore[attr-defined]
        _endpoint.__annotations__ = dict(getattr(func, "__annotations__", {}))

        self._register_route_entry(
            route_cls,
            rel_path,
            parent_route_classes,
            definition.method,
            mounted_path,
            order_rel_path=order_rel_path,
        )
        self._register_route_class_entry(route_cls, rel_path, parent_route_classes, mounted_path, instance)
        if definition.method == "WEBSOCKET":
            self.app.add_api_websocket_route(
                mounted_path,
                _endpoint,
                **self._websocket_route_kwargs(route_kwargs),
            )
            logger.debug("Mounted WEBSOCKET %s -> %s", mounted_path, getattr(func, "__name__", repr(func)))
        else:
            self.app.add_api_route(
                mounted_path,
                _endpoint,
                methods=[definition.method],
                **route_kwargs,
            )
            logger.debug("Mounted %s %s -> %s", definition.method, mounted_path, getattr(func, "__name__", repr(func)))

    def _register_route_entry(
        self,
        route_cls: type[Route],
        rel_path: Path,
        parent_route_classes: Sequence[type[Route]],
        method: str,
        mounted_path: str,
        *,
        order_rel_path: Path | None = None,
    ) -> None:
        entries = getattr(self.app.state, "route_loader_entries", None)
        if entries is None:
            entries = []
            self.app.state.route_loader_entries = entries
        entries.append({
            "root": str(self.api_root.resolve()),
            "rel_path": rel_path.as_posix(),
            "order_rel_path": (order_rel_path or rel_path).as_posix(),
            "route_path": mounted_path,
            "method": method.upper(),
            "route_cls": route_cls,
            "route_classes": [*parent_route_classes, route_cls],
        })

    def _register_route_class_entry(
        self,
        route_cls: type[Route],
        rel_path: Path,
        parent_route_classes: Sequence[type[Route]],
        url_path: str,
        instance: Route,
    ) -> None:
        entries = getattr(self.app.state, "route_loader_class_entries", None)
        if entries is None:
            entries = []
            self.app.state.route_loader_class_entries = entries
        entries.append({
            "root": str(self.api_root.resolve()),
            "rel_path": rel_path.as_posix(),
            "route_path": url_path,
            "route_cls": route_cls,
            "route_instance": instance,
            "route_classes": [*parent_route_classes, route_cls],
        })

    def _module_name_for_rel_path(self, rel_path: Path) -> str:
        module_path = rel_path.with_suffix("")
        parts = list(module_path.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        suffix = ".".join(parts)
        safe_suffix = suffix.replace("-", "_")
        return f"{self._module_prefix}.{safe_suffix}" if safe_suffix else self._module_prefix

    def _function_route_url_path(self, rel_path: Path, route_path: str) -> str:
        base_path = self._build_url_path(rel_path)
        suffix = str(route_path or "").strip("/")
        if not suffix:
            return base_path
        return base_path.rstrip("/") + "/" + suffix

    def _order_rel_path_for_url_path(self, url_path: str) -> Path:
        parts = [part for part in str(url_path or "").split("/") if part]
        if not parts:
            return Path("__init__.py")
        rel_parts: list[str] = []
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                name = part[1:-1].split(":", 1)[0]
                rel_parts.append(f"_{name}_")
            else:
                rel_parts.append(part)
        return Path(*rel_parts).with_suffix(".py")

    def _should_skip_rel_path(self, rel_path: Path) -> bool:
        parts = list(rel_path.parts)
        for idx, part in enumerate(parts):
            name = part[:-3] if idx == len(parts) - 1 and part.endswith(".py") else part
            if name == "__init__":
                continue
            if name.startswith("_") and name.endswith("_") and len(name) > 2:
                continue
            if name.startswith("_"):
                return True
        return False

    def _parent_route_classes(
        self,
        rel_path: Path,
        by_rel_path: dict[Path, list[type[Route]]],
    ) -> list[type[Route]]:
        parents: list[type[Route]] = []
        route_parts = list(rel_path.with_suffix("").parts)
        if route_parts and route_parts[-1] in {"__init__", "index"}:
            route_parts = route_parts[:-1]

        for depth in range(0, len(route_parts) + 1):
            prefix = route_parts[:depth]
            for entry_name in ("__init__.py", "index.py"):
                parent_rel = Path(*prefix) / entry_name if prefix else Path(entry_name)
                if parent_rel == rel_path:
                    continue
                parents.extend(by_rel_path.get(parent_rel, ()))
        return parents

    def _build_url_path(self, rel_path: Path) -> str:
        parts = list(rel_path.with_suffix("").parts)
        if parts and parts[-1] in {"index", "__init__"}:
            parts = parts[:-1]
        url_parts: list[str] = []
        for idx, part in enumerate(parts):
            if part.startswith("_") and part.endswith("_"):
                converter = ":path" if idx == len(parts) - 1 else ""
                url_parts.append(f"{{{part[1:-1]}{converter}}}")
            else:
                url_parts.append(part)
        return "/" + "/".join(url_parts) if url_parts else "/"

    def _route_sort_key(self, rel_path: Path) -> tuple[tuple[int, str], ...]:
        parts = list(rel_path.with_suffix("").parts)
        if parts and parts[-1] in {"index", "__init__"}:
            parts = parts[:-1]
        key_parts: list[tuple[int, str]] = []
        for part in parts:
            is_dynamic = part.startswith("_") and part.endswith("_") and len(part) > 2
            key_parts.append((1 if is_dynamic else 0, part.strip("_") if is_dynamic else part))
        return tuple(key_parts)

    def _route_kind_from_method_name(self, method_name: str) -> str | None:
        if method_name == "websocket":
            return "websocket"
        for verb in self._HTTP_VERBS:
            if method_name == verb:
                return verb
        return None

    def _is_route_handler_overridden(self, method_name: str, handler: Callable[..., Any]) -> bool:
        base_handler = getattr(Route, method_name, None)
        if base_handler is None:
            return True
        func = getattr(handler, "__func__", handler)
        return func is not base_handler

    def _build_route_kwargs(
        self,
        route_cls: type[Route],
        parent_route_classes: Sequence[type[Route]],
    ) -> dict[str, Any]:
        chain = [*parent_route_classes, route_cls]
        kwargs: dict[str, Any] = {}

        tags = self._collect_append_attr(chain, "Tags")
        if tags:
            kwargs["tags"] = tags

        dependencies = self._collect_append_attr(chain, "Dependencies")
        allowed_ips = self._collect_append_attr(chain, "AllowedIPs")
        if allowed_ips:
            dependencies.append(Depends(self._make_allowed_ips_dependency(allowed_ips)))
        if bool(self._resolve_scalar_attr(chain, "ApikeyProtected", default=False)):
            dependencies.append(Depends(self._require_apikey_dependency))
        if dependencies:
            kwargs["dependencies"] = dependencies

        for class_attr, kwarg_name in self._SCALAR_ROUTE_KWARGS.items():
            value = self._resolve_scalar_attr(chain, class_attr)
            if value is not None:
                kwargs[kwarg_name] = value
        return kwargs

    def _websocket_route_kwargs(self, route_kwargs: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "dependencies"}
        return {key: value for key, value in route_kwargs.items() if key in allowed}

    def _collect_append_attr(self, route_classes: Sequence[type[Route]], attr: str) -> list[Any]:
        values: list[Any] = []
        for route_cls in route_classes:
            raw_value = self._get_declared_route_attr(route_cls, attr)
            if raw_value is None:
                continue
            values.extend(self._as_list(raw_value))
        return values

    def _resolve_scalar_attr(self, route_classes: Sequence[type[Route]], attr: str, *, default: Any = None) -> Any:
        for route_cls in reversed(route_classes):
            value = self._get_declared_route_attr(route_cls, attr)
            if value is not None:
                return value
        return default

    def _get_declared_route_attr(self, route_cls: type[Route], attr: str) -> Any:
        for cls in inspect.getmro(route_cls):
            if cls is Route:
                break
            if attr in cls.__dict__:
                return getattr(route_cls, attr)
        return None

    def _as_list(self, value: Any) -> list[Any]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, Sequence):
            return list(value)
        return [value]

    def _make_allowed_ips_dependency(self, allowed_ips: Sequence[str]) -> Callable[[HTTPConnection], None]:
        patterns = tuple(str(item).strip() for item in allowed_ips if str(item).strip())

        def _check_allowed_ip(connection: HTTPConnection) -> None:
            client_ip = connection.client.host if connection.client else None
            if client_ip and any(fnmatch.fnmatchcase(client_ip, pattern) for pattern in patterns):
                return
            if connection.scope.get("type") == "websocket":
                raise WebSocketException(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Access denied from this IP.",
                )
            raise HTTPException(status_code=403, detail="Access denied from this IP.")

        return _check_allowed_ip

    async def _require_apikey_dependency(self, connection: HTTPConnection) -> None:
        api_key = str(getattr(connection, "apikey", "") or "").strip() or None
        if api_key is None and isinstance(connection, Request):
            api_key = AdvanceRequest.Cast(connection).apikey
        if api_key is None:
            api_key = self._extract_apikey(connection)
        if not api_key:
            self._raise_apikey_failure(connection, "Missing API key", http_status=401)
        else:
            path = str(connection.scope.get("path") or "").strip() or "/"
            result = await validate_apikey_route(api_key, path, record_access=True) 
            if result.ok:
                return
            self._raise_apikey_failure(
                connection,
                result.detail or result.reason,
                http_status=self._apikey_failure_http_status(result.reason),
            )

    def _extract_apikey(self, connection: HTTPConnection) -> str | None:
        header_key = (connection.headers.get("x-api-key") or "").strip()
        if header_key:
            return header_key
        authorization = (connection.headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            if token:
                return token
        cookie_key = (getattr(connection, "cookies", {}).get("x-api-key") or "").strip()
        if cookie_key:
            return cookie_key
        query_key = (
            connection.query_params.get("api_key")
            or connection.query_params.get("x_api_key")
            or ""
        ).strip()
        return query_key or None

    def _apikey_failure_http_status(self, reason: str | None) -> int:
        if reason == "not_found":
            return 401
        if reason in {"banned", "route_not_allowed"}:
            return 403
        if reason == "insufficient_credit":
            return 402
        if reason in {"minimum_interval", "rate_limited"}:
            return 429
        return 401

    def _raise_apikey_failure(
        self,
        connection: HTTPConnection,
        detail: str,
        *,
        http_status: int,
    ) -> None:
        if connection.scope.get("type") == "websocket":
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason=detail,
            )
        raise HTTPException(status_code=http_status, detail=detail)
