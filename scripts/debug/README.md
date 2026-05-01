# scripts/debug/

调试用的通用 Python 脚本(主要基于 Playwright)。这些脚本设计成你随时可以一行命令搞定的"我现在要看一眼这个页面/截个图/批量发现 JS 错误"等需求,无需重复写 boilerplate。

## 启动条件

- 安装 Playwright: `pip install playwright`,首次跑会自动 `playwright install chromium`。
- gallery 服务: `python example/gallery/run.py --server-port 19003 --server-worker 2`。

## 文件

### `playwright_helpers.py`

通用 Playwright 工具库 + CLI。

| 命令 | 作用 |
|---|---|
| `screenshot --url URL --out PATH [--dark] [--lang zh\|en] [--viewport WxH]` | 打开 URL,可选切深色/语言,然后整页截图。 |
| `click-shot --url URL --selector SEL --out PATH [--dark]` | 打开 URL,点击 selector,再截图。 |
| `audit --base http://127.0.0.1:19003 --pages-from example/gallery/public/pages` | 批量访问目录下所有 `.html`,收集 JS 错误/console error/失败请求,写入 `tmp/debug/audit.json`。 |
| `token --port 19211` | 用项目 `.env` 里的 `ADMIN_PW` 自动登录,打印 admin api_key。 |

代码层 API:

```python
from scripts.debug.playwright_helpers import BrowserSession, take_screenshot, audit_pages

# 单图
await take_screenshot("http://127.0.0.1:19003/", "tmp/debug/home.png", dark=True, lang="zh")

# 自定义流程
async with BrowserSession(viewport=(375, 812)) as sess:  # iPhone 尺寸
    await sess.goto_with_report("http://127.0.0.1:19003/pages/")
    await sess.set_dark_mode(True)
    await sess.set_lang("zh")
    await sess.screenshot("tmp/debug/mobile-zh-dark.png")
```

`BrowserSession` 自带:
- 失败的 picsum / pravatar / unsplash 请求会被忽略,不污染报告。
- `set_dark_mode(bool)` / `set_lang("en"|"zh")` 直接调底层 shell。
- `bearer=` 参数会自动在所有请求带上 `Authorization`(用于 admin API 调试)。

### `generate_template_previews.py`

为 `example/gallery/public/pages/` 里每个模板页生成 800×540 的 JPG 缩略图,
存到 `example/gallery/public/pages/_previews/<slug>.jpg`,供模板画廊页使用。

```bash
python -m scripts.debug.generate_template_previews --base http://127.0.0.1:19003
# 仅重生成几个:
python -m scripts.debug.generate_template_previews --only video-platform admin-dashboard
```

## 输出位置

所有调试产物默认放在 `tmp/debug/`,不要 commit。需要长期保留的资产(例如 template 缩略图)走专门的 generator 写到 `example/.../public/...`。

## 加新脚本时的约定

- 文件加在 `scripts/debug/`,顶部一段 docstring 描述用途和一行示例。
- 通用部分(浏览器启动、登录、端口探测)直接 `from .playwright_helpers import ...`,不要重复写。
- CLI 用 `argparse`,默认值要合理(默认指向 demo 端口 19003)。
