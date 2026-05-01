# 项目 AGENTS

此文档为提供给 AI 的通用文档, 说明开发所需注意的事项。

## 代码守则

1. 为了在开发时快速从代码层面区分类/实例的方法与字段, 统一采取以下命名约定:
   - 类/类下的静态方法: camel case
   - 实例/普通 function/decorator/普通变量: snake case

   示例:

   ```python
   class MyClass:
       MyClassVar: ClassVar[int] = 1
       var = 1

       def __init__(self, var: int):
           self.var = var

       @classmethod
       def ClassMethod(cls):
           pass

       @staticmethod
       def StaticMethod():
           pass

       def instance_method(self):
           pass
   ```

2. 常数统一使用全大写和 `_`。

3. 表达 private/protected 意味统一使用 `_xxx` 或 `__xxx__`, 不许使用 `__xxx` 这种两个底线 prefix, 这是为了在极端特殊情况下需要从其他地方访问这些对象时, 不会因为 Python 转换成 `_X_xxx` 而导致错误。

4. 如果某个模块不需要任何特殊的 init, 就不要写 `__init__.py`。如果某个模块想自动导出一些东西, 每个 `.py` 文件都要写 `__all__ = ["xxx", "yyy"]` 来明确导出哪些东西, 然后在 `__init__.py` 里写 `from .xxx import *` 来导出这些东西。这样 IDE 可以有更好的提示, 且各自定义 `__all__` 可以更清晰地分开管理各自的导出内容。在非必要情况下, 不要在 `__init__.py` 定义 `__all__`, 这会导致和它的子 `.py` 的 `__all__` 有矛盾。

   示例:

   ```text
   my_module/
   ├── __init__.py
   ├── xxx.py
   └── yyy.py
   ```

   `xxx.py`:

   ```python
   __all__ = ["XxxClass", "xxx_function"]

   class XxxClass:
       pass

   def xxx_function(): ...
   ```

   `yyy.py`:

   ```python
   __all__ = ["YyyClass", "yyy_function"]

   class YyyClass:
       pass

   def yyy_function():
       pass
   ```

   `__init__.py`:

   ```python
   from .xxx import *
   from .yyy import *
   ```

5. 注释可以使用中文或英文。注释风格遵循 Google style, 例如:

   ```python
   def my_function(param1: int, param2: str) -> bool:
       """这是一个示例函数.

       Args:
           param1: 这是第一个参数, 是一个整数.
           param2: 这是第二个参数, 是一个字符串.

       Returns:
           一个布尔值, 表示函数的结果.
       """
       pass
   ```

6. 项目使用 Python >= 3.12。你可以使用更方便的 generic syntax, 例如 `def f[T](x: T) -> T: ...`, 而不需要 `from typing import TypeVar, Generic` 等。在非必要情况下, 避免使用 `from __future__ import annotations`。

7. 在允许情况下必须使用明确的类型注解, 尤其是公共函数/方法, 以及所有类的字段, 以便 IDE 能提供更好的提示。特别注意:
   - 返回/传入的 dict: 有时为了方便返回多个值, 会直接使用 dict 来包住这些值, 但这会导致 IDE 无法提示这个 dict 里有什么字段。在可能的情况下, 应该使用 `@dataclass` 或 `TypedDict` 来定义这个 dict 的结构, 尤其是 FastAPI 的 response model, 这会直接影响自动生成的 API 文档。
   - 函数在不同传参下有不同返回值类型: 尽可能使用 `@overload` 来定义不同传参下的返回值类型, 示例:

     ```python
     from typing import overload, Literal, NoReturn

     @overload
     def f() -> int: ...

     @overload
     def f(raise_exception: Literal[True]) -> NoReturn: ...

     @overload
     def f(raise_exception: Literal[False]) -> int: ...
     ```

   - 对于多个地方共用的 `*args` 或 `**kwargs`, 可以使用 `Unpack[tuple[...]]` 或 `Unpack[TypedDict[...]]` 来定义它们的共通结构。
   - `TypedDict` 的 `extra_items` 参数可以允许 dict 有额外字段, 但 `extra_items` 在 3.12 尚未包含进标准库, 但 IDE 仍然会识别。因此, 你应该:

     ```python
     from typing import Any, TYPE_CHECKING, TypedDict

     class _A(TypedDict):
         a: int
         b: str

     if TYPE_CHECKING:
         class A(_A, extra_items=Any): ...
     else:
         A = _A
     ```

