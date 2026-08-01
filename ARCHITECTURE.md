# Vibe-Research 架构文档

> 个人 AI 投研看板（A股 / 美股 / 港股 / 韩股）。本地自托管，FastAPI 后端(:8900) + React 19/Vite 前端(:5899)。
> 定位：**把客观数据配齐摆好看板，三条出口接用户自己的 AI 做分析。** 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1，2026-07-30），仅挂轻量风险提醒「历史统计特征，市场有风险」。
> 文档基准：仓库 develop 分支，2026-07-28。

---

## 一图概览（数据流）

```
外部数据源                        数据层 (backend/*.py)            API 路由 (routers/)         前端 / AI 出口
──────────────────                ────────────────────             ──────────────────          ─────────────────
腾讯 qt.gtimg.cn (不封IP) ──────►  astock.py (A股全栈)  ──┐
东财 push2/reportapi/datacenter ─►  ├ em_get 限流+熔断     │──► stock_data / stock_financial ─► StockData / StockDeep
akshare (惰性导入) ──────────────►  ├ profit_forecast      │──► market / limitup / recommendation ─► Sectors / LimitUp
mootdx TCP:7709 (惰性) ──────────►  ├ kline/finance        │──► kline_history / chat / radar ─► 问AI / 资讯雷达
新浪/巨潮/同花顺 ─────────────────►  └ full_valuation      │──► workflow / risk / portfolio / myreports ...
                                   gstock.py (美港股/韩股) ─┘
东财 push2→push2delay 降级 ──────►  ├ global_indices / us_hk_stock
                                   market.py (情绪/板块) ──┘
akshare legu/行业资金流 ─────────►  ├ _sentiment/_sectors
东财涨停四池(聚合) ──────────────►  └ get_overview/_emotion  (TTL 5min 共享缓存)
108 RSS 源 ──────────────────────►  newsradar.py (12赛道, 40线程并发, 合规过滤)

AI 三条出口（共用 chat.TOOLS 5工具 + SYSTEM_PROMPT 投研五维框架）:
 1. 订阅接入  cli_runtime.py  — subprocess 调本机已登录 CLI (claude/qwen/deepseek/codex/opencode) — 不支持 function-calling，数据须已在 context
 2. API 接入  chat.py        — OpenAI 兼容 function-calling (≤6轮循环) — AI 自己调数据工具
 3. MCP 接入  mcp_server.py  — stdio JSON-RPC，复用 chat._exec_tool — 给 Claude Code 等 agent

调度: scheduled_tasks.py (cron-like, 每分钟tick, SQLite持久化) + scheduler.py (盘后预计算/持仓刷新)
打板工作流: trading_workflow.py (按时段编排) + workflow_state_machine.py (七态状态机) + pre/realtime/post_market_workflow.py
```

---

## 后端模块清单

