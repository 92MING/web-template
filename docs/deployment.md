# 部署指南

这一页只覆盖当前仓库已经存在且可以落地的部署面：服务启动、主配置结构、AI/存储配置拆分、反向代理和容器化。

## 1. 最小生产启动

推荐直接从 CLI 起服务：

```powershell
python -m app --production --server-port 8000 --server-worker 4
```

说明：

- 生产模式建议显式带 `--production`。
- CLI 参数名是 `--server-host`、`--server-port`、`--server-worker`。
- 开发态才建议使用 `--server-reload`；生产环境不要开。
- `internal_path_allowed_ip` 一定要收紧，否则 internal 管理入口会直接暴露给不该访问的人。

## 2. 主配置文件结构

服务主配置不是平铺结构，而是 `Config` 根模型，下面至少包含：

- `server_config`
- `log_config`
- `rtc_room_config`

一个可用的最小示例：

```yaml
server_config:
  host: 0.0.0.0
  port: 8000
  worker: 4
  reload: false
  internal_path_prefix: /_internal
  expose_internal_prefix: true
  internal_path_allowed_ip:
    - 10.0.*
  expose_ai_service: false
  enable_rtc_chatroom: false

log_config:
  log_method:
    - db

rtc_room_config:
  audio_sample_rate: 16000
  min_silence_ms: 1000
  min_voice_ms: 200
  mid_silence_ms: 500
  max_segment_ms: 10000
  min_energy_rms: 200
  bundle_policy: balanced
```

对应的完整示例见 [config/server_example.yaml](config/server_example.yaml)。

## 3. 主配置的发现顺序

如果不显式传 `--config`，服务会自动寻找这些文件：

1. `config/dev_server.{yaml,yml,json,toml}` 或 `config/prod_server.{yaml,yml,json,toml}`
2. `config/server.{yaml,yml,json,toml}`

如果都不存在，就直接用内置默认值启动。

显式指定配置文件：

```powershell
python -m app --config config/server.yaml
```

## 4. AI 与存储配置是分开的

这是当前仓库最容易写错的地方。

### AI services

AI 配置不在 `server.yaml` 里。它由 `AIServicesConfig` 单独加载，可以：

- 走自动发现 `config/ai_services.*`
- 用 `--ai-services-config <path>` 指定文件
- 用 `--ai-services-config <json>` 直接传内联 JSON

例如：

```powershell
python -m app --production --ai-services-config config/ai_services.yaml
```

### Storage

存储配置也不在 `server.yaml` 里。正常情况直接让 `StorageConfig.Global()` 自动发现 `config/storage.*` 即可。

只有在非常特殊的启动场景，才需要用：

```text
--storage-config-json
```

来传整套 JSON 覆盖。

## 5. 常用服务级开关

当前 `server_config` 和 CLI 中最常用的部署开关有这些：

| 项目 | 配置键 | CLI | 环境变量 |
| ---- | ------ | --- | -------- |
| 监听地址 | `server_config.host` | `--server-host` | `HOST` |
| 监听端口 | `server_config.port` | `--server-port` | `PORT` |
| worker 数 | `server_config.worker` | `--server-worker` | `WORKER` |
| 自动重载 | `server_config.reload` | `--server-reload` | `RELOAD` |
| internal 前缀 | `server_config.internal_path_prefix` | `--internal-path-prefix` | `INTERNAL_PATH_PREFIX` |
| internal 路由暴露 | `server_config.expose_internal_prefix` | `--expose-internal-prefix` / `--hide-internal-prefix` | `EXPOSE_INTERNAL_PREFIX` |
| internal IP 白名单 | `server_config.internal_path_allowed_ip` | `--internal-path-allowed-ip` | `INTERNAL_PATH_ALLOWED_IP` |
| AI 公开别名 | `server_config.expose_ai_service` | `--expose-ai-service` | `EXPOSE_AI_SERVICE` |
| RTC chatroom | `server_config.enable_rtc_chatroom` | `--enable-rtc-chatroom` / `--disable-rtc-chatroom` | `ENABLE_RTC_CHATROOM` |
| 额外 app 目录 | `server_config.extra_app_paths` | `--extra-app-paths` | 无 |
| 额外 public 目录 | `server_config.extra_public_paths` | `--extra-public-paths` | 无 |
| 额外 resources 目录 | `server_config.extra_resources_paths` | `--extra-resources-paths` | 无 |

## 6. 反向代理

Nginx 最小示例：

```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

要注意的是，当前 admin IP 限制判断的是 `request.client.host`。如果你把服务放在反向代理后面，通常有两种做法：

1. `internal_path_allowed_ip` 只允许反向代理所在内网地址。
2. `internal_path_allowed_ip` 设为 `all`，但在 Nginx 层自己做更严格的访问控制。

## 7. Docker

一个最简单可用的 Dockerfile：

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "-m", "app", "--production", "--server-host", "0.0.0.0", "--server-port", "8000", "--server-worker", "4"]
```

如果你用 compose，至少要把配置目录和需要持久化的资源目录挂出来。

## 8. 日志与管理面板

日志系统由 `log_config` 控制，当前常见模式是：

- `db`：写入 ORM 日志存储
- `file`：写入磁盘文件
- 两者可同时开启

默认 `log_method` 是 `db`。如果你要把日志写进文件，至少还要关心：

- `log_path`
- `log_backup_count`
- `log_rotation_interval`
- `rotation_time`
- `zip_old_logs`

管理面板可以直接查看不少运行态信息，因此生产环境一定要同时处理好：

- `expose_internal_prefix`
- `internal_path_allowed_ip`
- 反向代理层访问控制
