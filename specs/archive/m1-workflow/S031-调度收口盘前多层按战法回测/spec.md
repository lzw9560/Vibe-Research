# Spec: S031 — 调度收口 + 盘前简报多层 + 交互式战法 + 按战法回测

> 状态：已实现 2026-08-07（30/30 tasks ✅；前端 tsc 0 error + vitest 172 全绿；后端 pytest 895 passed；playwright 路由冒烟过；:8900 启停优雅）
> 作者：Codex（grill 驱动）  日期：2026-08-07
> 关联：`../S011-调度收口/spec.md`（复活，本轮做 R3/R5/R7/R9/R11/R12 + 预计算 seed，砍 R6/R8/R10 推 S011b 第二轮）、`../S028-limitup-screener-fix/spec.md`（#3 自动预计算调度）、`../S029-gene-screener-wireup/spec.md`（GeneScreener）、`../S030-pre-market-multilayer/spec.md`（盘前简报多层，并入本 spec 重写）
>
> 级别：large（碰 em_get 外部源 + 多文件 + UX 重设计 + 新建回测引擎；feature 分支 + grill + playwright）
> 分支：`feature/S031-调度收口盘前多层按战法回测`（off develop）
> 两节并行实现：A（后端调度收口+预计算打通，让数据自动有）+ B（前端多层+交互式战法+按战法回测+WinRatePanel 对比）。A 的预计算 seed 不阻塞 B——B 验收用回溯历史交易日数据（qualified != 0），不强依赖 seed 已跑。

---

## 0. 范围切片与轮次

本 spec = S011 复活（切片）+ S030 重写 + 交互式战法 L2 + 按战法回测引擎。S011 全 12 项分两轮：**本轮（A）= R3/R5/R7/R9/R11/R12 + 预计算 seed**；**第二轮（S011b）= R6/R8/R10（状态机接线）**。R10 状态机不是本次目的，`workflow_state` 表本轮不建、不留 hook。

| S011 项 | 本轮 | S011b | 说明 |
|---|---|---|---|
| R1 cron 扩展 | ✅已做 | — | `cron_match` 已实现，不再动 |
| R2 import/add_run 去重 | ✅已做 | — | 不再动 |
| R3 SQLite WAL+busy_timeout | ✅本轮 | — | |
| R4 任务去重 | ✅已做 | — | 不再动 |
| R5 lifespan 优雅停止 | ✅本轮 | — | 最小版：CronScheduler.stop + portfolio 线程停止标志 |
| R6 create_task 挂主循环 | — | ✅ | 保留独立循环，第二轮改 |
| R7 三份预计算合并 | ✅本轮 | — | scheduler.py ↔ scheduled_tasks ↔ daily_review 收口到一处 |
| R8 portfolio except:pass | — | ✅ | 第二轮 |
| R9 统一 BEIJING_TZ | ✅本轮 | — | `_tick` 的 `datetime.now()` 带时区 |
| R10 状态机接线落库 | — | ✅ | **非本次目的**，`workflow_state` 表不建 |
| R11 删 _build_strategy_match 死代码 | ✅本轮 | — | |
| R12 删 scheduler.py | ✅本轮 | — | 最后一步 |
| 预计算 seed（cron+交易日历） | ✅本轮 | — | S028 §10 剔出的 #3 |

---

## 1. 问题 / 目标

**后端（A）**：S011 标"已实现"但 `scheduler.py` 仍在、`app.py` 跑两套并行调度器、预计算逻辑抄三份（`scheduler._precompute_limitup_async` / `scheduled_tasks._execute_limitup_precompute` / `daily_review.precompute_daily`）、无 lifespan 优雅停止、`scheduled_tasks._tick` 用无时区 `datetime.now()`、`_build_strategy_match` 死代码留着。盘后预计算无自动 seed（工作日 15:30 不自动跑），涨停基因数据靠手动 trigger，盘前简报常显示"未取得"。

