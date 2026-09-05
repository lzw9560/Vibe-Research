# S149 Phase 0 审计报告

> **日期：** 2026-09-04
> **vibe-astock commit：** `3c3b7c841687b6263df7e434547a75b02f071c6f`（2026-09-02）
> **审计人：** orchestrator

---

## 1. 逐模块判定表

### 1.1 移植模块（12 个来源 → 7 个目标文件；vibe_astock_util 含 util.py + trade_calendar 4 函数）

| duanxian 模块 | 大小 | Vibe-Research 对应 | 判定 | 理由 |
|---|---|---|---|---|
| **util.py** | 4KB | **无等价物**（已验证） | **移植→backend/utils/vibe_astock_util.py** | Oracle 🔴 修正：6 个移植模块全部依赖 `atomic_write_json`/`china_now`/`china_today`/`validate_trade_date`，Vibe-Research 全仓无等价物。`safe_join` 仅被丢弃模块消费，按 YAGNI 不移植。`vr_paths` 有 `is_trading_day`/`BEIJING_TZ` 但无原子写 |
| emotion_metrics.py | 22KB | market.py::_emotion（部分）+ limitup_sti/（STI_WEIGHTS） | **吸收缺失函数** | 见 §2 逐函数 diff + 完整 import 依赖表 |
| journal.py | 32KB | 无 | **移植** | 全新功能，portfolio.py 是持仓非交易日志 |
| at_risk.py | 8KB | 无 | **移植→合入 journal_risk.py** | 全新功能 |
| excursion.py | 14KB | 无 | **移植→合入 journal_risk.py** | 全新功能 |
| attribution.py | 8KB | 无 | **移植→合入 journal_risk.py** | 判断vs执行归因，随 journal 一起 |
| inbox.py | 9KB | 无 | **移植→合入 journal_risk.py** | 异常交易收件箱，随 journal 一起 |
| risk.py | 26KB | 无 | **移植→合入 journal_risk.py** | 风险宪法，随 journal 一起 |
| prompts.py | 7KB | chat.py SYSTEM_PROMPT + llm_presets.py(77行) | **移植 PromptPack 接口**（砍 focus 三件套） | 加一层纯文本风格字段 |
| archive.py | 10KB | 无 | **移植**（视 Phase 2 需求） | 全新功能 |
| drift.py | 11KB | 无 | **移植**（视 Phase 2 需求） | 全新功能 |
| trade_calendar.py | 8KB | vr_paths（部分缺失） | **部分移植**（4 函数→vibe_astock_util，模块整体不引入） | emotion_metrics 依赖 is_settled/trade_dates_ending_at/live_quotes_are_close_of/quote_trade_day，vr_paths 无（见 §2.1） |

### 1.2 丢弃模块（37 个 + trade_calendar 部分移植见 §1.1）

