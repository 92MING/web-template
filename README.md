# Backend Template

可复制使用的 Python/FastAPI 后端框架模板，核心能力集中在根级 `core/`：类路由、管理面板、共享状态、统一存储、AI service 抽象、RTC 基础模块，以及直接可用的静态资源体系。

## 你会得到什么

- 自动发现 `app/api/` 下的 `Route` 子类并注册到 `/api/*`
- `public/` 公共静态资源目录，支持同名 `.m.html` 移动分支自动合并
- `resources/admin-panel/` 管理面板资源，默认挂载到 `/_internal/admin`
- `SharedDict` / `GlobalSharedDict` 共享状态能力
- `KV`、`ORM`、`Object`、`Vector` 四类存储抽象
- `completion`、`embedding`、`s2t`、`t2s` 四类 AI service 抽象
- 业务目录通过 `--extra-app-paths` / `--extra-public-paths` 挂进框架的能力

## 快速开始

项目要求 Python 3.12 及以上。

```powershell
# 安装依赖
pip install -r requirements.txt

# 启动开发服务
python -m app --server-port 8000 --server-worker 1
```

启动后常用入口：

- `http://127.0.0.1:8000/`：站点根静态资源
- `http://127.0.0.1:8000/_internal/admin`：管理面板，默认只允许 localhost 访问
- `http://127.0.0.1:8000/_internal/admin/openapi.json`：OpenAPI JSON

生产模式通常显式加上：

```powershell
python -m app --production --server-port 8000 --server-worker 4
```

## 第一个 Route

```python
from core.server import Route


class HelloRoute(Route):
    Tags = "Demo"

    async def get(self, name: str = "world") -> dict[str, str]:
        return {"message": f"Hello, {name}!"}
```

把它放进 `app/api/hello.py` 后，重启服务即可访问：

```text
GET /api/hello?name=Kimi
```

完整上手流程见 [docs/getting-started.md](docs/getting-started.md)。

## 配置先看这一段

当前仓库不是单一配置文件模式，而是三套独立配置：

1. 服务主配置：`Config`
2. 存储配置：`StorageConfig`
3. AI 配置：`AIServicesConfig`

服务主配置使用嵌套结构，存储和 AI 配置也都是独立文件，不并入 `server.yaml`。具体字段、加载顺序、示例文件直接看 [docs/config/README.md](docs/config/README.md)。

如果你要找本地 `.env`、AI key、admin 密码和测试 env 的说明，统一看 [docs/setup.md](docs/setup.md)。

## 项目结构

```text
app/
  index.html        # 默认 Hello World 页面，可替换
  __main__.py       # 启动入口
core/
  ai/               # AI service 抽象与实现
  rtc_chat/         # RTC / chat 基础模块
  server/           # FastAPI app、Route、管理面板、共享状态
  storage/          # KV / ORM / Object / Vector
  utils/            # 通用工具
public/             # 公共静态资源，挂载到 /
config/             # 本地配置目录
docs/               # 开发文档
example/            # 示例项目
resources/
  admin-panel/      # internal 管理面板资源
scripts/            # 安装、运行、重启等脚本
test/               # 测试
tmp/                # 临时文件
```

## 示例项目

两个示例项目都通过启动脚本把自己的业务目录挂进框架：

```powershell
cd example/e-class
python run.py

cd example/e-shop
python run.py
```

它们内部都会传入：

- `--extra-app-paths <example>`
- `--extra-public-paths <example>/public`

默认端口分别是：

- `example/e-class/run.py` -> `19001`
- `example/e-shop/run.py` -> `19002`

## 测试

最常用的入口：

```powershell
python -m pytest test/server -v
python -m pytest test/storage -v
python -m pytest test/ai -v
```

不要用管道截断 pytest 输出。更完整的测试说明见 [docs/testing.md](docs/testing.md)。

## 文档索引

| 文档 | 用途 |
| ---- | ---- |
| [docs/framework.md](docs/framework.md) | 框架总览、启动方式、配置体系、示例项目入口 |
| [docs/getting-started.md](docs/getting-started.md) | 从环境准备到第一个 Route 的上手流程 |
| [docs/route.md](docs/route.md) | Route 自动发现、路径规则、元数据继承 |
| [docs/storage.md](docs/storage.md) | KV / ORM / Object / Vector 配置与使用 |
| [docs/ai.md](docs/ai.md) | completion / embedding / s2t / t2s 的配置与调用 |
| [docs/frontend.md](docs/frontend.md) | `public/`、`.m.html`、shared 组件、i18n |
| [docs/deployment.md](docs/deployment.md) | 生产启动、配置拆分、反向代理、容器化 |
| [docs/testing.md](docs/testing.md) | 测试目录、运行方式、外部依赖测试约束 |
| [docs/setup.md](docs/setup.md) | 本地开发环境、VS Code / Pylance、配置文件位置 |
| [docs/config/README.md](docs/config/README.md) | server / storage / AI 三套配置的职责与加载顺序 |

如果你要看具体示例配置，直接看：

- [docs/config/server_example.yaml](docs/config/server_example.yaml)
- [docs/config/storage_example.yaml](docs/config/storage_example.yaml)
- [docs/config/ai_services_example.yaml](docs/config/ai_services_example.yaml)