**前端（B）**：盘前简报涨停基因因子被压成单层（`limitup_screener_factor.py` 只输出 1 个 `FunnelLayer`），用户无法逐层验证（打分→战法→仓位各留了什么、过滤了什么）。点候选整页跳路由打断视图。战法只读无交互（无法选战法反筛候选）。WinRatePanel 无真实按战法回测——`limitup_strategy.historical_win_rate` 是合成公式 `min(confidence*0.8+0.2,0.95)`（`limitup_strategy.py:685`），不是历史样本算的；`post_market_workflow._settle_recommendations` 返回 `[]` 桩；`backtest_lite` 只做 gene_score 散点无战法维度。

**目标**：A 让盘后预计算自动跑、收口到单一调度器、删死代码、补 WAL/lifespan/时区。B 让盘前简报呈现涨停基因因子三层漏斗（打分→战法→仓位）+ 候选池 R1/R2/R3 漏斗，逐层可验证；选战法可反筛候选（交互式 L2）；新建按战法回测引擎，WinRatePanel 展示真实回测胜率 vs 合成 historical_win_rate 对比。

---

## 2. 背景

### 调度现状（A）

- `app.py:40` `from scheduler import start_limitup_scheduler, start_portfolio_scheduler`；`app.py:72-73` 启两旧调度器；`app.py:164` `_st.start_scheduler()` 启 CronScheduler。**三套并行**，无 lifespan。
- `scheduler.py:16-61` `_precompute_limitup_async`：回溯 3 天，跑 limitup_screener/STI/auction/daily_review。仅 `LIMITUP_PRECOMPUTE=true` 时启动。
- `scheduled_tasks.py:465-511` `_execute_limitup_precompute`：几乎逐行复制 `scheduler.py` 的逻辑，加 `back_days` 参数。两份逻辑并行存活。
- `scheduled_tasks._loop`（:715）新建独立事件循环跑 `_ticker`，不挂 FastAPI 主循环（R6 第二轮改）。
- `scheduled_tasks._tick`（:735）`datetime.now()` 无时区；`cron_match` 纯函数比较无时区。`scheduler.py` 用了 `_ls.BEIJING_TZ`。
- `portfolio.py:184-198` `start_scheduler` 内 `while True` + `except Exception: pass`（R8 第二轮），无停止标志。
- `pre_market_workflow.py:199` `_build_strategy_match` 死代码（rg 确认无调用方）。
- 交易日历：`backtest_lite._next_trading_day` 读 `data/trading_calendar.json`（节假日），但该文件**当前不存在**（`find` 无结果），加载失败则只跳周末不跳节假日。`pre_market_workflow._resolve_date` 的回推循环第一天就 return（死代码），不回推交易日。

### 战法 + 胜率现状（B）

- **8 大战法**：`limitup_strategy.STRATEGY_REGISTRY`（`limitup_strategy.py:495`）：首板挖掘/连板接力/炸板回封/低吸龙头/反包战法/N字反击/平台突破/尾盘偷袭。每项含 entry_condition/stop_loss_pct/take_profit_pct/max_hold_days。
- **match_strategies**（:595）：对单股匹配战法，confidence 是每战法分支手写常量（首板=`total_score/100`、连板=`封板率/100`、炸板回封=0.6…）。**entry_price = round(gene.total_score,2)**（:680）——拿基因得分当价格代理，非真实价。
- **historical_win_rate**（:685）：`min(confidence*0.8+0.2,0.95)` 合成公式，非回测。`sample_size` 填 `gene.zt_count_250d`（冒充样本）。
- **三胜率源对比**：
  - `limitup_strategy.historical_win_rate`：合成，非真实。
  - `backtest_lite`：gene_score vs 次日收益散点 + 分位，**无战法维度**。
  - `win_rate_tracker.get_strategy_stats(strategy)`：读 `winrate.db` 的 `winrate_records`（`POST /api/n/records` 用户录入），按战法统计——**真实但靠用户手填**。
  - `post_market_workflow._settle_recommendations`：返回 `[]` 桩，系统自动结算死。
