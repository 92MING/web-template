# Route 开发手册

框架的核心是 `Route` 基类。任何继承自 `Route` 的类，只要放在 `app/`（或 `extra_app_paths` 指定的目录）下，就会被自动发现并注册为 FastAPI 路由。

有两个容易写错的点：

- `__init__.py` 可以定义 `Route`，而且它对应的是那个目录本身的 URL path。
- `index.py` 也会映射到所在目录本身的 URL path。

## 最小示例

```python
from core.server import Route

class HealthRoute(Route):
    Tags = "System"

    async def get(self) -> dict[str, str]:
        return {"status": "ok"}
```

包级路由同样合法：

```python
from core.server import Route


class UsersRootRoute(Route):
    async def get(self) -> dict[str, str]:
        return {"scope": "users-root"}
```

如果这个类定义在 `app/api/users/__init__.py`，对应路径就是 `/api/users`；如果定义在 `app/users/__init__.py`，对应路径就是 `/users`。

## HTTP 方法

方法名对应 HTTP verb，框架自动注册：

| 方法名 | HTTP 方法 |
| ------ | --------- |
| `get` | GET |
| `post` | POST |
| `put` | PUT |
| `patch` | PATCH |
| `delete` | DELETE |
| `head` | HEAD |
| `options` | OPTIONS |
| `websocket` | WebSocket |

类方法名必须精确等于 HTTP 方法名。`get_all`、`get_status_detail` 这类带后缀的方法不会被当成路由方法；如果需要子路径，请使用文件路径、`RoutePath`，或下面的函数装饰器。

## 函数装饰器路由

如果只是快速定义一个路由，可以不写 `Route` class，直接使用 `get`、`post` 等装饰器：

```python
from core.server.route import get


@get("/c")
async def hello() -> dict[str, str]:
    return {"message": "hello"}
```

如果这个函数定义在 `app/a/b.py`，对应路径就是 `/a/b/c`。

同一个文件里仍然可以定义 `Route` class。此时该文件里的 `Route` class 上声明的 `Tags`、`Dependencies`、`AllowedIPs`、`ApikeyProtected` 等配置，也会应用到同文件的装饰器路由上：

```python
from fastapi import Depends
from core.server import Route
from core.server.route import get


async def require_login() -> None:
    pass


class BRoute(Route):
    Tags = "B"
    Dependencies = Depends(require_login)


@get("/c")
async def hello() -> dict[str, str]:
    return {"message": "hello"}
```

可用装饰器包括：`route`、`get`、`post`、`put`、`patch`、`delete`、`head`、`options`、`websocket`。`route` 默认方法是 `GET`，也可以显式传 `method="POST"`。

## Route / HTML 查找顺序

访问一个无后缀路径时，例如 `GET /a/b/c`，框架按“应用目录优先、公开静态目录最后”的规则查找。

应用目录包括 `extra_app_paths` 和主仓 `app/`，顺序如下：

```text
for d in [*extra_app_paths, app/]:
    1. {d}/a/b/c/__init__.py
    2. {d}/a/b/c/index.py
    3. {d}/a/b/c/index.html
    4. {d}/a/b/c.py
    5. {d}/a/b/c.html
    6. {d}/a/b/_*_.py
    7. {d}/a/_*_/__init__.py
    8. {d}/a/_*_/index.py
    9. {d}/a/_*_.py
    10. {d}/_*_/__init__.py
    11. {d}/_*_/index.py
    12. {d}/_*_.py
```

`_*_` 表示合法的动态路径段，例如 `_user_id_`。动态目录里的 `index.html` 也会参与 HTML fallback；普通私有目录，例如 `_private/`，不会被当成 fallback 静态资源暴露。

公开静态目录包括 `extra_public_paths` 和主仓 `public/`，顺序如下：

```text
for d in [*extra_public_paths, public/]:
    1. {d}/a/b/c/index.html
    2. {d}/a/b/c.html
```