| duanxian 模块 | 大小 | 理由 |
|---|---|---|
| data.py | 17KB | Vibe-Research 有 astock.py + data/sources/（含熔断器/防封） |
| fetchers.py | 26KB | Vibe-Research 有 data/sources/eastmoney.py + tencent.py |
| config.py | 2KB | Vibe-Research 有 config.py + .env |
| cli_llm.py | 4KB | Vibe-Research 有 3 条 AI 出口（cli_runtime.py） |
| reflection.py | 532行 | vibe-astock 自己的复盘评估模块，含 _load_review()。Vibe-Research 的 reflection.py(72行) 是流式 LLM 调用，语义不同 |
| market_facts.py | 28KB | Vibe-Research 有 market.py + astock.em_zt_topic_pool |
| ~~trade_calendar.py~~ | 8KB | **已移至 §1.1 部分移植**（4 函数→vibe_astock_util，模块整体不引入） |
| analysts.py | 7KB | 复盘分析师角色定义，Vibe-Research 有 chat.py SYSTEM_PROMPT |
| debate.py | 2KB | Vibe-Research 有 debate.py |
| review_graph.py | 1KB | LangGraph 编排，Vibe-Research 无 LangGraph 依赖 |
| review_store.py | 7KB | Vibe-Research 有 snapshot_store/daily_review |
| roles.py | 1KB | 分析师角色，Vibe-Research 有自己的角色定义 |
| schemas.py | 5KB | pydantic 模型，Phase 4 砍掉 focus 三件套后不需要 |
| structured.py | 3KB | 结构化 LLM 输出，Vibe-Research 无此机制 |
| synthesizer.py | 2KB | 复盘综合器 |
| state.py | 2KB | LangGraph 状态 |
| tools.py | 2KB | LLM 工具定义 |
| modes.py | 11KB | 个人模式卡 |
| stats_context.py | 14KB | 统计语境 |
| theme_tree.py | 12KB | 题材事件树 |
| breadth.py | 10KB | 市场宽度 |
| live_emotion.py | 6KB | 实时情绪 |
| intraday.py | 13KB | 盘中异动流 |
| verification.py | 17KB | 明日验证条件（Vibe-Research 有 S060 已实现） |
| weekly.py | 5KB | 周报 |
| overseas.py | 8KB | 隔夜外围 |
| positions.py | 6KB | 持仓（Vibe-Research 有 portfolio.py） |
| preflight.py | 5KB | 体检闸 |
| helpers.py | 1KB | 辅助函数 |
| backtest.py | 27KB | 市场现象统计（Vibe-Research 有 win_rate_tracker） |
| llm_errors.py | 3KB | LLM 错误处理 |
| deepdive/ (6个) | ~18KB | 个股深挖 agent（含 __init__.py），Vibe-Research 有 stock_data 路由 |
| __init__.py | 611B | 包初始化 |

### 1.3 路由来源

| 文件 | 判定 | 理由 |
|---|---|---|
| server.py | **提取路由端点清单后丢弃** | 66KB 单文件，是 vibe-astock 的路由来源。提取 journal/drift/risk 端点定义后不保留 |
| main.py | **丢弃** | CLI 入口，Vibe-Research 有 app.py |
| vr/ (12个) | **丢弃** | vibe-astock 的 vr/ 包是 Vibe-Research backend/ 的旧版 fork |

---

## 2. emotion_metrics.py vs Vibe-Research 逐函数 diff

### 2.1 函数清单 + 完整 import 依赖表（终审 T1 补全）

emotion_metrics.py 有 24 个 def（8 公开 + 16 私有）。移植的是 6 个公开函数，但它们经私有函数和 import 链引入了 4 个必须改写的依赖——此前审计只列公开函数，漏了这条链。

| duanxian import / 内联调用 | 行 | 消费方 | Vibe-Research 改写目标 | 改写类型 |
|---|---|---|---|---|
| `import urllib.request` + `batch_pct()` 内联裸调 `qt.gtimg.cn` | 7,29-55 | money_effect/consec_premium 的实时回退路径 | `data/sources/tencent.py::fetch_raw(codes)` (line 86) | **函数替换**（不是 import 改写——batch_pct 自带 urllib 裸调，spec 工作项 4/5 够不着它） |
| `from . import trade_calendar` | 11 | 全公开函数（prev_trade_date/is_settled/trade_dates_ending_at/live_quotes_are_close_of/quote_trade_day） | `vr_paths` 有 `prev_trading_date`/`is_trading_day`，但**无 `is_settled`/`trade_dates_ending_at`/`live_quotes_are_close_of`/`quote_trade_day`** — 需在 `backend/utils/vibe_astock_util.py` 补这四个函数（从 duanxian/trade_calendar.py 移植，基于 vr_paths.is_trading_day 实现） | **移植 trade_calendar.py 的缺失函数**（不是全盘丢弃） |
| `from .data import fetch_prev_pool`（惰性，`_settled_pool` line 165） | 165 | money_effect/consec_premium 的定稿记录路径 | `astock.em_zt_topic_pool("getYesterdayZTPool", ...)` — **⚠️ 字段映射工作**：fetch_prev_pool 返回归一化行（ret/prev_boards/limit_price/close），em_zt_topic_pool 返回原始池行（字段名不同），需显式字段映射 | **函数替换 + 字段映射** |
| `from .data import is_limit_up`（惰性，`_stats_from_pool` line 175） | 175 | _stats_from_pool 判涨停 | 基于映射后字段的机械判定（close ≈ limit_price） | **函数替换**（依赖前一项的字段映射） |
| `from .util import atomic_write_json` | 12 | day_summary 的缓存写入 | `backend/utils/vibe_astock_util.py::atomic_write_json` | **import 改写** |
| `from . import fetchers as dr` | 14 | _zt_pool 调 `dr.fetch_zt_pool()` | `astock.em_zt_topic_pool("getTopicZTPool", ...)` | **import 改写** |