- **PreMarketReport 三层数据已就位**（`pre_market_workflow.py:76-88`）：`candidates`/`strong_candidates`/`filtered_out`→L1；`strategy_matches`→L2；`position_suggestions`→L3。但 L2 限 `pool.candidates[:20]`（:147）。
- **PositionSuggestion 双定义**：`pre_market_workflow.py:62`（@dataclass）vs `position_advisor.py:17`（普通类），结构相同但不同类。`report.position_suggestions` 从 `advise_batch()` 填，返 advisor 版，report 标 dataclass 版。
- **前端**：`PreMarketBriefing.tsx` 的 `FactorSection` 渲染单层 + conditions chips（S028 已加）。`useFunnelLayers` hook（`topology.ts:27`）已有。`WinRateView`（`/backtest`）挂 StatsMetrics/TrendsChart/BreakdownTable/RecordsForm，BreakdownTable 按战法下钻读 `winrate.db`。
- **gene_scores DB**：`limitup_screener/vibe_research.db` 存历史 8 天（07-28~08-06，1654 行），随 seed 积累变厚。表结构含 date/code/total_score/factor_*/qualify/high_gene/zt_count_250d。`load_gene_scores(date)`（`data.py:99`）能从 DB 重构 `GeneScore`。

---

## 3. 需求清单

### A 节：调度收口 + 预计算打通

- [ ] R3 SQLite WAL + busy_timeout：`scheduled_tasks._init_db` 加 `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`。
- [ ] R5 lifespan 最小版：`app.py` 用 FastAPI `lifespan=` 注册启动/停止；停止时 `CronScheduler.stop()` + portfolio 线程停止标志（本轮只加停止标志不删 except:pass，R8 第二轮）。
- [ ] R7 三份预计算合并：删 `scheduler.py._precompute_limitup_async`，统一到 `scheduled_tasks._execute_limitup_precompute`（保留 `back_days` 参数）；`daily_review.precompute_daily` 不在 `_execute_daily_data_refresh` 里重复调（由 limitup_precompute 统一驱动）。单一事实源。
- [ ] R9 统一 BEIJING_TZ：`scheduled_tasks._tick`/`_should_run` 的 `datetime.now()` 改 `datetime.now(BEIJING_TZ)`；cron_match 带时区比较。
- [ ] R11 删 `pre_market_workflow._build_strategy_match`（:199-230）死代码。
- [ ] R12 删 `backend/scheduler.py`；`app.py:40` 去 `from scheduler import ...`；`app.py:72-73` 删两旧启动调用。最后一步（补测+seed 验证后删）。
- [ ] R13 预计算 seed（S028 #3）：`scheduled_tasks` 启动时 seed 默认任务——`limitup_precompute`，cron `30 15 * * 0-4`（工作日 15:30），payload `{back_days:3}`。交易日判断：cron `1-5` 已限工作日（跳周末）；节假日表 `data/trading_calendar.json` 本轮不建，非交易日由 `get_screener_result` 返空涨停池自然处理，注释标明"节假日精确判断推 S011b"。

### B 节：盘前简报多层 + 交互式战法 + 按战法回测