## 模块说明

```text
├── app/
    ├── api/        # 业务路由, 每个非 _ 开头 .py 会自动导入并注册 Route 子类
    ├── core/       # 框架核心
        ├── ai/         # 通用 AI 接口与服务健康度管理
        ├── rtc_chat/   # RTC 会议/文字通讯基础模块
        ├── server/     # FastAPI app、Route、共享数据、分布式节点网络
        ├── storage/    # kv/object/orm/vector 等通用存储接口
        ├── utils/      # 通用函数与数据结构
    ├── public/     # 可直接通过路由访问的前端静态资源
    ├── main.py     # 后端启动入口
├── resources/
    ├── admin-panel/    # 后端管理面板资源
├── scripts/
├── test/
├── docs/
├── config/
├── logs/
├── tmp/
├── requirements.txt
```

## 文档导航

如果你需要先理解框架再动手, 优先直接看 `docs/` 下对应文档, 不要靠猜:

- `docs/framework.md`: 框架总览、启动方式、配置体系、示例项目入口
- `docs/getting-started.md`: 从环境准备到第一个 Route 的最短上手路径
- `docs/route.md`: Route 自动发现、`__init__.py`/`index.py`、路径参数、元数据继承
- `docs/storage.md`: KV / ORM / Object / Vector 四类存储的配置与调用方式
- `docs/ai.md`: completion / embedding / s2t / t2s 的配置结构与运行时入口
- `docs/frontend.md`: `public/` 静态资源、`.m.html` 合并、`shared/` 组件与模板、i18n
- `docs/deployment.md`: 生产启动、主配置结构、反向代理、容器化注意点
- `docs/testing.md`: 测试目录结构、pytest 运行方式、外部依赖测试约束
- `docs/setup.md`: 本地开发环境、VS Code / Pylance、配置文件放置方式
- `docs/config/README.md`: server / storage / AI 三套配置各自的职责和加载顺序
- `docs/config/server_example.yaml`: 主配置示例
- `docs/config/storage_example.yaml`: 存储配置示例
- `docs/config/ai_services_example.yaml`: AI services 配置示例

## 前端 / UI 开发注意

1. 开发 UI 前, 优先检查 `public/shared/` 下面现有的组件与模板:
    - `public/shared/components/`
    - `public/shared/components.js`
    - `public/shared/templates/`
    - `public/shared/templates.js`

2. 如果需求表面上没有现成组件, 先看能不能通过提升现有 shared 组件/模板的通用性来解决, 优先优化底层通用组件, 不要先写一个新的业务专用组件。

3. 如果确认 shared 里确实没有, 在写 UI 之前先思考这次需求里有哪些部分适合抽成可复用组件, 先把通用组件放进 `public/shared/`, 再基于它构建页面。

4. 图标优先从 `public/icons/` 里找。当前已有 `filled/`、`outlined/`、`twotone/` 三套目录。尽量不要自己手写 SVG 或重复造图标。

5. 如果确实需要额外的前端 JS 库, 可以下载后放进 `public/vendor/`, 但必须先确认现有 vendor 里有没有可直接复用的。当前仓库已经有如 `lit/`、`shoelace/`、`marked/`、`mermaid/`、`mathjax/`、`tailwindcss/`、`xterm/` 等目录。

6. 新增 UI 方案时, 默认优先考虑“能否沉淀到 shared 给后续项目复用”, 而不是只满足当前页面一次性需求。

## 服务器启停脚本

`scripts/` 下的脚本是工程标配, 优先用它们而不是手写 `python -m app ...` / `taskkill`:

