# Vibe-Research · 项目约束 (CLAUDE.md)

> 个人 AI 投研看板（A股/美股/港股）。FastAPI 后端(:8900) + React 19 前端(:5899)。
> 本文件是 Claude Code 在本项目的**强制约束**——自动加载，每次工作前先读。

---

## 0. 规范驱动开发（Spec-Driven Development, SDD）— 强制流程

**任何非平凡的功能/重构/修复，必须先写规范、后写代码。** 琐碎修复（typo、单行注释）可豁免。

### 流程
1. **写规范**：在 `specs/` 下建 `SNNN-短标题.md`（NNN 递增编号），用 `specs/_template.md` 模板。规范须含：问题/目标、需求清单、受影响文件、验收标准、合规自查。
2. **过合规自查**（见 §1）——本项目的合规红线比普通项目更严，任何 spec 必须显式过一遍。
3. **实现**：按规范逐步实现，commit 引用 spec 编号。
4. **验收**：逐条核对验收标准；涉及数据的跑 `financial_rigor.py`/`report_audit.py`（在 `~/tools/`，见 §5）验算，禁止心算。
5. **归档**：实现完成后在 spec 顶部标注状态（已实现/已废弃）与日期。

> 没有规范不写代码。用户要求"直接改"时，先花一屏写规范再动手——这是本项目的工作纪律。

### 何时可跳过规范
- 纯文档修订、typo、依赖版本号、CI 配置微调。
- 但**涉及数据输出/AI 提示词/交易信号**的改动一律不可跳过，必须过合规自查。

---

## 1. 合规红线（最高优先级，不可违反）

本项目是**投研数据看板**，合规是生存线。任何代码/规范必须守：

- **只返回客观数据**：工具、数据层、API 不预置标的、不排名、不推荐、不预测涨跌、不给买卖时机、不承诺收益、不做主观评分。
- **涨停四池原始池含个股 code/name**，仅供 `market._emotion` 聚合成**不含个股名**的指标（连板梯队/封板率/炸板率/晋级率）。**切勿直接把原始池接 API/UI**。
- **`chat.SYSTEM_PROMPT` 的中立规则焊死**：新增 AI 工具/改提示词时不得引入方向性建议。
- **用户私有数据**（持仓/研报/API key）只存 `~/.vibe-research/`（`VR_DATA_DIR`），**绝不进 git、不上传**。
- 规范的"合规自查"栏必须逐条确认未触红线，否则 spec 不予通过。

---

## 2. 开发环境（Windows 本机）

- **仓库**：`E:\python\projects\Vibe-Research`（develop 分支）
- **Python**：系统默认 `python` 是 3.7（太旧）；项目用 **3.10+**，venv 在 `backend/.venv`，解释器 `backend/.venv/Scripts/python.exe`。本机 `python3` 是 shim→`python`（见 §5）。
- **启动后端**：`cd backend && .venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8900 --reload`
- **启动前端**：`cd frontend && npm run dev`（:5899，Vite 代理 `/api`→:8900）
- **`dev.sh` 是 Linux 风格**（依赖 lsof、`.venv/bin/activate`），Windows Git Bash 上不通用——Windows 下用上面手动命令，或自建 `.ps1`/`.bat`。
- 每条 bash 命令用 `cd /e/python/projects/Vibe-Research && ...` 前缀（本环境 shell 状态不跨命令持久）。
- 测试：`cd backend && .venv/Scripts/python.exe -m pytest -m "not live"`（离线快测）。

---

## 3. 关键架构约定（详见 `ARCHITECTURE.md`）

- **数据层**：`astock.py`（A股，腾讯底座+东财走 `em_get` 限流）/ `gstock.py`（美港股）/ `newsradar.py`（资讯）/ `market.py`（情绪板块）。新增东财端点**必须走 `em_get()`**，不可裸调 requests（会被封 IP）。
- **AI 三出口共用 `chat.TOOLS`**：新增 AI 数据工具时，在 `chat.py` 的 `TOOLS` 加项 + `_exec_tool` 加分支——API 接入与 MCP 自动同时获得（`mcp_server.py` 复用 `chat.TOOLS`）。
- **限流/降级**：`em_get` 直连优先失败降级系统代理 + 熔断器 `circuit_breaker.get_breaker("eastmoney")` + 涨停四池 24h 缓存 + 路由级 `cache_response(ttl)`。
- **定时任务**：`scheduled_tasks.py`（cron + SQLite 持久化，6 种内置任务）；新增任务类型在 `TaskExecutor._executors` 加方法。
- **打板工作流**：七态状态机 `workflow_state_machine.py`（pending→candidate→watching→monitoring→holding→settled，旁路 filtered）。

---

## 4. 已知问题（动手前必读）

- **✅ 已修复（S001，2026-07-29）**：`chat._get_env_llm_config` 已在 `chat.py` 实现（读 `VR_LLM_BASE_URL`/`VR_LLM_API_KEY`/`VR_LLM_MODEL`），`POST /api/chat` 与 `GET /api/settings/llm-env-status` 不再 500。同日还修了 `cli_runtime` UTF-8 编码 bug（`run_cli[_stream]` 加 `encoding="utf-8"`，否则 Windows cp936 locale 下订阅 CLI 接入静默返空）——**注意**：`routers/chat.py:64` 的环境变量兜底对 cli/API 两条路径都执行，故原 bug 实际也阻塞订阅接入；现已一并打通。spec 见 `specs/S001-fix-chat-env-llm-config/spec.md`（已实现）+ `specs/S002-打板工作流重构/验收报告.md` 修订记录 HIGH-5。
- zustand 列为前端依赖但全仓未实际使用（无害冗余）。

---

## 5. 配套工具（`~/tools/`，本机自建）

- `financial_rigor.py`：市值/估值/三情景程序化验算（Decimal 精确，禁止心算）。
  - `verify-market-cap --price P --shares S(亿) --reported R`
  - `cross-validate --field F --values '{"源":值}' --unit U`
  - `three-scenario --price P --eps E --shares S(亿) --growth g1 g2 g3 --pe p1 p2 p3 --discount 0.10`
- `report_audit.py`：报告数据抽检准出（`extract` 抽样 15% → 取数 → `verdict` 判 ≤1% 准出）。
- `~/bin/python3` shim → `python`（让框架 `python3 …` 命令可用）。
- 涉及财务数据的分析/报告，关键数据必须经这两个工具验算后才算完成。

---

## 6. MCP 集成

- `vibe-research` MCP server 已 `claude mcp add -s user` 挂入，暴露 5 工具：`query_quote / query_valuation / query_reports / query_news / query_global_stock`。
- 启动：`backend/.venv/Scripts/python.exe backend/mcp_server.py`（stdio JSON-RPC，纯标准库）。
- 新增 MCP 工具 = 在 `chat.TOOLS` 加项（自动同步到 MCP，无需改 `mcp_server.py`）。

---

## 7. 工作风格

- 改代码前先读 `ARCHITECTURE.md` 定位模块；改 AI/数据相关先过 §1 合规自查。
- 实现后用 `pytest -m "not live"` 自测；涉及数据输出跑 §5 工具验算。
- 不确定的地方标注并实测，不臆测。
