# Test Layout

`test/` 按“领域 + 执行方式”组织：

- `ai/`：AI 服务相关测试。
- `ai/services/`：AI client / config / proxy 等单测。
- `ai/scenarios/`：人工场景脚本，统一使用 `run_*.py` 命名，不会被 pytest 自动收集。
- `server/`：FastAPI / 路由 / 真实 uvicorn 集成测试。
- `storage/`：文件与存储层测试。
- `tools/`：工具侧测试。
- `tools/paper_emulator/`：Paper Emulator 全部测试，文件名统一使用完整 `paper_emulator` 语义。
- `tools/ppt_generator/`：PPT Generator 测试。
- `generators/`：试卷与题目生成相关测试。
- `generators/papers/`：人工场景脚本，统一使用 `run_*.py`。
- `generators/stress/`：压力脚本，统一使用 `stress_*.py`。
- `utils/`：通用工具与回归测试。
- `dse_html_render.py`：按约束保持原位，不参与这轮重组。

命名规则：

- `test_*.py`：pytest / unittest 自动收集。
- `run_*.py`：人工场景脚本，需要手动执行。
- `stress_*.py`：压力脚本，需要手动执行。

常用运行方式：

- 快速单测：`python -m pytest test/ai test/server test/storage test/utils -q`
- 代理与 ThinkThinkSyn 回归：`python -m pytest test/ai/services/test_proxy_client.py -q`
- 真实双 worker 服务集成：`python -m pytest test/server/test_real_integration.py -q`
- AI 连通性脚本：`python test/ai/scenarios/run_quick_connectivity.py`
- 小学数学场景脚本：`python test/generators/papers/run_primary_math_render.py --paper all`
- DSE 日语翻译场景：`python test/generators/papers/run_dse_math_p2_japanese.py`
- MCQ 压力脚本：`python test/generators/stress/stress_mcq.py`
- 长题压力脚本：`python test/generators/stress/stress_long_questions.py`
- 试卷渲染压力脚本：`python test/generators/stress/stress_paper_render.py`

补充说明：

- 真实 AI / Paper Emulator 场景依赖 `.env` 里的 API key。
- `test/server/test_real_integration.py` 为了稳定和速度，会显式跳过 question embedding preload；它验证的是服务路由和多 worker 行为，不覆盖 preload 子进程本身。
- question embedding preload 的代理回退逻辑现在由 `aiohttp_client_session` 负责：自动注入代理失败时，会再试一次直连。