- [ ] R14 涨停基因因子多层化（后端）：`limitup_screener_factor.fetch()` 输出 3 个 `FunnelLayer`——L1 打分(五维+阈值)、L2 战法匹配、L3 仓位建议——各层 conditions/passed/filtered_out/input/output 齐全；保留 S028 的 data_status/conditions。
- [ ] R15 去 `[:20]` 上限：`pre_market_workflow.py:147` `pool.candidates[:20]` → 全部 qualified（match 全部）。性能基线测 50/80/100 qualified 三档，确认单只 `_strategy_matcher.match` 耗时 + 总时延可接受。
- [ ] R16 盘前简报渲染因子多层（前端）：`FactorSection` 渲染 `factor.layers`（3 层）成漏斗卡片（复用 `FunnelLayerCard` 公共组件，从 `FunnelLayers.tsx` 提取）。
- [ ] R17 候选池 R1/R2/R3 漏斗嵌入盘前简报：`PreMarketBriefing` 调 `useFunnelLayers`（既有）→ 渲染第二组漏斗。
- [ ] R18 候选点击改侧边抽屉：新建 `Sheet`（portal + 遮罩 + Esc）；`CandidateDetail` 抽出 `CandidateDetailPanel({code})`（纯展示不依赖路由 params），路由页 thin 包装调 Panel，抽屉调 Panel。
- [ ] R19 交互式战法 L2：L2 层用户可选战法（多选 chips，8 大战法）→ 前端即时反筛 L1/L2 的 passed（按 `best_strategy`/`strategy_code` 过滤）。选"全部"恢复。反筛纯前端，不重新请求后端。
- [ ] R20 按战法回测引擎（后端新模块）：对 `STRATEGY_REGISTRY` 8 战法各跑历史 lookback_days，输出每战法真实胜率/平均收益/样本量。**入场价用次日开盘价**（复用 `backtest_lite._calc_next_day_return` 的 K 线取数），出场用 `max_hold_days` 后收盘或触发 stop_loss_pct/take_profit_pct 提前平。**只复用 `match_strategies` 的战法匹配判定**（哪些股命中哪个战法），不复用它输出的 entry_price（:680 是假的）。
- [ ] R21 回测防封：回测引擎**只跑 DB 已有历史日**（`vibe_research.db` 的 gene_scores），lookback_days 按实际可用天数截断，不触发 em_get 回溯。随预计算 seed 积累扩展。
- [ ] R22 WinRatePanel 对比展示：盘前简报加 WinRatePanel——并列展示①按战法回测真实胜率（R20）、②合成 historical_win_rate（标注"合成估算非回测"）。两列对比。用户录入胜率（`winrate.db`）作第三面板靠后（已有 `/api/winrate/strategy`）。
- [ ] R23 页内布局重整：纵向流——市场情绪 → 涨停基因因子漏斗(三步) → 候选池漏斗(R1-R3) → WinRatePanel(战法胜率对比) → 候选详情(抽屉)。
- [ ] R24 GeneScreener 定位厘清：盘前简报头部链 `/limitup/gene`；GeneScreener 页头回链 + 定位说明。

---

## 4. 受影响文件

### A 节

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | R3 `_init_db` 加 WAL/busy_timeout；R9 `_tick`/`_should_run` BEIJING_TZ；R7 确认单一预计算源；R13 seed 默认任务 |
| `backend/app.py` | R5 lifespan（`@asynccontextmanager`）；R12 删 `from scheduler` + 旧启动调用 |
| `backend/scheduler.py` | 🗑️删（R12 最后一步） |
| `backend/pre_market_workflow.py` | R11 删 `_build_strategy_match`(:199-230)；R15 去 `[:20]`(:147) |
| `backend/portfolio.py` | R5 加停止标志（`_stop: threading.Event`），`while True`→`while not _stop.is_set()`；except:pass 留第二轮 |

### B 节

| 文件 | 改动 |
|---|---|
| `backend/factors/limitup_screener_factor.py` | R14 fetch() 拼 3 FunnelLayer（打分/战法/仓位），复用 report 既有字段 |
| `backend/strategies/strategy_backtest.py`（新） | R20/R21 按战法回测引擎：逐历史日取 DB gene_scores → match_strategies 判定 → K 线算入场/出场 → 按战法聚合胜率 |
| `backend/routers/strategy.py` | R20 加 `GET /api/strategy/backtest?lookback_days=` → 返 8 战法 {win_rate,avg_return,sample_size} |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | R16/R17/R19/R23：FactorSection 多层 + FunnelLayers 嵌入 + 战法反筛 chips + WinRatePanel + 布局重整 |
| `frontend/src/components/ui/Sheet.tsx`（新） | R18 轻量侧边抽屉（portal + 遮罩 + Esc 关） |
| `frontend/src/pages/workflow/CandidateDetail.tsx` | R18 抽出 `CandidateDetailPanel({code})` 供抽屉复用；路由页 thin 包装 |
| `frontend/src/components/ui/FunnelLayerCard.tsx`（新） | R16 从 `FunnelLayers.tsx` 提取公共漏斗卡片组件 |
| `frontend/src/pages/limitup/GeneScreener.tsx` | R24 页头回链盘前简报 + 定位说明 |
| `frontend/src/lib/query/strategy.ts`（新或并入既有） | R22 `useStrategyBacktest(lookback_days)` hook |

---

## 5. 设计方案

### A 节