**trade_calendar 缺失函数清单（需移植到 vibe_astock_util.py）：**

| duanxian/trade_calendar 函数 | vr_paths 等价物 | 处置 |
|---|---|---|
| `prev_trade_date(date)` | `vr_paths.prev_trading_date(date)` | ✅ 直接用 |
| `is_settled(date)` | 无 | **移植**（判断是否已收盘，可基于 `is_trading_day` + 当前时间判定） |
| `trade_dates_ending_at(date, lookback)` | 无 | **移植**（回溯 N 个交易日，基于 `is_trading_day`） |
| `live_quotes_are_close_of(date)` | 无 | **移植**（判断实时行情是否属于已收盘场次） |
| `quote_trade_day()` | 无 | **移植**（定位当前行情对应的交易日） |

| duanxian 函数 | Vibe-Research 对应 | 判定 |
|---|---|---|
| `promotion_rates()` | `market.py::_emotion` 的 promotion_rate (line 384) | **参照不移植** — Vibe-Research 已有，口径一致（len(lianban)/yzt_count） |
| `money_effect()` | **无直接对应**。STI 的 `prev_zt_performance` = `(zt/yzt)*100`，只是再涨停率一个维度 | **移植** — money_effect 给的是多维度分布（avg/median/positive_rate/limit_up_again_rate），STI 只取了 limit_up_again_rate 一个数。两者不重叠但有关联 |
| `consec_premium()` | **无** | **移植** — 昨日 2 板以上今日表现，全新指标 |
| `ladder_gap()` | `market.py::_emotion` 的 ladder (line 362) | **参照不移植** — Vibe-Research 已有连板梯队，但 duanxian 的 ladder_gap 有断层检测，**吸收断层检测逻辑** |
| `cycle_position()` | `limitup_sti/STIPhase` (概念重叠但计算不同) | **展示层补充**（见 §2.2） |
| `build_metrics()` | 无 | **移植**（聚合入口）；路由挂载点定死 → `routers/limitup/metrics.py`（终审 O4 定死） |
| `render_metrics()` | 无 | **移植**（文本渲染） |
| `day_summary()` | 无 | **移植**（原始读数） |

### 2.2 cycle_position() vs STIPhase 语义对比

| 维度 | cycle_position() | STIPhase |
|---|---|---|
| **输入** | 10 日涨停家数/最高连板/炸板率 | 8 维加权（含 prev_zt_performance 等） |
| **计算** | 三项归一化→均值→低谷定位→第几天 | 8 维加权得分→阈值分类 |
| **输出** | trough_date/day_n/pctile/trend | phase 枚举（启动/发酵/高潮/退潮/冰点/分歧） |
| **语义** | "这波情绪从哪天启动、今天第几天" | "现在处于什么阶段" |

**判定：** 概念重叠（都想定位"现在在周期的什么位置"）但计算方法和输出不同。cycle_position 更原始（基于 3 个硬指标），STIPhase 更综合（8 维加权）。

**建议：** Phase 2 先移植 cycle_position 作为 STIPhase 的**展示层补充**（给用户一个"第几天"的直观读数），不替换 STIPhase。两者并存，STIPhase 是主指标，cycle_position 是辅助读数。如果 Phase 2 grill 认为冗余，砍 cycle_position。

