# Tasks: S031 — 调度收口 + 盘前简报多层 + 交互式战法 + 按战法回测

> 对应 `spec.md` + `plan.md`。A/B 两节并行，按依赖排序。
> 删 `scheduler.py` 是 T7 最后一步（硬约束：T1-T6 验证后删）。
> 状态机（R10）推 S011b 第二轮，不在本 tasks。

## 任务清单

| ID | 任务 | 需求 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|---|
| **A 节：调度收口 + 预计算** | | | | | |
| T1 | `scheduled_tasks._init_db` 加 `PRAGMA journal_mode=WAL` + `busy_timeout=30000` | R3 | — | `PRAGMA journal_mode` 返 `wal`；并发写无 `database is locked` | ✅ |
| T2 | `app.py` lifespan：`@asynccontextmanager` 启停 `CronScheduler` + `_portfolio_stop: threading.Event`（`while not _portfolio_stop.wait(interval)` 替 `time.sleep`） | R5 | T1 | 进程退出时 `stop()` + `_portfolio_stop.set()` 被调；daemon 线程自然退出 | ✅ |
| T3 | `scheduled_tasks._tick`/`_should_run` 改 `datetime.now(BEIJING_TZ)`；导入 `from limitup_screener import BEIJING_TZ` | R9 | — | `now` 带 `Asia/Shanghai` tzinfo；cron 命中带时区比较 | ✅ |
| T4 | `_execute_daily_data_refresh` 删 `daily_review.precompute_daily` 重复调用（只保留 `portfolio.refresh_all`）；预计算统一由 `_execute_limitup_precompute` 驱动 | R7 | T3 | `_execute_daily_data_refresh` 无 daily_review 调用；`_execute_limitup_precompute` 是唯一预计算入口 | ✅ |
| T5 | `scheduled_tasks._ensure_seed_tasks()`：seed `limitup_precompute` cron `30 15 * * 0-4` payload `{back_days:3}`，幂等（查 name 已存在则跳过）；`start_scheduler` 末尾调 | R13 | T3 | 重启不重复创建；`scheduled_tasks` 表有 `limitup_precompute` 行 | ✅ |
| T6 | `pre_market_workflow.py:199-230` 删 `_build_strategy_match` 死代码 | R11 | — | rg 无 `_build_strategy_match` 引用 | ✅ |
| T7 | **删 `backend/scheduler.py`**；`app.py:40` 删 `from scheduler import`；`app.py:72-73` 删 `start_portfolio_scheduler`/`start_limitup_scheduler` 旧调用 | R12 | T1-T6 全验证 | `scheduler.py` 不存在；`app.py` 无 `from scheduler`；:8900 启停正常 | ✅ |
| T8 | A 节单测：`test_wal_pragma` / `test_seed_idempotent` / `test_lifespan_shutdown` / `test_tick_beijing_tz` | R3/R5/R9/R13 | T1-T5 | `pytest -m "not live"` 全过 | ✅ |
| T9 | :8900 启停冒烟 + 盘后预计算触发一次验证无并发重复 | A1/A9/A3 | T7,T8 | 启停优雅；预计算无并发重复 | ✅ |
| **B 节：盘前简报多层 + 交互式战法 + 回测** | | | | | |
| T10 | `pre_market_workflow.py:147` `pool.candidates[:20]` → 全部 qualified；性能基线测 50/80/100 qualified 三档 | R15 | — | 无 `[:20]`；100 qualified 总时延 <1s | ✅ |
| T11 | `limitup_screener_factor.fetch()` 拼 3 `FunnelLayer`（L1 打分/L2 战法/L3 仓位），各层 conditions/passed/filtered_out/input/output；S028 `data_status` 移入 L1 | R14 | T10 | fetch 返 3 层；L2 passed = `strategy_matches` code 集；L3 = `position_suggestions` code 集 | ✅ |
| T12 | 后端单测 `test_limitup_screener_factor_layers`：3 层 passed/filtered 正确 + 0 qualified 场景 | R14 | T11 | 3 层 FunnelLayer 断言通过 | ✅ |
| T13 | `FunnelLayerCard` 从 `FunnelLayers.tsx` 抽取为公共组件（conditions+passed+filtered_out+input→output 计数）；因子 conditions 用 info 色，候选池 neutral | R16 | T11 | `FunnelLayers` 与 `FactorSection` 共用；候选池页回归测过 | ✅ |
| T14 | `PreMarketBriefing.tsx` `FactorSection` 渲染 `factor.layers` 多层 `FunnelLayerCard` | R16 | T13 | 盘前简报呈现 L1/L2/L3 三层卡 | ✅ |
| T15 | `PreMarketBriefing.tsx` 调 `useFunnelLayers` 嵌入候选池 R1/R2/R3 第二组漏斗 | R17 | T13 | 候选池 R1-R3 在盘前简报同页可见 | ✅ |
| T16 | `Sheet.tsx` 新建（portal + 遮罩 + Esc + 点遮罩关）；组件单测（开/关/Esc） | R18 | — | Esc/点遮罩可关；单测过 | ✅ |
| T17 | `CandidateDetail.tsx` 抽出 `CandidateDetailPanel({code})`（纯展示 + Skeleton loading）；路由页 thin 包装调 Panel | R18 | T16 | 抽屉内嵌 Panel；`/workflow/candidates/:code` 直链仍渲染 | ✅ |
| T18 | `PreMarketBriefing.tsx` 点候选 `setDrawerCode(code)` → `<Sheet><CandidateDetailPanel/>` 不 `navigate` | R18 | T16,T17 | 点候选弹抽屉不整页跳 | ✅ |
| T19 | `StrategyFilter` 组件：8 大战法多选 chips + "全部"；反筛纯前端 `layer.output.filter(c => selected.has(c.best_strategy))` | R19 | T14 | 选战法即时反筛 passed；选"全部"恢复；不请求后端 | ✅ |
| T20 | `backend/strategies/strategy_backtest.py` 新建 `StrategyBacktester` 类：`_get_available_dates`(只查 DB) + `_backtest_single`(次日开盘入场/max_hold 收盘或 stop/profit 平) + `_aggregate`(按战法聚合) + 12h 缓存 | R20,R21 | T10 | 8 战法各返 win_rate/avg_return/sample_size；`available_days` 标实际天数；不触发 em_get | ✅ |
| T21 | `routers/strategy.py` 加 `GET /api/strategy/backtest?lookback_days=60` 端点（`asyncio.to_thread` 包） | R20 | T20 | 端点返 8 战法 `{win_rate,avg_return,sample_size,available_days}` | ✅ |
| T22 | 后端单测 `test_strategy_backtest`：mock DB gene_scores + K 线 → 8 战法胜率聚合正确；`sample_size` 不超 DB 实际天数 | R20,R21 | T20 | mock 数据回测断言通过 | ✅ |
| T23 | `frontend/src/lib/query/strategy.ts` `useStrategyBacktest(lookback_days)` hook | R22 | T21 | hook 取数正常 | ✅ |
| T24 | `WinRateComparePanel` 组件：两列对比表（左=回测真实胜率 / 右=合成 `min(confidence*0.8+0.2,0.95)` 标"估算"）+ `available_days` 标注 | R22 | T23 | 两列对比可见；合成列标注"估算" | ✅ |
| T25 | `PreMarketBriefing.tsx` 嵌入 `WinRateComparePanel` | R22 | T24 | WinRatePanel 在盘前简报可见 | ✅ |
| T26 | `PreMarketBriefing.tsx` 布局重整：纵向分区（情绪→因子漏斗→候选池漏斗→WinRatePanel→抽屉）+ `SectionHeader` | R23 | T14,T15,T18,T25 | 纵向清晰分区，无明显跳跃 | ✅ |
| T27 | `GeneScreener.tsx` 页头加回链"← 回盘前简报" + 副标题"配置伴随页"；`PreMarketBriefing` 头部链 `/limitup/gene` | R24 | — | 双向回链 + 定位说明可见 | ✅ |
| T28 | 前端 tsc + vitest 全过（含 Sheet/FunnelLayerCard/StrategyFilter/CandidateDetailPanel/WinRateComparePanel 新测） | B10 | T14-T27 | tsc 0 error；vitest 全绿 | ✅ |
| T29 | playwright 冒烟：`/workflow/pre-market` 加载 → 选战法反筛 → 点候选抽屉 → 关 → 直链 `/workflow/candidates/:code` 仍渲染 | B11 | T28 | 路由冒烟全过 | ✅ |
| T30 | 验收用回溯历史交易日（DB 已有 8 天，找 qualified!=0 的日）确认 L2/L3 非空；qualified=0 日 L2/L3 显示空（不做降级） | B12 | T12,T22 | 回溯日 L2/L3 有数据；0 日显示空 | ✅ |