- **不换框架**：保留 `CronScheduler` 独立事件循环（R6 推第二轮），本轮只加 lifespan 停止 + WAL + 时区 + 合并 + seed + 删旧。
- **lifespan 最小版**：`@asynccontextmanager`，startup 调 `_st.start_scheduler()` + `_start_portfolio_thread()`，shutdown 调 `_st.get_scheduler().stop()` + `_portfolio_stop.set()`。不 join daemon 线程（自然退出）。
- **WAL**：`_init_db` 加 PRAGMA，连接复用 `check_same_thread=False` + `_DB_LOCK`。不引连接池（YAGNI）。
- **删 scheduler 顺序**（硬约束）：A1-A5 完成 + 单测过 → seed 验证 → `app.py` 删 import + 旧调用 → `git rm scheduler.py`。
- **预计算 seed**：`_ensure_seed_tasks()` 在 `start_scheduler` 内调，幂等（查 name 已存在则跳过）。cron `30 15 * * 0-4`。交易日由 cron 限工作日 + `get_screener_result` 返空自然处理非交易日。
- **状态机**：本轮**不做**（R10 推 S011b），`workflow_state` 表不建、不留 hook。

### B 节

- **因子三层**（R14）：`limitup_screener_factor.fetch()` 拼 3 `FunnelLayer`，数据全从 `report` 既有字段取（candidates/filtered_out→L1，strategy_matches→L2，position_suggestions→L3），禁臆造。保留 S028 `data_status`/`scanned_count` 移入 L1。
- **去 [:20]**（R15）：`match_strategies` 纯内存计算（读 gene.factors/zt_count_250d，不调 astock），50/100 qualified <1s 可接受。`PositionAdvisor.advise_batch` 同理纯内存。无 em_get，无封号。
- **FunnelLayerCard 抽取**（R16/R17）：从 `FunnelLayers.tsx` 提取公共卡片（conditions+passed+filtered_out+input→output 计数），候选池页与盘前简报共用。conditions chips 样式复用，但因子层 conditions（权重公式）vs 候选池 conditions（过滤规则）语义不同——因子层 chips 用 info 色，候选池用 neutral，视觉区分。
- **Sheet 抽屉**（R18）：`createPortal` 到 body，遮罩 + Esc + 点遮罩关。`CandidateDetailPanel` 纯展示调 `candidatesApi.diagnosis(code)`，内 Skeleton loading。路由页 thin 包装调 Panel，抽屉调 Panel。
- **交互式战法 L2**（R19）：L2 层加战法多选 chips（8 大战法），反筛纯前端 `layer.output.filter(c => selected.has(c.best_strategy))`，选"全部"清空恢复。不重新请求后端。
- **按战法回测引擎**（R20/R21）：新建 `strategy_backtest.py`。流程：`_get_available_dates(lookback_days)` 查 DB DISTINCT date → 逐日 `load_gene_scores(date)` 重构 GeneScore → `match_strategies` 判定命中战法 → 逐 (code, strategy, date) K 线算入场(次日开盘)/出场(max_hold_days 收盘或 stop_loss/take_profit 提前平) → 按 strategy_code 聚合 win_rate/avg_return/sample_size。**只跑 DB 已有日**（当前 8 天，随 seed 扩展），lookback_days 按实际截断，不触发 em_get。
- **WinRatePanel 对比**（R22）：两列对比表——左列 R20 真实回测胜率，右列合成 `historical_win_rate`（`min(confidence*0.8+0.2,0.95)` 重算，标注"估算"）。用户录入胜率第三面板靠后。
- **布局**（R23）：纵向分区——①市场情绪 ②涨停基因因子漏斗(三步) ③候选池漏斗(R1-R3) ④WinRateComparePanel ⑤抽屉层。每区 SectionHeader。

---

## 6. 验收标准

### A 节