**⚠️ Oracle 🟠-6 双源分歧规则：** STIPhase 说"高潮"、cycle_position 说"启动第 2 天"时：
- (a) 前端同屏展示必须标注口径差异或主辅关系（STIPhase=主，cycle_position=辅）
- (b) cycle_position **不进 AI context、不进 journal 盖章**——堵住它悄悄变成第二事实源的路径
- journal 盖章字段只取 STIPhase 的 phase 枚举 + money_effect 的中位数

### 2.3 STI prev_zt_performance vs money_effect 重叠分析

| | STI prev_zt_performance | money_effect() |
|---|---|---|
| 公式 | `(zt / yzt) * 100` | avg/median/positive_rate/limit_up_again_rate |
| 粒度 | 全市场比率（今日涨停数÷昨日涨停数） | 按股粒度（昨日涨停股今日涨跌幅分布） |
| 重叠点 | ≈ money_effect.limit_up_again_rate | limit_up_again_rate 是 money_effect 的一个字段 |

**结论：** 不算重叠。STI 只取了"再涨停率"一个数，money_effect 给的是完整分布（中位数才是核心价值）。可以并存。

**⚠️ Oracle 🟠-7 等价声明修正：** 审计原文称 `STI.prev_zt_performance ≈ money_effect.limit_up_again_rate` 是错的。已核实 `service.py:185`：`prev_zt_performance = (zt/yzt)*100` = 今日涨停总数÷昨日涨停数（分子含首板），语义独立。真正接近 `limit_up_again_rate` 的是 `market.py:384` 的 `promotion_rate`（`len(lianban)/yzt_count`，lianban=今日 2 板+）。正确标注：**`STI.promotion_rate ≈ money_effect.limit_up_again_rate`；`prev_zt_performance` 是总数比，语义独立。**

---

## 3. 路由端点清单（从 server.py 提取）

### journal 相关（Phase 3 移植来源）

| 方法 | 路径 | 函数 | 请求体 | 响应 |
|---|---|---|---|---|
| GET | /api/journal/list | api_journal_list | `?limit=200` | `{trades:[...], total:int}` |
| GET | /api/journal/stats | api_journal_stats | — | `{available, overall, by_phase, by_playbook, by_planned, by_boards, by_hold, playbooks}` |
| POST | /api/journal/add | api_journal_add | `{date, code, name, playbook, pnl_pct?, as_planned?, note?, fills?, planned_stop?, planned_target?}` | `{ok, trade:{...}}` 或 `{error}` 400/500 |
| POST | /api/journal/update | api_journal_update | `?trade_id=xxx` + `{fills?, note?, as_planned?, planned_stop?, planned_target?}` (只处理出现的字段) | `{ok, trade:{...}}` 或 `{error}` 404/500 |
| POST | /api/journal/delete | api_journal_delete | `?trade_id=xxx` | `{ok, removed:1}` 或 `{error}` |
| GET | /api/journal/fees | api_journal_fees | — | `{commission_rate, commission_min, stamp_tax_rate, transfer_fee_rate, is_default}` |
| POST | /api/journal/fees | api_journal_save_fees | `{commission_rate, commission_min, stamp_tax_rate, transfer_fee_rate}` | `{ok, fees:{...}}` |

**fills 格式：** `[{side:"buy"/"sell", date:"YYYY-MM-DD", price:float, shares:float, fee?:float?}, ...]`

### risk 相关（Phase 3 移植来源）

| 方法 | 路径 | 函数 | 请求体 | 响应 |
|---|---|---|---|---|
| GET | /api/risk/report | api_risk_report | — | 风险报告 dict |
| GET | /api/risk/attribution | api_risk_attribution | — | 判断vs执行归因 dict |
| GET | /api/risk/excursion | api_risk_excursion | — | MFE/MAE dict |
| GET | /api/risk/at-risk | api_at_risk | — | 在险资金 dict |
| GET | /api/risk/equity-base | api_get_equity_base | — | `{base:float}` |
| POST | /api/risk/equity-base | api_set_equity_base | `{base:float}` | `{ok}` |
| GET | /api/risk/inbox | api_inbox | — | 异常交易收件箱 dict |
| GET | /api/risk/rules | api_risk_rules | — | 风险宪法 dict |
| POST | /api/risk/rules | api_risk_save_rules | `{rules:{...}}` | `{ok}` 或 `{error}` |