`public/` 不会扫描 Python Route。即使 `public/` 里存在 `.py` 文件，也只会被视作普通静态文件，不会 import，也不会注册路由。

父级 `__init__.py` / `index.py` 上声明的请求保护配置会在 middleware 层影响其 pattern 下的 HTML 和子路径访问，包括 `Dependencies`、`AllowedIPs`、`ApikeyProtected`。例如 `app/a/b/c/__init__.py` 开启 `ApikeyProtected` 后，`/a/b/c/index.html`、`/a/b/c/d` 这类访问也会先经过父级保护；如果更具体的 `app/a/b/c/d/__init__.py` 或 `app/a/b/c/d/index.py` 显式设置 `ApikeyProtected = False`，则会覆盖父级保护。

其中 `Dependencies` 是追加合并，父级和子级 dependency 都会执行；`AllowedIPs` 也是追加合并，任一白名单匹配即可放行；`ApikeyProtected` 是标量覆盖，最近的显式 `True` / `False` 生效。`Tags`、`ResponseModel` 这类只影响 API 注册/OpenAPI 的元数据不会作用到 HTML fallback。

```python
from fastapi import Body


class ItemRoute(Route):
    Tags = "Shop"

    async def get(self, item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    async def post(self, item_id: str, name: str = Body(...)) -> dict[str, str]:
        return {"created": item_id, "name": name}

    async def put(self, item_id: str, name: str = Body(...)) -> dict[str, str]:
        return {"updated": item_id, "name": name}

    async def delete(self, item_id: str) -> dict[str, str]:
        return {"deleted": item_id}
```

## 类级配置

```python
class OrderRoute(Route):
    Tags = ["Shop", "Order"]          # OpenAPI 标签分组
    Dependencies = [Depends(require_auth)]  # 全局依赖
    ApikeyProtected = True            # 需要合法 API key 且 key 有当前路径权限
    ResponseModel = OrderOut          # Pydantic 响应模型
    StatusCode = 201                  # 默认状态码
    Summary = "Create order"          # OpenAPI 摘要
    Description = "Create a new order" # OpenAPI 描述
    ResponseDescription = "Created order"
    OperationId = "createOrder"
    Deprecated = False
    IncludeInSchema = True
    AllowedIPs = "127.0.0.1"         # IP 白名单（仅本路由）
```

完整配置项：

| 配置项 | 类型 | 说明 |
| ------ | ---- | ---- |
| `Tags` | `str \| Sequence[str] \| None` | OpenAPI 标签 |
| `Dependencies` | `Depends \| Sequence[Depends] \| None` | 路由级依赖 |
| `ApikeyProtected` | `bool \| None` | 是否要求请求携带合法 API key，且 API key 权限匹配当前请求路径；`None` 表示继承父包配置 |
| `ResponseModel` | `Any \| None` | Pydantic 响应模型 |
| `StatusCode` | `int \| None` | 默认 HTTP 状态码 |
| `ResponseClass` | `Any \| None` | 自定义 Response 类 |
| `Responses` | `dict \| None` | 额外响应描述 |
| `Summary` | `str \| None` | OpenAPI 摘要 |
| `Description` | `str \| None` | OpenAPI 描述 |
| `ResponseDescription` | `str \| None` | OpenAPI response_description |
| `Deprecated` | `bool \| None` | 是否废弃 |
| `IncludeInSchema` | `bool \| None` | 是否包含在 OpenAPI 中 |
| `OperationId` | `str \| None` | OpenAPI operation_id |
| `Name` | `str \| None` | FastAPI 路由名 |
| `ResponseModelInclude` | `Any \| None` | response_model_include |
| `ResponseModelExclude` | `Any \| None` | response_model_exclude |
| `ResponseModelByAlias` | `bool \| None` | response_model_by_alias |
| `ResponseModelExcludeUnset` | `bool \| None` | response_model_exclude_unset |
| `ResponseModelExcludeDefaults` | `bool \| None` | response_model_exclude_defaults |
| `ResponseModelExcludeNone` | `bool \| None` | response_model_exclude_none |
| `Callbacks` | `list[Any] \| None` | FastAPI callbacks |
| `OpenapiExtra` | `dict[str, Any] \| None` | OpenAPI 扩展字段 |
| `GenerateUniqueIdFunction` | `Callable[..., str] \| None` | 自定义 operation id 生成器 |
| `AllowedIPs` | `str \| Sequence[str] \| None` | 本路由 IP 白名单 |

