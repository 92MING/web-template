# 快速入门

这一页只做一件事：把仓库拉起来，然后确认你已经能写出第一个 `Route`。

## 1. 准备 Python 环境

项目要求 Python 3.12 及以上。推荐使用独立环境：

```powershell
conda create -n proj-template python=3.12
conda activate proj-template
pip install -r requirements.txt
```

Windows 首次接手这个仓库时，建议顺手跑一次安装脚本，它会帮你检查一些本地工具链：

```powershell
python scripts/install.py
```

## 2. 启动服务

最小启动命令：

```powershell
python -m app --server-port 8000 --server-worker 1
```

启动后可以先确认这几个入口：

- `http://127.0.0.1:8000/`：站点首页，来自 `app/index.html` 或 `public/index.html`
- `http://127.0.0.1:8000/_internal/admin`：管理面板，默认只允许本机访问
- `http://127.0.0.1:8000/_internal/admin/openapi.json`：OpenAPI JSON

如果你想用配置文件启动，也可以：

```powershell
python -m app --config config/server.yaml
```

主配置文件的真实结构见 [config/server_example.yaml](config/server_example.yaml)。

## 3. 创建第一个 Route

新建 `app/api/hello.py`：

```python
from core.server import Route


class HelloRoute(Route):
    Tags = "Demo"

    async def get(self, name: str = "world") -> dict[str, str]:
        return {"message": f"Hello, {name}!"}
```

重启后访问：

```text
GET /api/hello?name=Kimi
```

返回应该类似：

```json
{"message": "Hello, Kimi"}
```

## 4. 理解 URL 是怎么来的

Route 的 URL 主要由文件路径和方法名共同决定：

```text
app/api/hello.py                -> /api/hello
app/api/users/__init__.py       -> /api/users
app/api/users/index.py          -> /api/users
app/api/users/_user_id_.py      -> /api/users/{user_id}
```

例如：

```python
from core.server import Route


class UserRoute(Route):
    async def get(self, user_id: str) -> dict[str, str]:
        return {"user_id": user_id}
```

如果它位于 `app/api/users/_user_id_.py`，那 URL 就是 `/api/users/{user_id}`。

## 5. 看看内置前端能力

前端不需要先上构建工具。默认就可以直接在 `public/` 下放页面：

- `app/index.html` 对应 `/`，用于应用自己的默认首页
- `public/about.html` 对应 `/about.html`
- `public/about.m.html` 会作为 `/about.html` 的移动端分支自动合并

如果你要写纯静态页、管理后台页或者小型前台站点，这套机制已经够用。详见 [frontend.md](frontend.md)。

## 6. 跑一下示例项目

两个示例项目都通过各自的 `run.py` 把业务目录挂进框架：

```powershell
cd example/e-class
python run.py

cd example/e-shop
python run.py
```

它们内部会自动传入：

- `--extra-app-paths <example>`
- `--extra-public-paths <example>/public`

这就是业务层和框架模板解耦的基本方式。

## 下一步

- [route.md](route.md)：把 Route 的路径规则、元数据继承、API key 权限都看清楚
- [storage.md](storage.md)：接入 KV / ORM / Object / Vector
- [ai.md](ai.md)：接入 completion / embedding / s2t / t2s
- [deployment.md](deployment.md)：把配置结构、生产启动和反向代理理顺