### archive/drift 相关（Phase 1 移植来源）

| 方法 | 路径 | 函数 | 请求体 | 响应 |
|---|---|---|---|---|
| GET | /api/archive/summary | api_archive_summary | — | `{available, days, date_from, date_to, size_mb, datasets, drift}` |
| GET | /api/drift | api_drift | — | `{available, field_drift, field_changed, structure, regime_events, summary}` |
| GET | /api/drift/calendar | api_get_regime_calendar | — | `{events:[{date, title, note?}]}` |
| POST | /api/drift/calendar | api_save_regime_calendar | `{events:[{date, title, note?}]}` | `{ok, count:int}` |

### Phase 2 情绪指标端点（Phase 2 路由来源）

| 方法 | 路径 | 函数 | 说明 |
|---|---|---|---|
| GET | /api/market/session | api_market_session | 此刻行情属于哪一场（盘前/盘中/已收盘/非交易日） |
| GET | /api/market/live-emotion | api_market_live_emotion | 实时打板情绪 |

**注意：** `build_metrics()`（emotion_metrics.py 的聚合入口）在 vibe-astock 中**没有独立路由**——它被 `_run_review()`（server.py:368）内部调用，结果写入复盘 JSON。Phase 2 移植时，`build_metrics()` 路由挂载点**定死 → `routers/limitup/metrics.py`**（终审 O4 定死，三选一悬空消除）。

### positions 相关（Phase 3 参考但不移植——Vibe-Research 有 portfolio.py）

| 方法 | 路径 | 函数 | 说明 |
|---|---|---|---|
| GET | /api/positions | api_positions | 持仓列表（从交易日志成交明细聚合） |
| POST | /api/positions/import-legacy | api_positions_import | 导入旧持仓 |

---

## 4. 验证项结果

### 4.1 许可证检查 ✅

vibe-astock `requirements.txt` 依赖：
- langgraph / langchain-core / langchain-openai（MIT）
- pydantic（MIT）
- python-dotenv（BSD）
- fastapi / uvicorn（MIT/BSD）
- requests（Apache-2.0）
- akshare（MIT）
- mini-racer（MIT）
- pytest（MIT）

**无 GPL/AGPL 传染。** Apache-2.0 许可证兼容。

### 4.2 archive.capture_day() 网络行为 ⚠️

**验证结果：确实发网络请求，且有两条路径。**

路径 1：`capture_day()` → `backtest._fetch_prev_pool(date)` → `import akshare as ak; ak.stock_zt_pool_previous_em()`（裸调 akshare，无防封）

路径 2：`capture_day()` → `market_facts.pools(date)` → 缓存未命中时 `import akshare as ak; ak.stock_zt_pool_em()` + `stock_zt_pool_zbgc_em()` + `stock_zt_pool_dtgc_em()`（三池连调，裸 akshare）

spec §4 合规表断言"archive 的 capture_day() 不额外发网络请求（用已缓存数据）"**不成立**。

**修正方案（Oracle 🟠-4 补全）：**
- `capture_day()` 的正确语义是"快照当天管线已取的数据"——只消费 Vibe-Research 当日已落盘的缓存/快照，定时任务排在主管线之后
- `_fetch_prev_pool` 改走 `astock.em_zt_topic_pool("getYesterdayZTPool", ...)` 并套上 `em_get` 限流/熔断器
- `pools` 路径一并覆盖：改读 Vibe-Research 的 `astock.em_zt_topic_pool` 缓存（24h HTTP 缓存已在 ARCHITECTURE.md 确认）
- 不裸调 akshare

### 4.3 Vibe-Research 复盘数据存储位置 ✅

**验证结果（Oracle 🟠-5 修正，删"推测"）：**

vibe-astock 的 `reflection._load_review()`（line 115，532 行文件）是它自己的函数，不是 Vibe-Research 的。

