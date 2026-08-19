# Vibe-Research · 项目约束 (CLAUDE.md)

> 个人 AI 投研看板（A股/美股/港股）。FastAPI 后端(:8900) + React 19 前端(:5899)。
> 本文件是 Claude Code 在本项目的**强制约束**——自动加载，每次工作前先读。

---

## 0. 规范驱动开发（Spec-Driven Development, SDD）— 强制流程

**任何非平凡的功能/重构/修复，必须先写规范、后写代码。** 琐碎修复（typo、单行注释）可豁免。

### 流程
1. **写规范**：在 `specs/` 下建 `SNNN-短标题/spec.md`（NNN 递增编号），用 `specs/_template.md` 模板。规范须含：问题/目标、需求清单、受影响文件、验收标准、合规自查。
2. **过合规自查**（见 §1）——已降级为**弱合规**：仪式类约束改为风险提醒，但**工程底线**（不臆造数据/私有数据隔离/防封）仍必过。spec 的"合规自查"栏确认未触工程底线即可。
3. **实现**：按规范逐步实现，commit 引用 spec 编号。
4. **验收**：逐条核对验收标准；涉及数据的跑 `financial_rigor.py`/`report_audit.py`（在 `~/tools/`，见 §5）验算，禁止心算。
5. **归档**：实现完成后在 spec 顶部标注状态（已实现/已废弃）与日期。

> 没有规范不写代码。用户要求"直接改"时，先花一屏写规范再动手——这是本项目的工作纪律。

### 0.1 分级工作流（2026-08-04 落地，替代原 Feature 分支工作流）

> **规范源在 `AGENTS.md`「分级工作流」**——跨工具共守（Claude Code / opencode / 所有 agent 通用）。本节为引用指针，改动以 AGENTS.md 为准。
>
> 摘要：改动按规模分级（small / medium / large），匹配不同流程门。small 免 spec/验收/分支/review；medium 免 feature 分支但走 issue 层单轮 review；large 保留完整 feature 分支 + grill + playwright 验收。判据与流程门详见 AGENTS.md。

### 何时可跳过规范
- 纯文档修订、typo、依赖版本号、CI 配置微调——属 small 级，免 SDD。
- **涉及数据输出/AI 提示词/交易信号**的改动一律不可跳过，必须过合规自查（弱合规下仅核查工程底线：不臆造/私有数据隔离/防封）。
- 分级判据与流程门详见 `AGENTS.md`「分级工作流」。

---

## 1. 合规边界 → 弱合规（私人投研助理定位）

> **定位调整（2026-07-30）**：系统角色明确为**私人投研助理**（自托管、个人使用，用户即决策者）。
> 原"合规红线"降级为**弱合规**——硬性约束改为**风险预警提醒**级别。
> 但区分两类：**合规仪式**（免责声明/标注/中立措辞/不代客决策）降为风险提醒；
> **工程底线**（不臆造数据/私有数据隔离/防封）**保留**——它们保护用户自身的钱与数据，
> 不是外部合规仪式。区分依据见 `~/.claude/.../memory/weak-compliance-personal-assistant-2026-07-30.md`。

### 1.1 弱合规（原红线 → 风险提醒级别）

私人助理场景下，系统可主动给研判、推荐、买卖时机，**无需**强制免责墙/中立措辞/不代客决策：

- **免责声明**：保留轻量风险提醒（如「历史统计特征，市场有风险」），不再强制「不构成投资建议」墙。S017 预测端点的免责墙可简化为风险提醒。
- **`chat.SYSTEM_PROMPT`**：可给方向性研判/买卖时机/收益预期，措辞放宽（具体放宽在 S010 落地）。
- **代客决策**：可给明确操作建议，但仍由用户最终决策（半自动化助手定位，见 `positioning-semi-automated-assistant`）。
- **涨停四池/连板股榜**：可如实呈现个股 code/name（公开榜单，用户自己的工具）。`lianban_stocks` 不再强制从 Emotion 剥离——是否剥离改为**设计选择**（聚合指标 vs 客观榜单分层呈现仍推荐分层，但不作红线）。

### 1.2 工程底线（保留——非合规，而是正确性/隐私）

以下三条保护用户自身的钱与数据，**不降级**（§44 lift bar 已降级为参考性建议，见下）：

- **判断须可复现**：研究性判断须基于公开数据 + 既定规则可复算（`~/tools/financial_rigor.py` 核对），**禁止臆造、禁止心算**。这是「让胜率数字为真」的前提，不是合规仪式。
- **用户私有数据隔离**（持仓/研报/API key）只存项目目录内 `.vibe-research/`（`VR_DATA_DIR`，见 `backend/vr_paths.py`），**绝不进 git（已 .gitignore）、不上传、不落 home 目录**。
- **东财端点走 `em_get`** 限流/熔断/代理探测（已迁 `backend/data/transport.py`），不裸调 requests（防封 IP）。

> **§44（lift bar）已降级为参考性建议**（2026-08-19，S084 reframe）：§44 原为出 winrate/r/verdict 前的「必过 gate」——须过三步（口径 sanity 验荒谬值 / n+CI+lift / 随机基准 lift<2x=噪声），未过只报「待验」不出结论。现降为**参考性建议，不强制、不阻塞实现**——设计方案经深度调研（grill），不因 §44 未过而阻断落地。§44 验证移至两处而非实现前 gate：（1）**设计期**——验证设计方案本身的统计有效性；（2）**回溯模块**——独立模块，引入 §44 作为回溯方案之一，长期积累数据后跑（阈值/胜率回溯校准）。其余工程底线（不臆造 / 私有数据隔离 / `em_get` 防封）不变。

### 1.3 边界变更记录

- **2026-08-19**（S084 reframe）：§44（lift bar，出 winrate/r/verdict 前的必过 gate）从工程底线降级为**参考性建议**——不强制、不阻塞实现（设计方案经深度调研/grill）；§44 验证移设计期（验设计方案统计有效性）+ 回溯模块（独立模块，引入 §44 作回溯方案之一，长期积累数据后跑）。其余工程底线（不臆造/私有数据隔离/`em_get` 防封）不变。受影响：`CLAUDE.md` §1.2。
- **2026-07-30**：私人助理定位明确，合规红线降级为弱合规（风险提醒）。仪式类（免责声明/中立措辞/不代客决策/四池零个股名）→ 风险提醒级；`lianban_stocks` 可如实呈现。保留工程底线：可复现/不臆造、私有数据隔离、`em_get` 防封。受影响：S017 免责墙可简化、S010 SYSTEM_PROMPT 放宽、S008 `lianban_stocks` 不再强制剥离（仍可分层作设计选择）、相关 spec 合规自查栏按弱合规重审。
- 2026-07-29：原 §1「只返回客观数据、不推荐/不给买卖时机」放宽为允许教育研究性判断（战法匹配/买卖时机研判/风险标注），仍守底层红线。


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
