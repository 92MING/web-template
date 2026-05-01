# 存储开发手册

框架内置四类存储抽象：`kv`、`orm`、`vector`、`object`。业务代码统一通过 `StorageConfig.Global()` 获取命名 client；配置由存储系统独立加载，不走 `server.yaml`。

## 四类存储分别做什么

| 类别 | 适合场景 | 典型 API | 支持后端 |
| --- | --- | --- | --- |
| `kv` | 会话、缓存、轻量状态 | `set`、`get`、`delete`、`keys`、`open_namespace` | `sqlite`、`redis`、`etcd` |
| `orm` | 结构化业务记录、日志、指标 | `save`、`Search`、`SearchOne`、`SelectedSearch`、`Delete` | `sqlite`、`sql`、`mongo`、`postgresql`、`mysql`、`redis` |
| `vector` | 向量检索、语义搜索、embedding 文档 | `save`、`Search`、`SearchVector`、`Delete` | `annoy`、`milvus-lite`、`milvus`、`redis`、`mongo` |
| `object` | 文件、二进制对象、上传产物 | `put_bytes`、`put_file`、`get_bytes`、`search`、`delete` | `local`、`minio` |

要点：

- `kv` 是 key-value，不是表结构。
- `orm` 走 `ORMModel`，默认按 collection/model 懒创建。
- `vector` 不是“普通 dict + upsert/search(top_k)”接口，推荐直接用 `VectorORMModel`。
- `object` 管的是对象和元数据，取字节优先用 `get_bytes()`，`get()` 返回的是异步字节流。

## 配置加载规则

`StorageConfig.Global()` 的自动发现顺序与 [docs/config/storage_example.yaml](docs/config/storage_example.yaml) 一致：

1. 环境变量 `__STORAGE_CONFIG__`，值为完整 JSON。
2. `config/dev_storage.{yaml,yml,json,toml}` 或 `config/prod_storage.{yaml,yml,json,toml}`。
3. `config/storage.{yaml,yml,json,toml}`。
4. 若未找到配置文件，则四个 section 各自按默认值启动。

默认值：

- `kv.default`: `sqlite`
- `orm.default`: `sqlite`
- `object.default`: `local`
- `vector.default`: Windows 下默认 `annoy`，其他平台默认 `milvus-lite`

注意：存储配置会从当前工作目录和项目根目录下的 `config/` 自动发现；它与 `server.yaml` 是两套独立配置。

## 正确的配置文件结构

推荐直接参考 [docs/config/storage_example.yaml](docs/config/storage_example.yaml)。一个最小但正确的示例如下：

```yaml
kv:
  default:
    type: sqlite
    namespace: server
    db_path: tmp/storage/kv.sqlite3
  cache:
    type: redis
    namespace: server_cache
    url: redis://127.0.0.1:6379/1
    default_expire: 3600

orm:
  default:
    type: sqlite
    namespace: server
    db_path: tmp/storage/orm.sqlite3
  log:
    type: sqlite
    namespace: server_logs
    db_path: tmp/storage/log.sqlite3

vector:
  default:
    type: annoy
    namespace: server
    db_dir: tmp/storage/vector
    metric_type: COSINE

object:
  default:
    type: local
    root_path: tmp/storage/objects
    metadata_db:
      type: sqlite
      namespace: server_objects_meta
      db_path: tmp/storage/objects_meta.sqlite3
  temp_file_upload:
    type: local
    root_path: tmp/storage/uploads
    metadata_db: default
```

字段要点：

- `kv.sqlite` 用 `db_path`，不是 `url`。
- `orm.sqlite` 用 `db_path`；`sql/postgresql/mysql/mongo/redis` 才使用 `url` 或各自连接字段。
- `object.local` 用 `root_path`，不是 `base_dir`。
- `object.metadata_db` 可以写成内联 KV 配置，也可以直接写成某个 KV client 名称，例如 `default` 或 `meta`。
- `vector.annoy` 用 `db_dir`；`vector.milvus-lite` 用 `db_path`；`vector.milvus` 用 `uri`。

## 命名 client 与 fallback

四类 section 都支持命名 client：

- 固定槽位：`default`、`cache`
- 内建命名槽位：
  - `kv`: `file_metadata`、`ai_services_context`
  - `orm`: `log`、`system_metrics`、`service_record`、`embedding_cache`、`content_analyzer`、`project_records`
  - `object`: `temp_file_upload`、`project_assets`
  - `vector`: 只有 `default`、`cache`
- 额外自定义 client 可以直接写在 section 下，也可以放到 `extra:` 里；解析后都会进入命名 client 集合。

client 解析规则：

1. 先按名字精确匹配。
2. 再做模糊匹配，忽略大小写、下划线、短横线。
3. 再走 `fallback`。
4. 最后退回 `default`。

另外，`default` 和 `cache` 会互相补齐：只配了一个时，另一个会自动复用它。

## 环境变量怎么配

环境变量只覆盖各 section 的默认 client，前缀如下：

- `STORAGE_KV_DB_*`
- `STORAGE_ORM_DB_*`
- `STORAGE_VECTOR_DB_*`
- `STORAGE_OBJECT_DB_*`

例如：

```powershell
$env:STORAGE_KV_DB_TYPE = 'sqlite'
$env:STORAGE_KV_DB_NAMESPACE = 'server'
$env:STORAGE_KV_DB_DB_PATH = 'tmp/storage/kv.sqlite3'

$env:STORAGE_OBJECT_DB_TYPE = 'local'
$env:STORAGE_OBJECT_DB_ROOT_PATH = 'tmp/storage/objects'
```

不要再使用这类并不存在的键名：