Vibe-Research 的复盘数据存储位置已确认：
- `backend/routers/review.py:42` — `GET /api/review/daily` 是日复盘入口，返回当日复盘数据
- `backend/snapshot_store.py` — 盘前快照存储 `<VR_DATA_DIR>/workflow/pre-market/<date>.json`（盘前预期快照，含情绪上下文）
- `backend/routers/review.py:66` — `GET /api/review/daily/backfill` 批量回填

**Phase 3 移植 journal.py 的 `_market_context()` 改写目标（多专家审查 critical #1 修订）：**
- 盘后复盘数据：走 **daily_review 磁盘持久化层**（`precompute_daily` 落盘 JSON，`get_daily_review` 先读磁盘 fallback `generate_review`），**零网络盖章**。不走 `routers/review.py` 的 `get_daily_review()` 路由入口（它同步调 `generate_review` 打 4 次 `em_zt_topic_pool`+`_sentiment`）
- 盘前快照（如需）：读 `snapshot_store.load_snapshot(date)`（盘前预期快照，不用于盘后盖章）
- **定死走磁盘持久化层**——journal 盖章是"当时面对的市场环境"，盘后复盘数据语义一致，且零网络

**⚠️ 终审 O1 修正（网络回归，多专家审查 critical #1 已落 spec 修订）：** `get_daily_review()` 底层调 `reviewer.generate_review(date)`，后者**同步打东财外部 API**（4 次 `em_zt_topic_pool` :153/157/161/165 + `_sentiment` :172，已核实）。vibe-astock 的 `journal.py:14` 原设计契约是"从已落盘读取，**不额外发起请求**"。当前方案下每记一笔交易触发一次东财调用——慢、加压、违背原模块契约 + em_get 防封底线。

**修正（多专家审查 critical #1）：** Phase 3 加硬约束"盖章零网络"。原"走 `generate_review` 下层已落盘缓存函数"**不成立**——`daily_review.py` 的 `_CACHE`(:32) 是 write-only（仅 :337 `precompute_daily` 写，零读，已核实 grep `_CACHE[` 只 :337 一处）。`snapshot_store.load_snapshot` 是盘前快照（语义"预期"非"实际"），不用于盘后盖章。**真实修正**：新建 daily_review 磁盘持久化层——`precompute_daily` 落盘 JSON 到 `<VR_DATA_DIR>/daily-review/<date>.json`，`get_daily_review` 先读磁盘 fallback `generate_review`。spec Phase 3 工作项 2 + G 门已同步修订（加"盖章路径零网络"验收项：monkeypatch `em_get` 断言未调用）。

### 4.4 模块总数 ✅

duanxian/ 下 **49 个 .py 文件**（含 deepdive/ 子包 6 个：`__init__/agents/data/graph/schemas/state`）。spec 声称"40+"属实。

### 4.5 server.py 路由端点 ✅

从 server.py 提取了 journal（7 个端点）、risk（9 个端点）、archive/drift（4 个端点）、positions（2 个端点）、Phase 2 情绪指标（2 个端点）。完整清单含请求体/响应契约见 §3。

---

## 5. 署名清单

需加 Apache-2.0 署名头的移植文件：

| 目标文件 | 来源 | 来源 commit |
|---|---|---|
| backend/utils/vibe_astock_util.py | duanxian/util.py + trade_calendar.py（4 函数）@3c3b7c8 | 3c3b7c8 |
| backend/journal.py | duanxian/journal.py@3c3b7c8 | 3c3b7c8 |
| backend/journal_risk.py | duanxian/at_risk.py + excursion.py + attribution.py + inbox.py + risk.py@3c3b7c8 | 3c3b7c8 |
| backend/emotion_metrics_ext.py | duanxian/emotion_metrics.py@3c3b7c8（部分函数） | 3c3b7c8 |
| backend/prompt_pack.py | duanxian/prompts.py@3c3b7c8 | 3c3b7c8 |
| backend/data/archive.py | duanxian/archive.py@3c3b7c8 | 3c3b7c8 |
| backend/data/drift.py | duanxian/drift.py@3c3b7c8 | 3c3b7c8 |