| 文件 | 职责 | 关键函数/类 |
|---|---|---|
| `app.py` | FastAPI 入口；注册 26 个 router；启动调度器；CORS/API Key 鉴权/性能指标中间件；路由级缓存 | `app`、`_require_api_key`、`_metrics_middleware`、`cache_response(ttl)`；启动 `start_portfolio_scheduler(1800)`、`start_limitup_scheduler()`、`_st.start_scheduler()` |
| `astock.py` | A股全栈数据层（五源分级） | `tencent_quote`、`em_get`（统一限流入口）、`eastmoney_reports`、`profit_forecast`、`kline`、`finance`、`full_valuation`、`valuation_percentile`、`em_zt_topic_pool`（涨停四池）、`dragon_tiger_board`、`margin_trading`、`block_trade`、`stock_fund_flow_120d`、`concept_blocks`… |
| `gstock.py` | 美股/港股/韩股（东财合规子集） | `global_indices`、`resolve_symbol`、`us_hk_stock`、`_push2_stock_get`（push2→push2delay 降级） |
| `newsradar.py` | 资讯雷达（108 RSS / 12 赛道） | `fetch_radar`、`get_radar(force)`；`ThreadPoolExecutor(40)`；原子写缓存 |
| `market.py` | 市场情绪/板块资金/全球指数 | `get_overview`、`get_short_term_emotion`、`get_turnover_top`、`get_global_indices`；`_emotion`（涨停四池聚合→连板梯队/封板率/晋级率）；TTL 5min |
| `chat.py` | 系统 AI 对话层 | `TOOLS`（5工具）、`_exec_tool`、`run_chat[_stream]`（API）、`run_chat_cli[_stream]`（订阅）、`SYSTEM_PROMPT`（投研五维框架，S010 放宽）；`MAX_ROUNDS=6`；SSRF 防护 |
| `mcp_server.py` | MCP server（stdio JSON-RPC） | `MCP_TOOLS`、`_handle`、`main` |
| `cli_runtime.py` | 订阅接入：调本机 CLI | `_CLI_DEFS`、`detect_cli`、`run_cli[_stream]`；三种投递 system-file/stdin/arg；禁 CLI 内置工具防越权；subprocess `encoding="utf-8"`（Windows cp936 locale 防护，HIGH-5） |
| `config.py` | 配置（dataclass + .env） | `AssistantDefaultConfig`、`load_config()`、`default_config` |
| `portfolio.py` | 持仓（存 `~/.vibe-research/`） | `refresh_all`、`CACHE_DIR` |
| `myreports.py` | 研报文件存储（用户私有） | `_DATA_DIR`（VR_DATA_DIR/VR_REPORTS_DIR） |
| `risk_models.py` | 一日风险量化 | `OneDayRisk`、`get_dynamic_thresholds(sti_phase)`、`_build_risk_factors` |
| `risk/bomb_alert_system.py` | 炸板预警 | `BombAlertSystem.check` |
| `risk/position_manager.py` | 动态仓位管理 | `PositionManager` |
| `trading_workflow.py` | 打板工作流编排（按时段判阶段） | `TradingWorkflow`、`get_current_stage`、`run_pre_market/intraday/post_market` |
| `workflow_state_machine.py` | 打板状态机 | `WorkflowStatus`（7态）、`WorkflowStateMachine`、`_ALLOWED_TRANSITIONS` |
| `scheduled_tasks.py` | SQLite 持久化 cron 调度 | `CronScheduler`（每分钟tick）、`TaskExecutor`（6种内置任务）、`start_scheduler` |
| `scheduler.py` | 后台调度（盘后预计算+持仓刷新） | `start_limitup_scheduler`、`start_portfolio_scheduler(1800)` |
| `circuit_breaker.py` | 数据源熔断器 | `get_breaker("eastmoney")` → `allow_request/record_success/record_failure` |
| `notification/` | 多通道通知（15+ sender） | `notification_service`、senders/(feishu/dingtalk/email/discord/slack/telegram/...) |

---

## AI 三条出口

三条共用 `chat.TOOLS`（5 工具）与 `SYSTEM_PROMPT`（投研五维框架，S010 放宽），保证语义一致。

| 出口 | 原理 | function-calling | 适用 |
|---|---|---|---|
| **订阅接入** `cli_runtime.py` | subprocess 起本机已登录 CLI，用订阅额度作答、免 key；三种提示词投递 system-file/stdin/arg；禁 CLI 内置工具防越权 | ❌ 不支持（数据须已在 context） | 仅本地自托管；复盘/今日要点等"数据已备好"场景 |
| **API 接入** `chat.py` | OpenAI 兼容 `/chat/completions`，key 存浏览器；≤6 轮工具循环，结果截断 6000 token；流式 NDJSON；SSRF 防护挡 baseURL 指向云元数据/内网 | ✅ AI 自己调数据工具 | 网页问个股、多步取数；云端/公网可用 |
| **MCP** `mcp_server.py` | 纯标准库 stdio JSON-RPC，零第三方依赖；复用 `chat._exec_tool` | ✅ | 给 Claude Code 等 agent，用订阅额度调数据 |

### MCP 暴露的 5 工具

| 工具 | 用途 | 参数 |
|---|---|---|
| `query_quote` | A 股实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停（可批量） | `codes`: string[]（6位代码） |
| `query_valuation` | 完整估值 + 机构一致预期 EPS + 前向 PE/PEG/PE 消化年数 | `code`: string |
| `query_reports` | 个股近期研报（标题/机构/评级/日期） | `code`: string |
| `query_news` | 个股近期新闻（标题/时间/来源） | `code`: string |
| `query_global_stock` | 美股(AAPL)/港股(00700)/韩股(005930.KS，仅行情) | `symbol`: string |

执行映射：`query_quote`→`astock.tencent_quote`、`query_valuation`→`astock.full_valuation`、`query_reports`→`astock.eastmoney_reports`、`query_news`→`astock.stock_news`、`query_global_stock`→`gstock.us_hk_stock`。

---

## 数据层与限流/降级

### astock.py — A 股五源分级
- **腾讯**（`qt.gtimg.cn`，HTTP GBK）：行情/PE/PB/市值/换手/涨跌停。标准库 `urllib`，不封 IP，**永远可用**（底座 Layer 1）。
- **东财**（push2/push2ex/reportapi/datacenter-web/searchapi）：研报/龙虎榜/解禁/融资融券/大宗/股东户数/分红/资金流/行业排名/涨停四池/个股新闻。**会封 IP**，统一走 `em_get()`。
- **akshare/mootdx**（惰性导入）：缺失时 `DependencyMissing` 优雅报错，不挡启动。
- **新浪/巨潮/同花顺**：财报三表/公告/一致预期。