### 父包 Route 的继承规则

父目录的 `__init__.py` 中定义的 `Route` 不只是“自身挂载”，还会向子路由提供元数据。

继承/合并规则如下：

- `Tags` 追加合并。根包、父包、当前路由会按层级依次叠加。
- `Dependencies` 追加合并。
- `AllowedIPs` 追加合并，任一匹配即可放行。
- `ApikeyProtected` 是标量覆盖规则：默认值是 `None`，表示继承父包配置；父包设为 `True` 时，子路由默认继承；子路由显式设为 `False` 可关闭。
- 其他标量配置如 `Summary`、`Description`、`ResponseModel`、`StatusCode` 等，也是子类/子路由就近覆盖父级。

`ApikeyProtected` 开启后，API key 可通过 `x-api-key`、`Authorization: Bearer ...`、`api_key` 或 `x_api_key` 传入。

## 错误处理

`Route` 可以定义错误处理方法。框架会按请求路径查找最近的 Route handler；例如 `/a/b/c/d` 触发 404 时，如果 `/a/b/c` 对应的 Route 定义了错误处理，就优先调用它。

```python
from typing import Any

from core.server import ErrorContext, Route
from starlette.responses import HTMLResponse


class PageRoute(Route):
    def on_error_code(
        self,
        code: int,
        exception: Exception,
        context: ErrorContext,
    ) -> Any:
        if code == 404:
            return HTMLResponse(f"<h1>Not found</h1><p>{context.path}</p>", status_code=404)
        return exception

    async def on_exception(
        self,
        exception: Exception,
        context: ErrorContext,
    ) -> Any:
        if isinstance(exception, ValueError):
            return {"message": str(exception)}
        return await super().on_exception(exception, context)
```

两个方法都可以写成 sync 或 async：

- `on_exception(exception, context)`：处理普通异常。默认实现会在遇到 `HTTPException` 时继续调用 `on_error_code`。
- `on_error_code(code, exception, context)`：处理 HTTP 错误码，例如 404、403、500。
- 返回 `exception` 表示当前 handler 不处理该错误，继续使用原始错误行为。
- 返回其他值表示该 handler 已处理错误；可以返回 `dict`、`str`、`HTMLResponse`、`JSONResponse` 等 FastAPI 支持的响应值。

如果覆写了 `on_exception`，`on_error_code` 不一定会触发；是否继续触发取决于你的 `on_exception` 是否调用 `super().on_exception(...)`。

`ErrorContext` 会提供当前请求、路径、方法、匹配到的 Route path、Route class、异常 traceback 等上下文信息。字段如下：

| 字段 | 说明 |
| --- | --- |
| `request` | 当前 FastAPI `Request`。 |
| `path` | 当前请求路径。 |
| `method` | 当前请求方法。 |
| `route_path` | 本次命中的错误处理 Route path。 |
| `route_cls` | 本次命中的错误处理 Route class。 |
| `traceback` | 可为空的 `traceback.TracebackException`。真实异常会带 traceback；由 404/403 这类响应状态码触发时通常为 `None`。 |

## 路径参数

文件名使用 `_xxx_.py` 格式时，`xxx` 成为路径参数：

```text
app/api/user/_user_id_.py          ->  /api/user/{user_id}
app/api/class/_class_id_/chat.py   ->  /api/class/{class_id}/chat
app/api/classroom/_class_id_/__init__.py -> /api/classroom/{class_id}
```

方法签名中的参数名必须与路径参数名一致：