- `KV_DEFAULT_TYPE`
- `ORM_DEFAULT_URL`
- `VECTOR_DEFAULT_TYPE`

如果要一次性覆盖整套命名 client，请使用 `__STORAGE_CONFIG__`，而不是拼一组旧文档风格的环境变量。

## 在业务代码中获取 client

```python
from core.storage import StorageConfig
from core.server import Route


class ItemRoute(Route):
    async def init(self, app):
        await super().init(app)
        storage = StorageConfig.Global()
        self.kv = storage.get_kv_client()
        self.orm = storage.get_orm_client()
        self.vector = storage.get_vector_client()
        self.object = storage.get_object_client()
        self.uploads = storage.object.get_temp_file_upload()
```

获取命名 client：

```python
storage = StorageConfig.Global()

cache_kv = storage.get_kv_client("cache")
log_orm = storage.get_log_orm_client()
upload_object = storage.object.get_temp_file_upload()
analytics_vector = storage.get_vector_client("analytics", fallback="default")
```

## KV 的正确用法

KV client 保存任意可序列化对象，并支持 TTL 与 namespace。

```python
kv = StorageConfig.Global().get_kv_client("default")

await kv.set("session:123", {"user_id": 42}, expire=3600)
session = await kv.get("session:123")

await kv.set("profile:1", {"name": "Alice"})
profile = await kv.get("profile:1", target_type=dict)

keys = await kv.keys(prefix="session:")
deleted = await kv.delete("session:123")
```

分层 namespace：

```python
user_sessions = kv.open_namespace("user_sessions")
await user_sessions.set("token-1", {"role": "admin"})
value = await user_sessions.get("token-1")
```

说明：

- `expire` 是秒数，也可以传绝对时间戳。
- `get(..., target_type=T)` 会尝试反序列化为指定类型；失败时返回原始值。
- `keys()` 的筛选参数叫 `prefix`，不是 shell 风格通配表达式。

## ORM 的正确用法

ORM 以 `ORMModel` 为核心，常用入口是模型自己的 `save()`、`Search()`、`Delete()`。

```python
from core.storage.orm import ORMModel


class User(ORMModel, collection_name="users"):
    name: str
    email: str
    age: int = 0


user = User(name="Alice", email="a@example.com", age=30)
await user.save()

rows = [item async for item in User.Search({"name": "Alice"})]
one = await User.SearchOne({"email": "a@example.com"})
selected = [item async for item in User.SelectedSearch({"age": 30}, fields=("name", "email"))]

user.age = 31
await user.save()

await user.delete()
await User.Delete({"name": "Alice"})
```

说明：

- 这个仓库的主接口不是 `create_table()` / `find()` / `orm.save(model_class)`。
- collection 会在首次保存时按需创建，`save(create_collection=True)` 默认已开启。
- `Search()` 和 `SelectedSearch()` 返回异步生成器，不是 list。

## Object 的正确用法

Object client 管理对象内容和元数据。取完整字节时优先用 `get_bytes()`；需要流式读取才用 `get()`。

```python
obj = StorageConfig.Global().get_object_client("default")

meta = await obj.put_bytes(
    b"hello object storage",
    object_name="docs/hello.txt",
    metadata={"topic": "demo", "lang": "en"},
    content_type="text/plain",
)

data = await obj.get_bytes("docs/hello.txt")

matches = [
    item async for item in obj.search(
        name="hello",
        path_prefix="docs/",
        metadata={"topic": "demo"},
    )
]

paths = [path async for path in obj.list_objects("docs/")]
await obj.set_expire("docs/hello.txt", 3600)
await obj.delete("docs/hello.txt")
```

说明：

- `put()` / `put_bytes()` 都要求用关键字参数传 `object_name`。
- `list_objects()`、`search()`、`list_metadata()` 都返回异步生成器。
- `object.local` 通常还要配 `metadata_db`，否则对象元数据无法独立检索。

## Vector 的正确用法

Vector 存储推荐使用 `VectorORMModel` + `VectorORMField`，而不是手写“创建索引 / upsert / top_k”式伪接口。

```python
from core.storage.vector import VectorIndex, VectorORMField, VectorORMModel


def fake_embed(text: str) -> list[float]:
    return [1.0, 0.0]


class DocChunk(VectorORMModel, collection_name="doc_chunks"):
    title: str = ""
    category: str = ""
    embedding: list[float] = VectorORMField(
        default_factory=list,
        index=VectorIndex(dim=2, embedder=fake_embed),
    )


item = DocChunk(title="Alpha", category="math", embedding=[1.0, 0.0])
await item.save()

rows = [item async for item in DocChunk.Search({"category": "math"})]

nearest = [
    item async for item in DocChunk.SearchVector(
        [1.0, 0.0],
        field="embedding",
        limit=5,
        query={"category": "math"},
    )
]

await item.delete()
```

说明：

- 向量索引定义在 `VectorORMField(..., index=VectorIndex(...))` 上。
- 标量过滤走 `Search()`，向量近邻检索走 `SearchVector()`。
- 如果直接拿 client，则方法名是 `set()`、`search()`、`search_vector()`、`delete()`，不是 `upsert()` 或 `search(top_k=...)`。

## 后端类型速查

```yaml
kv.type: sqlite | redis | etcd
orm.type: sqlite | sql | mongo | postgresql | mysql | redis
vector.type: annoy | milvus-lite | milvus | redis | mongo
object.type: local | minio
```

如需完整配置字段，请直接对照 [docs/config/storage_example.yaml](docs/config/storage_example.yaml) 与 [core/storage/config.py](../core/storage/config.py)。