### `em_get` 限流/降级策略（核心）
1. 串行限流：默认 1.0s + 抖动 0.1~0.5s，QPS≤2。
2. 复用 `requests.Session`（Keep-Alive），直连会话 `trust_env=False` 忽略 HTTP_PROXY。
3. **直连优先、失败降级系统代理**：auto 模式先直连（短超时 8s 不重试），成功 latch direct；失败走系统代理 latch proxy，整进程复用。`VR_DATA_PROXY=1` 强制代理。
4. **熔断器**（`circuit_breaker.get_breaker("eastmoney")`）：快速失败不重复重试。
5. 涨停四池 HTTP 缓存 24h；路由级缓存 `cache_response(ttl)`。

### gstock.py — 美港股/韩股
东财 `push2` 优先、失败降级 `push2delay`（延时行情），latch 整进程复用；全部复用 `astock.em_get`。韩股剥 `.KS` 后缀按裸代码搜（MktNum 177，仅行情无 F10 财务）。

### newsradar.py — 资讯雷达
108 RSS 源、12 赛道、40 线程并发、合规词表过滤（赌/预测市场/加密/色情命中即跳过）；单源失败不拖垮整体；缓存原子写（tmp + os.replace）。

### market.py — 市场情绪/板块/全球指数
全站共享 TTL 5min 缓存；`_emotion` 把涨停四池聚合成连板梯队/封板率/炸板率/晋级率；数据源故障的空结果不缓存，下次直接重试。

---

## 定时任务与打板工作流

### 定时调度（`scheduled_tasks.py`）
- CronScheduler：每 60s tick，5 段 cron 匹配，daemon 线程。
- SQLite 持久化（`backend/data/market_data.db`）：`scheduled_tasks` + `scheduled_task_runs`。
- TaskExecutor 内置 6 种任务：`daily_data_refresh` / `daily_review_notify` / `limitup_precompute`（盘后预计算基因+STI+竞价+复盘）/ `portfolio_refresh` / `market_data_sync` / `cleanup_old_runs`。
- `app.py` 启动时 `start_scheduler()`；另 `scheduler.py` 起 `start_portfolio_scheduler(1800)` 与 `start_limitup_scheduler()`。

### 打板工作流状态机（`workflow_state_machine.py`）
七态：`pending → candidate → watching → monitoring → holding → settled`，旁路 `filtered`；`settled → candidate`（下一轮）、`filtered → candidate`（可重入）。`transition(target, reason)` 记 `_history`。

### 工作流编排（`trading_workflow.py`）
按时段判阶段：8-9 盘前 / 9-15 盘中 / 15-22 盘后 / 其余非交易；调度 PreMarketWorkflow / RealtimeWorkflow（产出 signals/alerts/含 BombAlert + adjustments/含 PositionAdjustment）/ PostMarketWorkflow。

---

## 前端（React 19 + Vite 6 + TS）

- **路由**（`router.tsx`）：26+ 页面，`/`→`/daily-review`。含 daily-review / intel / sectors / portfolio / stock-data / stock/:code / watchlist / my-reports / limitup(×3) / recommendation / strategy-signals / backtest / risk-dashboard / sentiment-weather / workflow / scheduled-tasks / settings 等。
- **状态管理**：实际是 React state + localStorage（zustand 列在依赖但全仓未用——冗余）。
- **AI 配置/鉴权**：`lib/llm.ts` 存 `localStorage["vr-llm"]`；`lib/api.ts` 存 `localStorage["vr-access-key"]`，每次请求带 `Authorization: Bearer`。
- **与后端**：Vite 代理 `/api`→`:8900`；`lib/api.ts` 统一 `request<T>`；AI 对话 `chatStream` 流式 POST `/api/chat`，NDJSON 逐行解析 `{delta|tool|done|error}`，支持 AbortSignal 中止。
- 图表 echarts 6，Markdown react-markdown + remark-gfm，提示 sonner。

---

## 配置与数据目录

### 关键环境变量
- **安全**：`VR_API_KEY`（设了则 `/api/*` 除 `/api/health` 需鉴权；本地留空=开放，公网必设）、`VR_ALLOW_ORIGINS`（CORS 白名单）。
- **AI 兜底**：`VR_USE_FREE_FALLBACK` / `VR_FREE_PROVIDER` / `VR_GEMINI_API_KEY` / `VR_GROQ_API_KEY` 等。
- **数据源**：`VR_DATA_PROXY=1`（强制东财走代理，默认 auto 直连优先）；`IWENCAI_API_KEY`（仅语义搜索）。
- **基因/推荐阈值**：`VR_GENE_QUALIFY_THRESHOLD` / `VR_RECOMMEND_*_THRESHOLD`。
- **通知渠道**：飞书/钉钉/邮件/telegram/discord/slack/wechat 等大量字段（见 `config.py`）。