署名头格式：
```python
# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified
# Original author: Simon Lin (simonlin0423@gmail.com)
```

---

## 6. 审计结论

### 6.1 判定表确认

spec §附 的 Phase 0 审计判定表模板 **基本准确**，修正：
- **util.py 补入移植表**（Oracle 🔴-1 修正：6 个移植模块全部依赖它，Vibe-Research 无等价物）
- **inbox/attribution/risk 从丢弃表移入移植表**（Oracle 🟠-1 修正：随 journal_risk 一起移植）
- server.py 补入（提取路由端点后丢弃）
- deepdive/ 实为 6 个文件（含 __init__.py），非 5 个
- 其余 37 个模块全部确认丢弃
- 模块总数 49（非"40+"模糊表述）

### 6.2 对 spec 的影响

| spec 条目 | 影响 |
|---|---|
| §4 合规表 "archive 不额外发网络请求" | **断言不成立**，已修正为"capture_day 有两条网络路径（_fetch_prev_pool + market_facts.pools），均需改走 em_get + 只消费已落盘缓存" |
| Phase 3 `_market_context()` 改写目标 | **多专家审查 critical #1 修订**：走 daily_review 磁盘持久化层（`precompute_daily` 落盘 JSON + `get_daily_review` 先读磁盘 fallback `generate_review`），零网络盖章；不走 `routers/review.py:43 get_daily_review()` 路由入口（同步打东财），不走 vibe-astock 的 reflection._load_review |
| Phase 2 cycle_position vs STIPhase | **判定**：概念重叠但计算不同，cycle_position 作展示层补充；**双源规则**：不进 AI context、不进 journal 盖章 |
| Phase 2 money_effect vs STI | **判定**：不重叠可并存。**等价标注修正**：`STI.promotion_rate ≈ money_effect.limit_up_again_rate`（非 prev_zt_performance）；`prev_zt_performance` 是总数比，语义独立 |
| **Phase 0 新增 util.py 移植** | Oracle 🔴-1：6 个移植模块依赖 `atomic_write_json`/`china_now`/`china_today`/`validate_trade_date`（`safe_join` 仅丢弃模块消费按 YAGNI 不移植），Vibe-Research 无等价物。移植→`backend/utils/vibe_astock_util.py` |
| **边界测试升级** | Oracle 🟠-8：vibe-astock 原测试（test_core_logic.py:1067）是一跳字符串匹配，移植时按 grill 🔴-4 升级为闭包扫描 + 运行时工具遍历，原测试作参照不作成品 |

### 6.3 Phase 1–4 G 门状态

| Phase | G 门状态 | 说明 |
|---|---|---|
| Phase 0 | ✅ 本报告完成审计 + Oracle 审查 1 轮（1 🔴 + 7 🟠 已修正） | 🔴 util.py 已补入移植表；🟠 项已修正 |
| Phase 4 | ✅ 暂定 G 门可用 | TomorrowFocus 已砍掉；字段映射表：analyst_style→SYSTEM_PROMPT 分析框架段、analyst_len→篇幅约束、chat_guidance→个股约束段、judge_requirements 暂不接线 |
| Phase 2 | ✅ G 门可定稿 | cycle_position 判定已出（展示层补充+双源规则），money_effect 重叠判定已出（不重叠），路由挂载点需新建或挂 routers/review.py |
| Phase 3 | ✅ G 门可定稿（多专家审查 9 confirmed 已落 spec） | `_market_context` 走磁盘持久化层零网络（critical #1），路由端点契约 24 个（positions 2 仅参考），util.py 移植含 trade_calendar 4 函数 |
| Phase 1 | ✅ 暂定 G 门可用 | capture_day 双网络路径已验证（_fetch_prev_pool + market_facts.pools），修正方案已定（只消费已落盘缓存 + 改走 em_get） |

### 6.4 下一步

