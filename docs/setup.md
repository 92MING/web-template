# 开发环境设置

这一页只讲当前仓库接手后最先要做的几件事：选 Python 环境、装依赖、配 VS Code、确认配置目录。

## 1. 选择 Python 环境

项目要求 Python 3.12 及以上，建议使用独立环境：

```powershell
conda create -n proj-template python=3.12
conda activate proj-template
pip install -r requirements.txt
```

Windows 下第一次接手仓库时，建议运行：

```powershell
python scripts/install.py
```

它会帮助检查和安装部分本地依赖工具。

## 2. VS Code 建议设置

至少要让 Pylance 能正确解析 `app/` 下的包。

可以在工作区设置里加入：

```json
{
  "python.analysis.extraPaths": [
    "${workspaceFolder}/app"
  ]
}
```

如果你用的是多环境工作流，还要确认 VS Code 当前选中的解释器就是这个项目的 Python 环境。

## 3. 配置文件放哪

当前仓库有三套独立配置，不要混在一起：

- 服务主配置：`config/server.yaml`，或者 `config/dev_server.yaml` / `config/prod_server.yaml`
- 存储配置：`config/storage.yaml`
- AI 配置：`config/ai_services.yaml`

详细结构见：

- [config/README.md](config/README.md)
- [config/server_example.yaml](config/server_example.yaml)
- [config/storage_example.yaml](config/storage_example.yaml)
- [config/ai_services_example.yaml](config/ai_services_example.yaml)

## 4. 环境变量文件

`app/__main__.py`（通过 `python -m app`）会自动尝试加载：

- `.env`
- `.env.dev` / `.env.development`
- `.env.prod` / `.env.production`

所以本地开发通常会准备：

```text
.env
.env.dev
```

建议把“所有环境共用的密钥”放进 `.env`，把“只在本机开发时才启用的覆盖项”放进 `.env.dev`。

## 5. 当前仓库实际在用的公开 env

下面这些是当前代码里真实会读取、并且适合开发者配置的 env；内部 `__XXX__` runtime env 不在这里展开。

### 5.1 管理后台与鉴权

- `ADMIN_PW`：管理面板登录密码。未设置时，服务启动会生成一次性临时密码。
- `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`：JWT RS256 密钥对；若 `.env` 和进程 env 都没提供，启动时会自动生成并写回 `.env`。

### 5.2 AI provider

- `TTS_APIKEY` / `TTS_API_BASEURL`：ThinkThinkSyn completion/TTS 相关默认 client。
- `OPENROUTER_API_KEY` / `OPENROUTER_API_URL`：OpenRouter 默认 client。
- `OPENROUTER_MODEL` / `OPENROUTER_MODEL_FILTER`：OpenRouter 默认模型筛选。
- `OPENROUTER_HTTP_REFERER` / `OPENROUTER_X_TITLE`：OpenRouter 请求头透传。
- `OPENAI_APIKEY` / `OPENAI_API_KEY`：OpenAI-like client API key。
- `OPENAI_API_URL` / `OPENAI_BASE_URL`：OpenAI-like client base URL。

### 5.3 Server 直接 env 覆盖

这些 env 是 `ServerConfig` 直接读取的快捷覆盖入口；长期配置仍建议写 `config/server.yaml`。

- `HOST` / `PORT`
- `DEV_PORT` / `PROD_PORT`
- `WORKER` / `RELOAD`
- `FRONTEND_BASEURL`
- `EXPOSE_AI_SERVICE`
- `EXPOSE_INTERNAL_PREFIX`
- `INTERNAL_PATH_ALLOWED_IP`
- `FORCE_EXIT_TIMEOUT`
- `SYSTEM_ALLOWED_ROOTS`
- `SYSTEM_DEFAULT_ROOT`
- `SYSTEM_TERMINAL_DEFAULT_CWD`
- `SYSTEM_TERMINAL_MAX_SESSIONS`

### 5.4 本地工具与文档处理

- `SOFFICE_PATH`：显式指定 LibreOffice `soffice` 路径。
- `ENABLE_OFFICE_COM`：Windows 下允许 `.doc` / `.ppt` 通过 Office COM 做转换。
- `SSH_KEY_PATH`：`core.utils.network_utils.ssh_tunnel` 默认 SSH 私钥路径。
- `XELATEX_PATH` / `DVISVGM_PATH` / `PDFTOPPM_PATH`：本地 TeX / PDF 工具路径覆盖，安装脚本会检查这些值。

### 5.5 测试相关 env

直接跑外部依赖集成测试时，当前仓库主要读取两组测试 env：

- `TEST_MONGO_URL`
- `TEST_REDIS_URL`
- `TEST_MINIO_ENDPOINT` / `TEST_MINIO_ACCESS_KEY` / `TEST_MINIO_SECRET_KEY`
- `TEST_MILVUS_URI` / `TEST_MILVUS_TOKEN`
- `TEST_POSTGRES_HOST` / `TEST_POSTGRES_PORT` / `TEST_POSTGRES_USER` / `TEST_POSTGRES_PASSWORD`
- `TEST_ETCD_HOST` / `TEST_ETCD_PORT`
- `EMBEDDING_CACHE_DB`

另外，`test/server/_test_helpers.py` 现在还保留了一组单独的 server 测试 env：

- `PROJ_TEST_MONGO_URL`
- `proj_test_MILVUS_URI` / `proj_test_MILVUS_TOKEN`
- `proj_test_ETCD_PORT`
- `proj_test_MYSQL_PORT` / `proj_test_MYSQL_USER` / `proj_test_MYSQL_PASSWORD`
- `proj_test_POSTGRES_PORT` / `proj_test_POSTGRES_USER` / `proj_test_POSTGRES_PASSWORD`
- `proj_test_MINIO_ENDPOINT` / `proj_test_MINIO_ACCESS_KEY` / `proj_test_MINIO_SECRET_KEY`

## 6. 启动自检

环境就绪后，至少跑一次：

```powershell
python -m app --server-port 8000 --server-worker 1
```

如果能正常打开：

- `/`
- `/_internal/admin`
- `/_internal/admin/openapi.json`

说明开发环境已经基本就绪。
