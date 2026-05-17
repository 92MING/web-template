# 框架总览

这是一个以 FastAPI 为底座、以类路由为核心的 Python 3.12 后端模板。当前仓库里，框架默认提供这些能力：

- `app/api/` 自动发现并注册 `Route` 子类。
- `public/` 作为公共静态目录，支持同名 `.m.html` 移动分支自动合并。
- `resources/admin-panel/` 作为 `/_internal/admin` 管理面板静态资源。
- `/_internal/admin/openapi.json` 作为 internal 管理侧 OpenAPI 入口。
- `SharedDict` / `GlobalSharedDict` 作为共享状态能力。
- `KV`、`ORM`、`Object`、`Vector` 四类存储抽象。
- `completion`、`embedding`、`s2t`、`t2s`、`t2img` 五类 AI service 抽象。

## 项目结构

```text
app/
  api/              # 业务 API，自动发现 Route
  core/
    ai/             # AI service 抽象与实现
    server/         # FastAPI app、Route、管理面板、共享状态
    storage/        # KV / ORM / Object / Vector
    utils/          # 通用工具
  public/           # 站点静态资源，挂载到 /
  __main__.py       # 启动入口
config/             # 本地配置目录
docs/               # 开发文档
example/            # 示例项目
plugin/             # 可插拔功能模块，例如 webrtc-chatroom
resources/
  admin-panel/      # internal 管理面板资源
scripts/            # 安装、运行、重启等脚本
test/               # 测试
tmp/                # 临时文件
```

## 启动方式

开发模式最小启动命令：

```powershell
python -m app --server-port 8000 --server-worker 1
```

生产模式通常显式加上 `--production`：

```powershell
python -m app --production --server-port 8000 --server-worker 4
```

几点要注意：

- CLI 参数名是 `--server-host`、`--server-port`、`--server-worker`，不是旧文档里的 `--host`、`--port`、`--worker`。
- `--config` 读取的是服务主配置；存储和 AI 配置各自独立加载，不在同一个文件里。
- `--extra-app-paths`、`--extra-public-paths`、`--extra-resources-paths` 可以把业务目录额外挂进框架。

完整上手流程见 [getting-started.md](getting-started.md)。

## 路由模型

最常见的业务扩展方式，就是在 `app/api/` 下新增一个继承 `Route` 的类：

```python
from core.server import Route


class HelloRoute(Route):
    Tags = "Demo"

    async def get(self, name: str = "world") -> dict[str, str]:
        return {"message": f"Hello, {name}!"}
```

这会自动注册为 `/api/hello`。

文件和目录名也参与 URL 生成：

- `app/api/users/__init__.py` 对应 `/api/users`
- `app/api/users/index.py` 对应 `/api/users`
- `app/api/users/_user_id_.py` 对应 `/api/users/{user_id}`
- 子路径通过文件路径、`RoutePath` 或函数装饰器声明，方法名必须精确等于 HTTP 方法名

这部分的完整规则见 [route.md](route.md)。

## 管理面板与公开接口

服务启动后，默认有这些入口：

- `/`：站点入口，优先来自 `app/index.html`，再查 `public/` 与 `extra_public_paths`
- `/_internal/admin`：管理面板，默认开启，但只允许 `localhost`
- `/_internal/admin/openapi.json`：internal 管理侧 OpenAPI 文档数据
- `/_internal/ai/*`：AI service internal 管理与调用接口

AI 的公开别名 `/ai/*` 默认不会暴露。只有 `server_config.expose_ai_service = true`，或者 CLI 显式传 `--expose-ai-service`，才会同时开放 `/ai/*`。

## 配置体系

当前仓库不是“所有配置都塞进一个文件”的模式，而是三套独立配置：

1. 服务主配置：`Config`，由 `server_config`、`log_config`、`plugin_paths`、`plugin_configs` 组成。
2. 存储配置：`StorageConfig`，由存储模块单独自动发现。
3. AI 配置：`AIServicesConfig`，由 AI 模块单独自动发现。

服务主配置的默认发现顺序是：

- `config/dev_server.*` 或 `config/prod_server.*`（运行态优先）
- `config/server.*`

服务主配置文件结构是嵌套的，不是把 `host`、`port` 直接写在顶层。示例见 [config/README.md](config/README.md) 和 [config/server_example.yaml](config/server_example.yaml)。

## 前端静态资源

框架对前端目录的处理有两层：

- 根站点静态资源来自 `app/`、`public/`，并与 `extra_app_paths` / `extra_public_paths` 做覆盖式合并。
- 管理面板资源来自 `resources/admin-panel/`，单独挂载到 `/_internal/admin`。

`.html` 页面如果存在同名 `.m.html` 文件，会在返回时自动合并桌面版和移动版。详见 [frontend.md](frontend.md)。

## 生命周期事件与 Scheduler

业务模块可以在 `app/` 或 `extra_app_paths` 中注册两类运行时逻辑：

- main process 逻辑：`on_main_process_starts_event`、`on_main_process_stops_event`、`register_main_process_context_manager`，以及默认 `run_on="main_process"` 的 scheduler。
- FastAPI worker 逻辑：`on_app_created`、`on_before_app_created`、`on_app_shutdown`，以及 `run_on="fastapi_process"` 的 scheduler。

两者的导入规则不同：

- main process 在 uvicorn 启动前会遍历 import 一次 `app/` 和 `extra_app_paths` 下的 `.py` 文件，用来触发 schedule/event 的注册。此遍历会包含 `_` 开头的文件和目录；唯一跳过的是 `__main__.py`，避免递归执行启动入口。
- FastAPI worker 仍按 RouteLoader 的路由发现规则导入业务模块。`_private.py`、`_private/` 这类以 `_` 开头但不是 `_path_param_` 形式的文件/目录会被跳过，因此写在这些位置的 `on_app_created` / `on_before_app_created` / `on_app_shutdown` 不会在 worker 中生效。

如果一个非 `_` 文件同时包含 main process 注册和 FastAPI worker 注册，它通常会被 main process import 一次，并被每个 worker 再 import 一次。顶层代码应只做注册和常量定义，避免把有副作用的启动逻辑直接写在 import 阶段。

## 示例项目

示例项目不是“内嵌在 app 里”运行，而是各自通过启动脚本把自己的业务目录挂到框架上：

```powershell
cd example/e-class
python run.py

cd example/e-shop
python run.py
```

这两个脚本实际都会转调：

- `--extra-app-paths <example>`
- `--extra-public-paths <example>/public`

默认端口分别是：

- `example/e-class/run.py` -> `19001`
- `example/e-shop/run.py` -> `19002`

## 文档索引

- [getting-started.md](getting-started.md)：从零启动和第一个 Route
- [route.md](route.md)：Route、路径规则、元数据继承
- [storage.md](storage.md)：存储配置与使用
- [ai.md](ai.md)：AI service 配置与调用
- [frontend.md](frontend.md)：静态页面、`.m.html`、共享组件、i18n
- [deployment.md](deployment.md)：生产部署、反向代理、配置拆分
- [testing.md](testing.md)：测试组织与运行方式
- [config/README.md](config/README.md)：三套配置系统的职责与加载顺序
