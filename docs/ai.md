# AI 服务开发手册

框架内置四类 AI service：`completion`、`embedding`、`s2t`、`t2s`。

当前仓库的 AI 配置不是“每类一个 provider + model”的平铺结构，而是：

- 每个 service kind 自己维护一组本地 `clients`
- `default` 定义默认 service 实例
- 其他命名实例放在 `extras`，也可以直接写成顶层额外 key
- service 与 service 之间可以显式依赖，比如 `embedding.default.completion_service`、`s2t.default.completion_service`

## 四类能力与对应对象

| 能力 | 配置 section | 默认运行时对象 | 常用方法 |
| ---- | ------------ | -------------- | -------- |
| 文本/多模态补全 | `completion` | `CompletionService.Default()` | `complete()`、`stream_complete()`、`json_complete()`、`translate()`、`detect_language()` |
| 向量嵌入/重排/切块 | `embedding` | `EmbeddingService.Default()` | `embedding()`、`rerank()`、`chunking()`、`diversity_rerank()` |
| 语音转文本 | `s2t` | `S2TService.Default()` | `s2t()` |
| 文本转语音 | `t2s` | `T2SService.Default()` | `t2s()`、`t2s_stream()` |

要点：

- service kind 名称是 `s2t` / `t2s`，不是 `speech_to_text` / `text_to_speech`。
- 默认调用入口通常是各 Service 类的 `Default()`，不是 `AIServicesConfig.get_xxx_client()`。
- `AIServicesConfig.Global()` 负责加载配置；真正执行业务调用的是 `CompletionService`、`EmbeddingService`、`S2TService`、`T2SService`。

## 配置加载规则

`AIServicesConfig.Global()` 的加载顺序如下：

1. 环境变量 `__AI_SERVICES_CONFIG__`，值为完整 JSON。
2. 自动发现 `config/ai_services.{yaml,yml,json,toml}`。
3. 在服务运行态且 `__MODE__=dev|prod` 时，优先模式文件：`config/dev_ai_services.*` 或 `config/prod_ai_services.*`，然后再回退通用文件。
4. 如果没有找到任何配置，`AIServicesConfig.Global()` 返回 `None`。

这份配置不属于 `server.yaml`，而是由 `AIServicesConfig` 独立加载。

## 正确的配置结构

最小正确示例直接参考 [docs/config/ai_services_example.yaml](docs/config/ai_services_example.yaml)。

```yaml
completion:
  clients:
    openai:
      type: openai-completion
      api_key: ${OPENAI_API_KEY}
      model: gpt-4.1-mini

  default:
    clients:
      - openai

embedding:
  clients:
    openai:
      type: openai-embedding
      api_key: ${OPENAI_API_KEY}
      model: text-embedding-3-small

  default:
    clients:
      - openai

s2t:
  clients: {}
  default:
    completion_service: default

t2s:
  clients: {}
  default:
    clients: []
```

这个结构的含义是：

- `completion.clients.openai` 定义一个 completion 客户端配置，类型是 `openai-completion`。
- `completion.default.clients: [openai]` 表示默认 completion service 使用这个本地客户端。
- `embedding` 同理。
- `s2t.default.completion_service: default` 表示默认 S2T service 可以引用默认 completion service，把它适配为音频能力来源。

## 关键配置概念

### 1. client config

每个 `clients.<name>` 都是一个 `AIServiceClientInitData` 子类，至少包含：

- `type`: 注册过的客户端类型字符串，例如 `openai-completion`、`openai-embedding`
- `key`: 可选，运行时 client key
- `max_concurrent`: 并发限制
- `priority`: client 默认优先级
- `strategy_lvl`: client 默认切换等级
- 其他未知字段会自动进入 `kwargs`，透传给 client 构造函数

也就是说，这种写法是合法的：

```yaml
completion:
  clients:
    openai:
      type: openai-completion
      api_key: ${OPENAI_API_KEY}
      model: gpt-4.1-mini
      max_tokens: 32000
      max_concurrent: 16
```

其中 `api_key`、`model`、`max_tokens` 都会被收集并传给对应 client。

### 2. service init

`default` 和其他命名 service 的结构是 `AIServiceInitData` 或其子类，常见字段：

- `clients`: 客户端引用列表，既可以是字符串引用，也可以是 inline binding
- `fail_cooldown`: 故障冷却时间
- `recovery_interval`: 恢复探测间隔
- `kwargs`: 额外 service 初始化参数

支持短写：

- `default: openai`
- `default: [openai, backup]`
- `default: { clients: [openai] }`

三种写法最终都会规范化成 `clients` 列表。

### 3. binding 级调度覆盖

如果同一个真实 client 在某个 service 里想覆盖局部优先级，可以写 binding：

```yaml
completion:
  clients:
    openai:
      type: openai-completion
      api_key: ${OPENAI_API_KEY}
      model: gpt-4.1-mini

  default:
    clients:
      - client: openai
        priority: 0.5
        strategy_lvl: 1
```

这里的 `priority` / `strategy_lvl` 只作用于这个 service 绑定，不会改动底层 client 自身的默认值。

### 4. extras / 命名实例

除了 `default` 外，还可以定义多个命名 service。可以显式放进 `extras:`，也可以直接作为额外 key 写在当前 section 下，验证时会自动收进 `extras`。

```yaml
completion:
  clients:
    openai:
      type: openai-completion
      api_key: ${OPENAI_API_KEY}
      model: gpt-4.1-mini
    fast:
      type: openai-completion
      api_key: ${OPENAI_API_KEY}
      model: gpt-4.1-nano

  default:
    clients: [openai]

  summary:
    clients: [fast]
```