1. ✅ Oracle 重审已通过 + 终审 grill PASS + 多专家对抗审查 9 confirmed 已落 spec 修订（见 §7）
2. ✅ Phase 1–4 G 门已定稿
3. 按 Phase 4 → Phase 2（需 S133 先行）→ Phase 3 → Phase 1 顺序实施（Phase 4 可立即进；critical #1 是 Phase 3 唯一需代码决策阻断项，已定方案：daily_review 磁盘持久化层）

---

## 7. 多专家对抗审查结论（2026-09-05，已落 spec 修订）

**方法**：6 视角 finder（事实核实/工程底线/架构一致/内部矛盾/遗漏盲点/迁移可行）→ 3-lens 对抗验证（事实核实/方案可行/必要性，≥2 反驳则杀）→ 遗漏扫描 critic → R3 补漏 → 综合。首次 glm-5.2 网关挂 46 verdict+综合（DNS getaddrinfo failed），resume 指定 model:opus 重跑成功。

**9 条 confirmed findings（去重后，1 critical + 3 high + 4 medium + 1 low）**：

| # | severity | category | 问题 | fix |
|---|---|---|---|---|
| 1 | 🔴 critical | compliance | O1 修正称"走 generate_review 下层缓存函数"——该函数不存在（`_CACHE` write-only 仅 :337 写零读） | 新建 daily_review 磁盘持久化层（precompute_daily 落盘 JSON + get_daily_review 先读磁盘 fallback generate_review），零网络盖章 |
| 2 | 🟠 high | consistency | O1 文档三向矛盾未回流（§4.3 自相矛盾 + §6.2/spec:158 仍走 get_daily_review + G 门无零网络验收 + LRU 归属未定 + 行引用 :42→:43） | 统一至 O1 修正口径 + G 门加零网络验收 + LRU 归属 + 行引用 :43 |
| 3 | 🟠 high | consistency | trade_calendar 三处丢一处移植矛盾（spec §1.2+§附+audit §1.2 丢 vs audit §2.1 移植 4 函数） | 改"部分移植"，4 函数（is_settled/trade_dates_ending_at/live_quotes_are_close_of/quote_trade_day）→vibe_astock_util |
| 4 | 🟠 high | architecture | journal_risk.py 65KB 隐私边界漏（隐私约束只覆盖 journal.py） | 显式加 journal_risk.py 约束 + 闭包扫描 denylist 显式加"journal_risk" |
| 5 | 🟡 medium | consistency | util 函数清单四处不一致（safe_join/china_today） | 四处同步 atomic_write_json/china_now/china_today/validate_trade_date |
| 6 | 🟡 medium | completeness | Phase 2 工作项漏 batch_pct 内联 urllib + trade_calendar 移植 | 补工作项 8（batch_pct 改 fetch_raw）+ 9（trade_calendar 4 函数） |
| 7 | 🟡 medium | fact | 端点计数 24 vs 22（§3+§4.5 枚举 24，§6.2+spec:289 写 22） | 统一为 24（positions 2 仅参考不移植） |
| 8 | 🟡 medium | consistency | audit §6.4 stale（"过 Oracle 重审"pending vs spec:3"终审 PASS"done） | 更新反映终审后状态 |
| 9 | ⚪ low | fact | spec Phase 3 工作项 5 称"40 个 include_router"，实际 37 个（grep 验证） | 改 37 |

**verdict**：Phase 4（PromptPack 试点）**可立即进入实现**——critical/high 不触及 Phase 4。Phase 2 阻断=#3+#6；Phase 3 阻断=#1 critical+#2+#4+#7+#9（最重）。critical #1 是唯一需代码设计决策的阻断项，已定方案（daily_review 磁盘持久化层），其余 8 条廉价文档修正。

**阻断按落地顺序**：Phase 4 前（#5+#8 廉价文档）→ Phase 2（#3+#6）→ Phase 3（#1+#2+#4+#7+#9）。

**journal 全量**：`subagents/workflows/wf_0fb632d2-635/journal.jsonl`（78 原始 findings + 189 verdict）。完整 9 条 issue+fix：`tasks/wr760p76j.output`。