```python
class UserRoute(Route):
    async def get(self, user_id: str) -> dict[str, str]:
        return {"user_id": user_id}
```

## 私有文件

以下文件/目录会被跳过：

- `__pycache__`
- 以 `_` 开头但不以 `_` 结尾的文件（如 `_private.py`）
- 以 `_` 开头的目录（如 `_private/`）

不会被跳过：

- `__init__.py`
- `_user_id_.py` 这类路径参数文件
- `_class_id_` 这类路径参数目录

规则本质上是：

- 以 `_` 开头且以 `_` 结尾的名字，会被当作路径参数。
- 普通 `__init__.py` 会被当作包路由入口。
- 只有“私有名”才会被跳过，也就是以 `_` 开头、但不是路径参数占位的名字。

## 生命周期

```python
from fastapi import FastAPI


class MyRoute(Route):
    async def init(self, app: FastAPI) -> None:
        """每个 worker 启动时调用一次。"""
        await super().init(app)
        # 初始化逻辑，例如预热缓存
```

## 共享数据

每个 Route 实例在运行时都能访问：

```python
from typing import Any


class StateRoute(Route):
    async def get(self) -> dict[str, Any]:
        # 本节点跨 worker 内存 KV
        self.shared_dict.set("key", "value", expire=3600)
        val = self.shared_dict.get("key")

        # 跨节点分布式 KV
        await self.global_shared_dict.set("global_key", "global_value")
        gval = await self.global_shared_dict.get("global_key")

        # 共享数据容器（worker 注册、节点信息等）
        workers = self.shared_data.workers

        return {"local": val, "global": gval}
```

## Redirect（跨 worker / 跨节点）

```python
from typing import Any


class ProxyRoute(Route):
    async def get(self) -> Any:
        # 转发到本节点另一个 worker
        return await self.redirect(0, "/api/health")

        # 转发到指定节点
        return await self.redirect(("node-b", 0), "/api/health")

        # 转发到本类的另一个方法
        return await self.redirect(0, self.another_method, arg1="foo")
```

## FastAPI 依赖注入

Route 完全支持 FastAPI 的依赖注入：

```python
from fastapi import Query, Path, Body, UploadFile, File, Depends, Header

class UploadRoute(Route):
    Tags = "File"

    async def post(
        self,
        folder: str = Query("default"),
        file: UploadFile = File(...),
        x_token: str = Header(None),
    ) -> dict[str, str]:
        content = await file.read()
        return {"filename": file.filename, "size": len(content)}
```

## 自定义响应

```python
from fastapi import Response
from starlette.responses import PlainTextResponse, StreamingResponse

class DownloadRoute(Route):
    async def get(self) -> Response:
        data = b"hello world"
        return Response(content=data, media_type="application/octet-stream")
```

## 自动发现路径规则

| 文件路径 | 注册路径 |
| -------- | -------- |
| `app/api/__init__.py` | `/api` |
| `app/api/hello.py` | `/api/hello` |
| `app/api/user/__init__.py` | `/api/user` |
| `app/api/user/index.py` | `/api/user` |
| `app/api/user/_user_id_.py` | `/api/user/{user_id}` |
| `app/api/class/_class_id_/chat/index.py` | `/api/class/{class_id}/chat` |
| `app/api/class/_class_id_/chat/__init__.py` | `/api/class/{class_id}/chat` |
| `app/api/_private.py` | ❌ 跳过 |
| `app/api/_private/utils.py` | ❌ 跳过 |

如果路由文件位于 `extra_app_paths` 指定的目录中，规则相同。

再补三条容易漏掉的规则：

1. `__init__.py` 和 `index.py` 都会映射到所在目录本身。
2. 方法名后缀不会追加到 URL；子路径请用文件路径、`RoutePath` 或函数装饰器声明。
3. 一个文件里如果定义了多个 `Route` 子类，加载器会逐个挂载；但通常仍建议一个文件只放一组相关路由，避免可读性变差。