- [ ] A1 SQLite WAL+busy_timeout 启用：`scheduled_tasks._init_db` 后 `PRAGMA journal_mode` 返 `wal`；并发写无 `database is locked`。
- [ ] A2 lifespan 优雅停止：进程退出时 `CronScheduler.stop()` 被调、`_portfolio_stop.set()` 被调、daemon 线程自然退出。
- [ ] A3 三份预计算收口：`scheduler.py` 已删；`scheduled_tasks._execute_limitup_precompute` 是唯一预计算入口；`_execute_daily_data_refresh` 不再调 `daily_review.precompute_daily`。
- [ ] A4 `_tick` 用 `datetime.now(BEIJING_TZ)`；cron 命中带时区比较。
- [ ] A5 `_build_strategy_match` 已删；rg 无引用。
- [ ] A6 `scheduler.py` 已删；`app.py` 无 `from scheduler`；`app.py` 无 `start_limitup_scheduler`/`start_portfolio_scheduler` 旧调用。
- [ ] A7 seed 默认任务：`limitup_precompute` cron `30 15 * * 0-4` 存在于 `scheduled_tasks` 表；幂等（重启不重复创建）。
- [ ] A8 `pytest -m "not live"` 全过（含 WAL/cron/seed 新测）。
- [ ] A9 :8900 启动/停止优雅；盘后预计算触发一次验证无并发重复。

### B 节

- [ ] B1 盘前简报涨停基因因子呈现 L1/L2/L3 三层卡，每层 conditions+passed+filtered_out+输入→输出计数可见。
- [ ] B2 候选池 R1/R2/R3 漏斗在盘前简报同一页可见（第二组），逐层可验证。
- [ ] B3 点任一层候选 → 右侧抽屉弹诊断卡（不整页跳路由）；Esc/点遮罩可关；`/workflow/candidates/:code` 直链仍可用。
- [ ] B4 L2 层可选战法（多选 chips）→ 前端即时反筛 passed（按 best_strategy 过滤）；选"全部"恢复；反筛不重新请求后端。
- [ ] B5 `pre_market_workflow.py:147` 无 `[:20]`；match 全部 qualified。性能基线：50/100 qualified 三档总时延 <1s。
- [ ] B6 `GET /api/strategy/backtest?lookback_days=60` 返 8 战法各 {win_rate, avg_return, sample_size}；sample_size = DB 实际策略命中交易数（匹配全部 gene_scores 不限 qualify；可能 > available_days）；available_days 标实际回测天数。
- [ ] B7 WinRatePanel 展示真实回测胜率 vs 合成 historical_win_rate 两列对比；合成列标注"估算"。
- [ ] B8 页内布局：情绪→因子漏斗→候选池漏斗→WinRatePanel 纵向清晰分区，无明显跳跃。
- [ ] B9 GeneScreener 有回链 + 定位说明；盘前简报有去 GeneScreener 的入口。
- [ ] B10 前端 tsc + 既有测试通过；新增 Sheet/FunnelLayerCard/StrategyBacktest 测试。
- [ ] B11 playwright 关键路由（pre-market → 战法筛选 → 抽屉 → 候选直链）冒烟。
- [ ] B12 验收用回溯历史交易日数据（qualified != 0）：用 DB 已有 8 天中找有 qualified 的交易日验收 L2/L3 非空；不做 0 数据降级（qualified=0 日子 L2/L3 显示空，用户自行切换日期）。
- [ ] B13 数据：各层 passed/filtered 基于后端实际字段，禁臆造。回测胜率基于 DB gene_scores + K 线实际价，禁合成冒充真实。

---

## 7. 合规与工程底线自查

- [ ] 调度逻辑不引入方向性判断；预计算走 `em_get` 限流+熔断，不裸调。
- [ ] 战法匹配/回测胜率属客观历史统计特征，用户可见输出挂轻量风险提醒"历史统计特征，市场有风险"。
- [ ] 判断可复现：层 conditions/passed/filtered 基于后端 report/funnel 实际字段；回测胜率基于 DB gene_scores + K 线实际价，禁臆造/心算。
- [ ] 涨停股 code/name/得分/战法属公开榜单客观事实，可呈现（CLAUDE.md §1.1 私人助理口径）。
- [ ] 走既有 `/api/workflow/pre-market` + `/api/workflow/funnel/layers` + `/candidates/{code}/diagnosis` + `/api/limitup/screener`（em_get 限流+熔断已有），不新增裸调。
- [ ] 回测引擎只读 DB 已有 gene_scores（不触发 em_get 回溯）+ `astock.kline`（mootdx 本地，非 em_get）。
- [ ] 私有数据不涉；不动 `.vibe-research/`。