这里 `summary` 就是一个命名 completion service，可通过 `cfg.completion.get_service("summary")` 或 `CompletionService.GetInstance("summary")` 使用。

## 不能再这样写

当前仓库中，下列旧写法是不对的：

- 顶层 `clients:` 已被移除，必须改成 `completion.clients` / `embedding.clients` / `s2t.clients` / `t2s.clients`
- `speech_to_text:`、`text_to_speech:` 不是有效 section 名称
- `AIServicesConfig.Global().get_completion_client()` 这类接口不存在
- `complete()` 的默认返回值是字符串，不是 `response.text`
- `embedding` 的主方法名是 `embedding()`，不是 `embed()`
- `s2t` / `t2s` 的主方法名分别是 `s2t()` / `t2s()`，不是 `transcribe()` / `synthesize()`

## 在业务代码中使用

最常见做法是直接拿默认 service：

```python
from fastapi import Body

from core.ai import CompletionService
from core.server import Route


class ChatRoute(Route):
    async def post(self, message: str = Body(...)) -> dict[str, str]:
        service = CompletionService.Default()
        reply = await service.complete(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": message},
            ],
        )
        return {"reply": reply}
```

如果你确实需要先拿配置对象，也应该这样用：

```python
from core.ai import AIServicesConfig


cfg = AIServicesConfig.Global()
if cfg is None:
    raise RuntimeError("AI services config is missing")

completion_service = cfg.completion.get_default()
embedding_service = cfg.embedding.get_default()
```

## Completion 的正确用法

`CompletionService.complete()` 默认返回 `str`。如果需要完整结构，传 `full_output=True`。

```python
from core.ai import CompletionService


service = CompletionService.Default()

text = await service.complete(
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ],
    temperature=0.7,
)

full = await service.complete(
    full_output=True,
    messages=[{"role": "user", "content": "Return JSON only"}],
)
```

Completion service 还提供很多高层能力：

- `stream_complete()`
- `json_complete()`
- `translate()`
- `detect_language()`
- `ocr()` / `asr()` / `summarize()` 等高阶封装

## Embedding 的正确用法

Embedding 主方法是 `embedding()`：

```python
from core.ai import EmbeddingService


service = EmbeddingService.Default()
vectors = await service.embedding(["Hello world", "Good morning"])
```

除基础向量化外，还支持：

- `rerank()`
- `chunking()`
- `diversity_rerank()`

并且 `EmbeddingService` 可配置引用 `completion_service` 和 `s2t_service`，用于 OCR / ASR / 多模态回退。

## S2T 的正确用法

S2T 主方法是 `s2t()`，返回字符串：

```python
from core.ai import S2TService
from core.models import Audio


service = S2TService.Default()
audio = Audio.from_path("audio.mp3")
text = await service.s2t(audio)
```

如果 `s2t.default` 里配置了 `completion_service`，框架会把对应 completion service 适配成 S2T 能力来源。

## T2S 的正确用法

T2S 主方法是 `t2s()`，返回 `Audio`；如果要流式输出字节，使用 `t2s_stream()`。

```python
from core.ai import T2SService


service = T2SService.Default()
audio = await service.t2s("Hello world")

chunks = []
async for chunk in service.t2s_stream("Hello world"):
    chunks.append(chunk)
```

## 运行时实例与命名 service

配置驱动创建后，service 实例会按 key 缓存。常用取法：

```python
from core.ai import CompletionService


default_service = CompletionService.Default()
same_instance = CompletionService.GetInstance("default")
summary_service = CompletionService.GetInstance("summary")
```

如果 `summary` 还没创建，但配置里存在，可以先通过 `AIServicesConfig.Global().completion.get_service("summary")` 触发实例化。

## Admin / Public AI 路由

AI HTTP API 的实际暴露规则由服务端配置决定：

- 管理侧 AI 接口始终注册在 `server_config.internal_path_prefix` 下，默认是 `/_internal/ai/*`
- `server_config.expose_ai_service` 为真时，只会额外公开带 public 标记的 AI 业务接口到 `/ai/*`
- `/ai/services` 不公开；service/client 管理信息只走 `/_internal/ai/services*`

常见端点包括：

- `GET /_internal/ai/services`
- `POST /_internal/ai/complete`，可按配置公开为 `POST /ai/complete`
- `POST /_internal/ai/embedding`，可按配置公开为 `POST /ai/embedding`
- `POST /_internal/ai/s2t`，可按配置公开为 `POST /ai/s2t`
- `POST /_internal/ai/t2s`，可按配置公开为 `POST /ai/t2s`

管理面板页本身走另一套前缀：

- `/_internal/admin/ai-services/overview`
- `/_internal/admin/ai-services/settings`

## 健康状态与共享上下文

框架会维护 service/client 的运行时状态，并通过 AI 面板和 `/_internal/ai/services/*` 系列接口暴露聚合信息。与 AI 相关的共享上下文优先使用存储里的 `kv.ai_services_context` client；若未配置，则回退到默认 KV。

## 配置排查建议

1. 先看 [docs/config/ai_services_example.yaml](docs/config/ai_services_example.yaml)，不要从旧版 `provider/model` 文档脑补结构。
2. 如果 `AIServicesConfig.Global()` 返回 `None`，先检查是否真的存在 `config/ai_services.*` 或 `__AI_SERVICES_CONFIG__`。
3. 如果报 `top-level clients 已移除`，说明你还在用旧配置格式。
4. 如果某个 service 没建起来，先确认该 service 的 `clients` 引用是否能在本 section 的 `clients` 中解析到。