### 数据目录
- `VR_DATA_DIR`（默认 `~/.vibe-research/`）：持仓 + 研报，**用户私有、绝不进仓、不上传**——重装项目不丢。
- `VR_REPORTS_DIR`（默认 `VR_DATA_DIR/myreports`）：研报文件。
- `backend/data/`：`market_data.db`（定时任务）、`winrate.db`（胜率）、`fallback/`。
- `backend/.cache/radar.json`：资讯雷达缓存。

---

## 可扩展点

| 想加 | 改哪 |
|---|---|
| 新 A 股数据端点 | `astock.py`（东财走 `em_get`）；可抄 `a-stock-data/SKILL.md` 40 端点代码 |
| 新 AI 工具（网页+MCP 同时获得） | `chat.py` 的 `TOOLS` 加项 + `_exec_tool` 加分支 |
| 新 API 模型供应商 | 前端 `lib/ai-models.ts` 加条目（后端 OpenAI 兼容，无需改） |
| 新订阅 CLI | `cli_runtime.py` 的 `_CLI_DEFS` + 前端 `ai-models.ts` |
| 新页面 | 前端 `pages/` + `router.tsx`；后端 `routers/` + `app.py` `include_router` |
| 新通知通道 | `notification/senders/` 加 sender + `config.py` 加环境变量 |
| 新定时任务类型 | `scheduled_tasks.py` 的 `TaskExecutor._executors` |
| 新战法/策略 | `strategies/` 或 `limitup_strategy.py`；需状态流转则扩 `workflow_state_machine.py` |
| 新风险因子 | `risk_models.py` 的 `_build_risk_factors` / `OneDayRisk` |

### 合规（扩展时务必守）
- 工具/数据层以客观数据为主；研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1，2026-07-30），输出仅挂轻量风险提醒「历史统计特征，市场有风险」，不承诺确定性。
- `market._emotion` 的涨停四池原始池含个股名，默认仅聚合为不含个股名的指标；若需连板股客观榜单，走 `astock.em_zt_topic_pool` 原始池出口如实呈现 code/name（设计选择，2026-07-30），聚合指标与客观榜单分层由调用方明确标注。
- `chat.SYSTEM_PROMPT` 措辞放宽（S010），保留可复现等工程底线。

---

## 已知问题（develop 分支，2026-07-29 复核）

### ✅ 已修复：`chat._get_env_llm_config` 缺失 → "问 AI" 500（S001，2026-07-29）

- 原状：`routers/chat.py:32/59/64` 调 `chat_layer._get_env_llm_config()`，但 `chat.py` 未定义该函数 → `POST /api/chat` 与 `GET /api/settings/llm-env-status` HTTP 500。
- 修复：`chat.py` 补 `_get_env_llm_config()`（读 `VR_LLM_BASE_URL`/`VR_LLM_API_KEY`/`VR_LLM_MODEL`，缺省空串）；`.env.example` 补对应注释项。
- 订阅接入路径：原判断称"cli-* 不受影响"**有误**——第 64 行环境变量兜底对两条路径都执行，故原 bug 也阻塞订阅接入；现已一并打通。
- 配套修复：`cli_runtime.run_cli[_stream]` 加 `encoding="utf-8", errors="replace"`（否则 Windows cp936 locale 下 `claude.CMD` 的 UTF-8 stdout 被 GBK 解码 → `UnicodeDecodeError` 被 `_pump` bare except 吞 → 订阅 CLI 静默返空内容，见 `specs/S002-打板工作流重构/验收报告.md` HIGH-5）。
- 实测：`POST /api/chat`（cli-claude 配置）→ 200，流含 `delta`+`done`，答案合规。

### 其他
- zustand 列为前端依赖但全仓未实际使用（无害冗余）。

---

## 部署状态（本机）

- 仓库：`E:\python\projects\Vibe-Research`（develop 分支）
- 后端：`backend/.venv`（Python 3.10.1），uvicorn :8900 运行中，定时调度器已启动
- 前端：`frontend` node_modules 已装，vite :5899 运行中
- MCP：`vibe-research` 已 `claude mcp add -s user`，健康检查 ✔ Connected，5 工具 stdio 实测可取真实 A 股数据（query_quote 600519/000858 返回正确）
- 注：dev.sh 为 Linux 风格（lsof + `.venv/bin/activate`），Windows 下改用手动 `.venv/Scripts/python.exe -m uvicorn` + `npm run dev`