---

## 8. 测试计划

- **A 节单测**：test_wal_pragma（`_init_db` 后 journal_mode=wal）、test_seed_idempotent（重复 start_scheduler 不重复创建 limitup_precompute）、test_lifespan_shutdown（stop 被调 + _portfolio_stop.set 被调）、test_tick_beijing_tz（now 带 BEIJING_TZ）。
- **B 节单测**：`test_limitup_screener_factor_layers`（fetch 返 3 层 FunnelLayer，L1/L2/L3 passed/filtered 正确）、`test_strategy_backtest`（mock DB gene_scores + K 线 → 8 战法胜率聚合正确）、`test_no_20_cap`（match 全部 qualified，不限 20）。
- **前端**：`Sheet`（开/关/Esc）、`FunnelLayerCard`（多层渲染 + conditions）、`CandidateDetailPanel`（诊断卡渲染）、`StrategyFilter`（多选反筛）。
- **集成**：PreMarketBriefing 挂载 → 因子三层 + 候选池 R1-R3 + WinRatePanel 均渲染（mock query）。
- **playwright（large 必）**：`/workflow/pre-market` 加载 → 选战法反筛 → 点候选 → 抽屉开 → 关 → 直链 `/workflow/candidates/:code` 仍渲染。
- **离线**：`cd backend && .venv/bin/python -m pytest -m "not live"` 全过。

---

## 9. 风险与回滚

- **删 scheduler 前 scheduled_tasks 需验证**：顺序硬约束——A1-A5 + seed 验证后才删。回滚：`git checkout scheduler.py` + 恢复 app.py import。
- **回测引擎 K 线取数慢**：`astock.kline` 逐股逐日调，8 天 × ~80 股 = ~640 次 mootdx 调用。mootdx 本地无封号风险，但慢。**缓存**：回测结果缓存到 `strategy_backtest` 内存 + TTL（12h），重复请求不重算。回滚：删 strategy_backtest.py + 端点。
- **去 [:20] 性能**：match_strategies 纯内存，已验证无 astock 调用。最坏 100 qualified × 单只 <10ms = <1s。若超预期，加并行 `match_batch`（已有）。
- **FunnelLayerCard 抽取**：候选池页（`/candidates`）与盘前简报共用，改动影响候选池页，需回归测试。
- **回滚**：feature 分支，未合 develop 前 `git checkout develop` 即隔离；合并用 `--squash` 一 commit。

---

## 10. 决策记录（2026-08-07，grill 3 轮）

- **S011 切片**：本轮做 R3/R5/R7/R9/R11/R12 + 预计算 seed；砍 R6/R8/R10 推 S011b 第二轮。R10 状态机非本次目的，`workflow_state` 表不建。
- **胜率数据源**：选 (a) 新建按战法回测引擎（真实 K 线算盈亏），与合成 historical_win_rate 并列对比展示。用户录入胜率（winrate.db）优先级靠后。
- **回测引擎**：只复用 match_strategies 的战法匹配判定，不复用其 entry_price（假值）。入场价 = 次日开盘价（K 线），出场 = max_hold_days 收盘或 stop_loss/take_profit 提前平。只跑 DB 已有历史日，不触发 em_get 回溯。
- **去 [:20] 上限**：放宽到全部 qualified；match_strategies 纯内存无 em_get。
- **候选展开**：侧边抽屉（Sheet），不整页跳；路由保留供直链。
- **两套漏斗**：都默认展开，分区标题区分因子三步 vs 候选池 R1-R3。
- **qualified!=0 验收**：用 DB 已有历史交易日（回溯），不做 0 数据降级（qualified=0 日子 L2/L3 显示空，用户自行切换日期）。
- **交易日历**：`trading_calendar.json` 本轮不建，cron `1-5` 跳周末 + screener 返空自然处理非交易日。精确节假日判断推 S011b。
- **S027**：不合入本 spec（ai_proxy 与盘前简报无关，不合）。
