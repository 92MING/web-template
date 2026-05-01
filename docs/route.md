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

如果方法名带后缀，后缀会继续拆成子路径：

- `get` -> 当前路由本身
- `get_all` -> `/all`
- `get_status_detail` -> `/status/detail`
- `websocket_chat` -> WebSocket `/chat`

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

    async def get_all(self) -> dict[str, str]:
        return {"scope": "all-items"}
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
2. 方法名后缀会继续追加到 URL，例如 `get_all` 对应 `/all`。
3. 一个文件里如果定义了多个 `Route` 子类，加载器会逐个挂载；但通常仍建议一个文件只放一组相关路由，避免可读性变差。
