# 测试开发指南

这份测试说明只基于当前仓库已经存在的测试目录与辅助基类来写。

## 先看测试目录

当前顶层测试目录主要是：

```text
test/
  ai/
  core/
  server/
  storage/
  utils/
```

其中最常见的是：

- `test/server/`：FastAPI 路由、管理面板、公开接口、存储 API 面板接口
- `test/storage/`：更底层的存储集成与后端能力测试
- `test/ai/`：AI service 相关测试
- `test/utils/`：工具层测试

## 最常用的运行方式

```powershell
# server 测试
python -m pytest test/server -v

# storage 测试
python -m pytest test/storage -v

# AI 测试
python -m pytest test/ai -v

# 单个文件
python -m pytest test/server/test_route_loader.py -v

# 单个用例关键字
python -m pytest test/server/test_storage_kv_api_redis.py -k config -v
```

如果只是快速回归，也可以把目标缩小到当前改动附近，不要动不动全量跑。

## 关于 pytest 输出

这个仓库有一条很重要的约束：

- 不要用管道截断 pytest 输出。
- 不要把 pytest 输出重定向成看不到实时进度的形式。

也就是说，下面这种做法不要用：

```powershell
python -m pytest test/server -v | Select-Object -First 20
```

如果你是在 VS Code 里通过自动化代理跑长测试，应当异步启动终端命令，然后持续查看完整输出，而不是截断它。

## 当前仓库里常见的两类测试

### 1. 进程内 ASGI 测试

这类测试通常直接用 `httpx.ASGITransport` 跑 FastAPI app，不需要额外起 uvicorn 进程。

在 `test/server/_test_helpers.py` 里已经提供了很多可复用的基类，例如：

- `FullAppTestBase`
- `StorageKVTestBase`
- `StorageORMTestBase`
- `StorageObjectTestBase`
- `StorageVectorTestBase`

这类测试适合覆盖：

- Route 注册结果
- 请求参数和响应结构
- 管理面板 API 行为
- 存储面板接口的 CRUD 语义

### 2. 真实后端依赖集成测试

这类测试会连真实的 Redis、MongoDB、PostgreSQL、MinIO、Milvus 等服务，主要分布在：

- `test/server/test_storage_*`
- `test/storage/`

典型例子：

- `test/server/test_storage_kv_api_redis.py`
- `test/server/test_storage_orm_api_postgresql.py`
- `test/server/test_storage_object_api_minio.py`
- `test/server/test_storage_vector_api_milvus.py`
- `test/storage/test_minio_object_integration.py`

这类测试的前提不是“pytest 能跑”，而是对应后端真的可连。

## Docker 与外部依赖

如果你用 Docker 起外部依赖，最重要的不是“起起来”，而是“测完要停掉”。

常见最小命令示例：

```powershell
# Redis
docker run -d -p 6379:6379 redis:8

# PostgreSQL
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16

# MongoDB
docker run -d -p 27017:27017 mongo:7
```

Milvus、MinIO 这类依赖通常需要更完整的启动参数或 compose 文件，建议按具体测试文件需求准备。

测试结束后，务必停止并清理容器，避免持续占内存和端口。

## 命名约定

当前仓库里需要记住的约定很简单：

| 形式 | 含义 |
| ---- | ---- |
| `test_*.py` | 自动收集的测试 |
| `run_*.py` | 人工场景脚本，手动执行 |
| `stress_*.py` | 压测脚本，手动执行 |

## 实际编写测试时的建议

1. 先选对层级。路由行为问题先写 `test/server`，底层存储语义问题再去 `test/storage`。
2. 能复用 `test/server/_test_helpers.py` 里的基类，就不要重复手写环境初始化。
3. 验证多 worker 语义时，再显式使用 `worker >= 2` 的真实服务场景；不要把这个要求机械地套到所有测试上。
4. 不要为了让旧测试通过而改坏当前后端行为。先判断是代码回归，还是测试已经过时。