## 依赖图

```
==== A 节（后端调度，可先于 B 独立推进） ====
T1(WAL) ─ T2(lifespan)
T3(BEIJING_TZ) ─ T4(预计算合并) ─ T5(seed)
T6(删死代码)                    # 独立，无依赖
T1,T2,T3,T4,T5,T6 全验证 ─ T8(单测) ─ T7(删 scheduler.py) ─ T9(启停冒烟)

==== B 节（前端+回测，A/B 并行） ====
T10(去[:20]) ─ T11(因子三层) ─ T12(后端单测)
                                   └─ T13(FunnelLayerCard 抽取) ─ T14(因子多层渲染) ─ T19(战法反筛)
                                                                   └─ T15(候选池漏斗嵌入)
T16(Sheet) ─ T17(CandidateDetailPanel) ─ T18(抽屉接线)
T20(回测引擎) ─ T21(端点) ─ T22(后端单测) ─ T23(hook) ─ T24(WinRateComparePanel) ─ T25(嵌入)
T27(GeneScreener 回链)                    # 独立
T14,T15,T18,T19,T25 ─ T26(布局重整) ─ T28(tsc+vitest) ─ T29(playwright) ─ T30(回溯验收)
```

## 并行策略

- **A 节**（T1-T9）和 **B 节**（T10-T30）可两人/两 agent 并行。
- A 节内部：T1→T2、T3→T4→T5 有序；T6 独立可随时做；T7 删 scheduler 是 A 节收尾硬门（T1-T6 全验证后）。
- B 节内部：T10 最先（无依赖，去上限后 L2 才有完整数据）；T16/T27 独立可并行；T20 回测引擎可独立于前端推进；汇合点在 T26（布局重整需 T14/T15/T18/T25 都就位）。
- **A 不阻塞 B**：B 验收用 DB 已有 8 天历史日，不强依赖 A7 seed 已跑。

## 合规检查点

- T4/T5 预计算走 `em_get` 限流+熔断，不裸调（A 节）
- T20/T22 回测只读 DB gene_scores（不触发 em_get）+ `astock.kline`（mootdx 本地），无封号风险（B 节）
- T11 因子三层 passed/filtered 基于后端 report 实际字段，禁臆造（B 节）
- T20 回测胜率基于 DB gene_scores + K 线实际价，禁合成冒充真实（B 节）
- T7 删 `scheduler.py` 前必须 T1-T6 全验证 + T8 单测过（硬约束，同 S011 T15→T16）
- 战法匹配/回测胜率属客观历史统计特征，用户可见输出挂"历史统计特征，市场有风险"提醒

## 规模与分工建议

| 分工 | 任务 | 预估 |
|---|---|---|
| 后端-调度 | T1-T9 | 中（lifespan + WAL + seed + 删旧，改动面可控） |
| 后端-回测 | T10-T12, T20-T22 | 中-大（新建回测引擎 + 因子三层重构） |
| 前端 | T13-T19, T23-T29 | 大（Sheet + FunnelLayerCard + 战法反筛 + WinRatePanel + 布局重整 + playwright） |
| 独立 | T6, T27 | 小（删死代码 / 回链） |