- `python scripts/run.py [-p <PORT>] [-w <WORKERS>] ...`: 后台拉起主仓 `app/`(非 `example/*`) 的服务器, 自动写日志、登记 PID。例外: `example/<name>/` 仍然用各自目录里的 `run.py` 启动。
- `python scripts/stop.py [-p <PORT>]`: 优雅停止任意一个本地 server(主仓或 example 都适用), 比手动 `taskkill` 干净, 会通过 admin API 通知 worker 退出后再清理残留进程。
- `python scripts/restart.py [-p <PORT>]`: 等同 `stop` + `run`, 适合改完代码热重启。
- `python scripts/logs.py [-p <PORT>] [--follow] [--level INFO]`: 通过 admin API 查询 / tail 后端日志, 不需要去 `logs/` 翻文件。
- `python scripts/install.py [-y]`: 一次性把依赖、可选系统组件(LibreOffice / TeX 等)装齐, 新机器初始化用。

约定: 在调试 / 临时排错时若开了 server, **必须**用 `scripts/stop.py` 收尾, 不要让进程泄漏。

## 调试脚本

`scripts/debug/` 下放着一组通用调试工具, 优先复用这些, 不要每次重复写 Playwright boilerplate。详细命令见 `scripts/debug/README.md`, 这里只列你最常用的:

- `python -m scripts.debug.playwright_helpers screenshot --url <URL> --out tmp/debug/x.png [--dark] [--lang zh|en] [--viewport 375x812]`: 整页截图, 可切深色 / 语言 / 移动端视口。
- `python -m scripts.debug.playwright_helpers click-shot --url <URL> --selector <SEL> --out <PATH>`: 进入页面 → 点击某元素 → 截图(用来抓 modal / drawer / 折叠状态)。
- `python -m scripts.debug.playwright_helpers audit --base http://127.0.0.1:19003 --pages-from example/demo/public/pages`: 批量访问目录下所有 html, 收 JS / console 错误到 `tmp/debug/audit.json`。
- `python -m scripts.debug.playwright_helpers token --port 19211`: 从项目 `.env` 找 `ADMIN_PW`, 自动登录, 打印 admin api_key (调用受保护接口时使用)。

约定：在 `scripts/debug/` 只加跨项目通用的调试工具，切勿把只服务某个 `example/*` 的一次性脚本放进去。

代码层 API: `from scripts.debug.playwright_helpers import BrowserSession, take_screenshot, audit_pages, admin_login`. `BrowserSession` 自带 `set_dark_mode` / `set_lang`, 可直接 `bearer=` 注入鉴权头。所有调试产物默认写到 `tmp/debug/`, 不进 git。

新增调试脚本统一放进 `scripts/debug/`, 顶部 docstring 写清用途与示例命令, 通用部分从 `playwright_helpers` import, 不要重写。

## 开发注意

1. 不准“写脚本来改代码”, 因为你经常会写错导致整个文件被改坏甚至误删, 绝对不允许。

2. `asyncio.run` 应该改成用 `utils.concurrent_utils` 的 `run_any_func`, 因为这个才能保证在 FastAPI worker 的特殊 loop 环境下也可以运行, 除非 `asyncio.run` 是在一个单独的 thread 跑, 这样就可以接受。

## 环境

1. 注意项目使用的特定 Python 环境, 不要在全局环境安装依赖。

2. 仅限 Windows: PowerShell `Set-Content` 会损坏 UTF-8 多字节字符, 写文件时不要用它。

## 测试

1. 禁止用 `| Select-Object` 或任何管道截断 pytest 输出。管道会隐藏进度, 无法判断测试是否卡住。

2. 必须用 async mode 运行 pytest, 再用 `get_terminal_output` 查看结果。

3. 测试 server 模式的时候, 强烈建议使用 `worker >= 2`, 这样才可以更好模拟在真实环境中多进程访问共享资源的情况。

4. 如果要用 Docker 运行 container 进行某些测试, 例如测试不同 DB 的 storage 模块, 应该先检查有什么 images 已经 pull 了, 不要重复 pull 重复的东西。
