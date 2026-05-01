# 配置说明

这个仓库的配置要分成三层看：

1. 服务主配置
2. 存储配置
3. AI services 配置

它们不是一个模型，也不共享同一个配置文件。

## 1. 服务主配置

服务主配置由 `Config` 负责，里面当前只有三个子配置：

- `server_config`
- `log_config`
- `rtc_room_config`

### 服务主配置加载方式

- 显式传 `--config <path>` 时，按该路径读取。
- 未传时，会优先尝试模式文件：`config/dev_server.{yaml,yml,json,toml}` 或 `config/prod_server.{yaml,yml,json,toml}`。
- 如果模式文件不存在，再回退到 `config/server.{yaml,yml,json,toml}`。
- 如果都不存在，就用内置默认值启动。

### 结构示意

```yaml
server_config:
   host: 127.0.0.1
   port: 8000
   worker: 1

log_config:
   log_method:
      - db

rtc_room_config:
   enable_rtc_chatroom: false
   audio_sample_rate: 16000
```

完整示例见 [server_example.yaml](server_example.yaml)。

### 写回路径

`Config.write_to_path()` 默认会写到：

```text
config/server.yaml
```

## 2. 存储配置

存储配置由 `StorageConfig` 单独负责，不属于服务主配置文件。

### 存储配置作用范围

- `kv`
- `orm`
- `vector`
- `object`

### 存储配置加载方式

- 环境变量 `__STORAGE_CONFIG__`
- 模式优先文件 `config/dev_storage.*` 或 `config/prod_storage.*`
- 通用文件 `config/storage.*`
- 如果都没有，则四个 section 各自使用默认值

### 存储配置说明

- CLI 不会自动把存储配置塞进 `server.yaml`。
- 常规部署直接让 `StorageConfig.Global()` 自动发现即可。
- 只有非常特殊的场景才需要 `--storage-config-json`。

完整示例见 [storage_example.yaml](storage_example.yaml)。

## 3. AI services 配置

AI 配置由 `AIServicesConfig` 单独负责，也不属于服务主配置文件。

### AI 配置作用范围

- `completion`
- `embedding`
- `s2t`
- `t2s`

### AI 配置加载方式

- 环境变量 `__AI_SERVICES_CONFIG__`
- 自动发现 `config/ai_services.*`
- 通过 CLI 显式传 `--ai-services-config <path>` 或内联 JSON

### AI 配置说明

- 如果没有任何 AI 配置，`AIServicesConfig.Global()` 可以返回 `None`。
- 这不影响服务主配置本身的加载。

完整示例见 [ai_services_example.yaml](ai_services_example.yaml)。

## 4. 怎么选对文件

推荐的职责边界：

- 服务监听、管理面板、日志、RTC 参数：放服务主配置
- 数据库、对象存储、向量库：放存储配置
- 模型、provider、service 绑定：放 AI 配置

不要再把：

- `host`
- `port`
- `internal_path_allowed_ip`
- `completion`
- `kv`

这些字段混写进同一个旧式平铺 YAML 里。
