# Changelog 2026-09-15 — 自主推进 + 自查 review log

> 用户睡了，自主推 G3+ tasks。每完成一个 task 跑 test + 自查 + 记这里。用户醒来看这个 + git diff 复核。

## 累计已完成（G1-G3 部分）

### G1 地基
- **T0** ✅ grep zt_count_250d 7 文件确认 blast radius（只 consecutive_relay C1 用 zt_count_250d≥2 门槛，其他战法/数据传递不受影响）
- **T1b** ✅ `engine/pctchg_injector.py` enrich_pctchg + 6 tests GREEN（baostock cache 无 pctChg → 从 close 算，修一字板误判可买 bug）
- **T1a** defer — refresh_kline_cache 是增量刷新不补历史 bar；T1b（从 close 算）才是历史回测 fix（已 done）。T1a 是 going-forward 维护不阻塞。
- **T2** 决策（排除 ST 股）— G5 harness 实现时接 ST 列表源（st_play_radar/em_get）
- **T3** ✅ writer 已存在（first_board_settlement.py:220 写 forward_test_records，first_board_filter cron 15:16 每日触发）→ backfill 自动积累，不须建新 cron

### G2 verifier §44v2 修正（87 tests + broad 220 passed）
- **T5** ✅ `s44_verifier/verifier.py` R8 双算（event_metrics 任何 edge_type 都算）+ R5 查 ALL 窗口（不漏隔夜 edge）+ p_bonf 不被 event 覆盖。改 5 现有 R5 test + 加 2 新 test。
- **T5b** ✅ `s44_verifier/event_drift.py` adjust_event_drift（两样本 event vs universe，减市场 drift）+ 7 tests + wired 进 verifier（is_drift_inflated 降级 non-robust 防牛市假阳性）
- **T6** ✅ `s44_verifier/family_grouping.py` effective_family_count（去重 bollinger==zscore 等价）+ split_into_subphases（K>8 拆≤8）+ FrozenK + 12 tests

### G3 战法 + 架构（部分）
- **T1** ✅ `strategies/dimension_registry.py`（5 维 + 3 战法 config）+ `dragon_score.py`（composite 0-100 非 ML）+ 14 tests GREEN
- **T3** ✅ `FirstBoardLimitupStrategy`（首板涨停新卡，C1 sector_rank≤3 + C2 zt_count_today≥2 + C3 seal_to_float_ratio≥0.005）+ 10 tests GREEN。⚠️ 涨停 pipeline 不构造 msc → 卡在涨停路径 data_unavailable（wiring 待 G5/harness）。

## 待办（自主推进顺序）

- [ ] **T4** 接力 consecutive_relay C1 改 lbc≥2 — ⚠️ 见下方 review（须先确认不回归）
- [ ] **T5** 反包 leader_drop_reversal 新卡（龙头大跌+吞没+放量，读 bars+gene.high_gene）
- [ ] **T9-T12** 多日跟踪架构（tracking_pool + indicator_snapshots + escalation_engine + early_admission，自包含无 wiring gap）
- [ ] **T7** intraday_loss_breaker + **T8** QMT 模板（G4 独立）
- [ ] **S204 T7** DIM_ARM_MAP arm-sizing + **T8** R3 enforce（G4）
- [ ] **T13** sensitivity_sweep harness（G5，依赖 G2 T5/T6 done）
- [ ] G5 regime harness + G6 sweep + G7 全量验收

## T4 review — ⚠️ 倾向 defer（避免回归）

consecutive_relay C1 现在 `gene.zt_count_250d≥2`（gene_scores 有此列，涨停路径可读，能 fire）。spec 要 C1 改 `lbc≥2`（当下连板，lbc 在涨停池 raw ths_lb_cache 不在 ctx.gene）。

问题：改 C1=lbc 后，涨停路径 ctx 无 lbc → C1 data_unavailable → consecutive_relay **永不 fire（回归**——现在能 fire 的战法变不能 fire）。wiring（lbc 进 ctx/msc）待 G5/harness。

**判断**：T4 须等 lbc wiring 才能做（否则回归）。**defer T4 到 wiring 完成后**。先做不依赖 wiring 的 task（T5 反包读 bars+gene / 架构 T9-T12 / G4 独立）。

---

## 自主推进日志（每 task 追加）

### T5 反包 leader_drop_reversal ✅（10 tests GREEN）
- 新卡 `LeaderDropReversalStrategy`（gene_based.py）：C1 龙头确认（high_gene=1 or sector_rank≤3）+ C2 T-1 大跌≥7%（close/open 复算，round 4 位避 float 噪声）+ C3 T 吞没（curr.close≥prev.open & curr.open≤prev.close）+ C4 放量≥1.2x。
- ⚠️ 同 T3 wiring gap：ctx 无 bars 字段 → 读 msc.bars，涨停路径无 msc.bars → C2/C3/C4 data_unavailable（C1 high_gene 可评）。wiring 待 G5/harness。
- edge_type=event，须 R11 event_drift（G2 T5b 已 done）修正 verdict 才可靠。
- 大跌从 close 复算不依赖 pctChg（R14 注入前可用）——双轨分离成立。
- **自查**：float 噪声致 -7% 算成 -0.06999 → 用 round(drop_pct, 4) 修。test_c2_drop_7pct_hit 等边界 case 通过。

### T9 tracking_pool_repo ✅（11 tests GREEN）
- `tracking_pool_repo.py`：candidate_tracking_pool + indicator_snapshots 两表（幂等 CREATE IF NOT EXISTS + ON CONFLICT DO NOTHING + resolve_data_dir）。mirror workflow_state_repo 模式。
- TRACKING_LABELS（admit/tracking/decayed/promoted）词表分离 workflow_state.WorkflowStatus enum（test_tracking_labels_not_in_workflow_enum 验证 R5/R6 修正）。
- **自查**：tmp DB 隔离（monkeypatch _DB_PATH + re-_ensure_tables），不污染真实 market_data.db。

### T10 early_admission ✅（10 tests GREEN）
- `early_admission.py`：pre-涨停候选识别（T-1 only pit guard，caller 传数据不取数不臆造）。high_gene=1 / lbc=1（苗子 pre-2 板）/ zt_count_today≥2 三信号入池。
- **自查**：lbc=1（非≥1）——lbc≥2 已涨停非 pre，不入 early_admission（由 consecutive_relay 等处理）。test_already_limitup_not_admitted 验证。

### T11+T12 escalation_engine ✅（10 tests GREEN）
- `escalation_engine.py`：maturity promote（tracking→watching，age≥3+gene+20%+sector_rank≤5，社区阈值标探索性）+ decay（promoted 5 日无改善 → WATCHING→FILTERED reason='decayed' 非→CANDIDATE 防振荡）+ R7 ensure_candidate 联动（pre-涨停候选不在 workflow_state）。
- 决策#11：只 candidate→watching 自动，watching 以上人工（test_no_auto_holding 验证不调 monitoring/holding）。
- T12 decay：test_decay_uses_filtered_not_candidate 验证防振荡 loop。
- **自查**：fake workflow_repo（FakeWorkflowRepo 记录调用）+ tmp DB 隔离，不碰真实 workflow_state。maturity 阈值（3/20%/5/5）标探索性须 sweep。

### T7 intraday_loss_breaker ✅（11 tests GREEN）
- `risk/intraday_loss_breaker.py`：吃大面 enforce（单笔>5% 禁加仓 / 合计>8% 禁开新仓+冷却）+ intraday_multiplier（四层乘积 final_size=arm×portfolio×lift×intraday）。
- 不依赖 baostock/S204（基于持仓浮亏）。复用 DrawdownBreaker pattern 思路（enforced/disabled）。

### T13 sensitivity_sweep ✅（8 tests GREEN）
- `tools/sensitivity_sweep.py`：sweep_param（每值跑 verify→SweepResult）+ overfit 检测（edge 仅单 v→overfit / 多邻近→稳健 / 无→no_edge）+ sweep_k_count（sweep 次数计入 Bonferroni K）+ FrozenK。
- verdict_fn callback（caller 跑 verify 传 (status,lift,n)），harness 不耦合具体战法。
- **自查**：overfit 检测逻辑——edge（robust_edge verdict）仅 1 v→overfit，≥2 v→robust，0→no_edge。

---

## ⚠️ 决策点汇总（自主推进停在此，须你定）

### 1. T4 接力 consecutive_relay C1 改 lbc — defer（wiring gap，会回归）
consecutive_relay C1 现读 `gene.zt_count_250d`（gene_scores 有，能 fire）。改 lbc（在涨停池 ths_lb_cache 不在 ctx.gene）→ 涨停路径无 lbc → C1 data_unavailable → 永不 fire（回归）。**须先 lbc wiring**（ths_lb_cache → ctx/msc.lbc）。

### 2. T7 DIM_ARM_MAP wire 进 scoring.py:85 — defer（代码自己警告不自动改）
evaluation.py:235-260 注释明确："S197 R3 两门 safeguard 落地前不自动改"——breakout 臂 min-multiplier 风险（ofi/seal_sincerity/bid_ask_pressure 任一 lift<1 days≥60→×0.1 拖垮整 breakout 臂）。wire lift_for_arm 进 scoring.py:85 else 分支会违反此警告。**须 S197 R3 两门 safeguard 先落地**（你决策）。

### 3. G5 regime harness（regime_stratified_*_lift ×4）— defer（战法 wiring gap）
首板涨停/反包/接力 战法读 msc.bars/seal_to_float_ratio/zt_count_today，但涨停 pipeline 不构造 msc（strategy_base:127 注明）→ 战法在涨停路径 data_unavailable 不命中。**须先 战法 wiring**（涨停池 raw seal + sector_cycle zt_count + baostock bars 填进 msc）。

### 4. 战法 wiring（T3 首板涨停 / T5 反包 / T4 接力 共同 blocker）—— 最大 wiring task
涨停 pipeline 当前不构造 market_scan_ctx（只有非涨停 funnel 路径构造）。要让首板涨停/反包/接力 在涨停路径真跑，得 wiring：涨停池 raw seal_to_float_ratio（limitup_screener/models.py:50）+ sector_cycle zt_count_today + baostock bars 填进 msc。**这是 pipeline 重构级 task，须你定 scope**（在涨停 pipeline 哪里构造 msc）。

---

## G7 全套件回归（后台跑，~22min）

`bjx1dxmig` background——验 G2/G3 所有改动（verifier R8双算+R5查ALL+R11drift + 战法 + 架构）没回归。完成通知。

### G7 结果 ✅ 零回归
- **6 failed, 3614 passed**（比开始 3503 多——我加的新 test 全过）。
- 6 failed **全是会话开始就有的老 bug**（s070×4 + task_executor stuck + gap_window 字符串），**与我的改动无关**。
- 我的 G2（verifier §44v2）+ G3（战法+架构）+ G4（风控+sweep）改动**零回归**。

## wiring (a) phase 1 ✅ 端到端验证

用户同意 (a) wire + (i) 分期（phase 1 seal+zt_count，phase 2 bars 待）。

- **step 1** ✅ match_strategies 加 `market_scan_ctx` 参数（向后兼容 default None）。
- **step 2** ✅ `_build_limitup_msc(gene, date)` helper（limitup_strategy.py）：从 gene_obj（seal_to_float_ratio + high_gene + industry）+ sector_cycle `_get_zt_count_by_date_industry`（按 industry 取板块涨停家数）建 msc。
- **step 3** ✅ get_strategy_signals 调 `_build_limitup_msc` + 传 match_strategies。
- **首板涨停 C1 改** ✅ 用 high_gene（ctx.gene，涨停路径有）OR sector_rank（msc，非涨停 funnel）——涨停路径 gene_obj 有 high_gene，C1 能 fire。
- **端到端验证** ✅：mock gene（high_gene=True, seal=0.006, industry）+ mock sector_cycle(zt_count=3) → _build_limitup_msc → 首板涨停 fired=True, 3/3 hit（C1 high_gene + C2 zt_count≥2 + C3 seal≥0.005）。**首板涨停 战法卡现在真能 fire**（之前 data_unavailable）。

**phase 2（待）**：+ bars（baostock K线）→ 反包 leader_drop_reversal 能 fire（C2 大跌/C3 吞没/C4 放量 须 bars）。
**T4 接力 lbc（仍 defer）**：lbc 不在 gene_obj/msc，须 ths_lb_cache wiring（phase 3?）。

## 战法注册 ✅（用户定 (a) 都注册，反包标占位）

- `strategies/impl/__init__.py`：加 `FirstBoardLimitupStrategy` + `LeaderDropReversalStrategy` export（12→14）。
- `strategies/funnel/registry.py`：STRATEGY_REGISTRY 加 2 StrategyConfig（首板涨停 + 龙头大跌反包）。
  - 首板涨停：`first_board_limitup`，entry_condition="板块共振(zt_count_today≥2)+封单≥0.5%+龙头(high_gene/sector_rank≤3)"，能 fire（wiring phase 1 done）。
  - 反包：`leader_drop_reversal`，entry_condition 标 "⚠️占位：phase 2 bars wiring 待，当前 data_unavailable 不 fire"。
- 验证：count=14，2 新战法在，无 test 断言 12 数量（不挂）。

## 剩余讨论项（实现前先定，用户要"先讨论完再一起实现"）

1. ~~战法注册~~ ✅ done
2. **T4 接力 lbc wiring** — lbc 不在 gene_obj，须 ths_lb_cache wiring（phase 3?）
3. **T7 DIM_ARM_MAP wire scoring** — 代码警告 S197 safeguard 未落地不自动改
4. **phase 2 bars**（反包）— baostock cache 高效读（module-level cache?）
5. **G5 regime harness** — regime_stratified_*_lift，scope（4 战法? 首板先?）
6. **S201b2 6 老 bug** — gap_window 字符串/S206 任务类型 trivial fix?
7. **S205 下轮** — 5 战法 per-战法维度集
8. **前端 polish** — workflow `wwqho30s9` 清单到了改

## fork agent 修 3 组老 bug ✅（agent a503bf96，7 test 绿，111 passed 零回归）

- **gap_window**：真因 `gap_window_lift.py:120` 写错 `edge_type="selection"`（应是 overnight_gap，S199+M4）→ 改对。**生产 bug 修了**（不只 test 格式）。
- **s070×5**：executor 跑 subprocess（`risk.seal_intraday_collect_cli`）但 test mock in-process → subprocess 看不到 mock → written=0。改 test 调 `run_collect`（in-process 内层函数）。
- **task_executor stuck**：stuck 时间戳固定 09-04，today=09-15 cutoff=09-08 → 09-04 被清。改 `datetime.now()` 动态。
- 改动：gap_window_lift.py（生产 edge_type 修正）+ test_s070 + test_task_executor + test_verifier_router。

## 0914 定时任务（用户问"跑了吗"）

**跑过了**——0914 多数 success，10 failed 全是 timeout 300s / reaped stale >1300s（backend 过载/慢任务，非没跑）。failed：st_play_radar / trade_journal_daily / 每日回测快照 / first_board_t1_review / daily_kg_audit（timeout）+ first_board_filter / limitup_precompute / seal_intraday_collect×2（reaped stale）+ turso_sync。用户说"没有的话执行一次"——已跑不重跑（backend 没起 + w9rkiek3c 改文件，起 backend 风险）。failed 的明天经 `POST /api/scheduled-tasks/{id}/run` trigger endpoint 重跑。

## 自主并行推进最终总结（w9rkiek3c + fork agent + route fix + 文档/图谱）

### fork agent（a503bf96）修 3 组老 bug ✅（7 test 绿，111 passed 零回归）
- gap_window：`gap_window_lift.py:120` 生产 edge_type 修正 `selection`→`overnight_gap`（S199 真因，不只 test 格式）。
- s070×5：executor 跑 subprocess 但 test mock in-process → 改 test 调 `run_collect`（in-process 内层函数）。
- task_executor stuck：stuck 时间戳固定 09-04 被 cutoff 清 → 改 `datetime.now()` 动态。

### w9rkiek3c workflow 3 agent 并行 ✅（108+44 passed 零回归）
- **agent A**：`Relay23Strategy`（gene_based.py:652，C1 lbc≥2 + C2 量比[1.5,2.5] + C3 Dragon Score 占位）+ 注册（15 项）+ wiring phase 2（`_build_limitup_msc` 加 bars baostock module-level + lbc 涨停池 raw）+ test_relay_23 + test_limitup_msc_wiring。反包+接力二三板 能 fire。
- **agent B**：G5 2 regime harness（`regime_stratified_first_board_limitup_lift.py` + `regime_stratified_reverse_package_lift.py`，MA20 3-way + wire_verdict K=12 拆 3 family 各 K=4）+ tests。
- **agent C**：前端 polish 批量（灰字透明度→去透明度 + 原生灰→主题色 + 蓝按钮→暖橙 primary，5 文件）。

### 路由恢复（用户报"短线漏斗选股不见了"）✅
- 根因：frontend-audit（69126e2）误删 `Candidates.tsx`（候选池主页：SelectionPipeline 漏斗 R1/R2 + DiagnosisCard 选股池 + ThresholdPanel 因子参数）+ `Recommendation.tsx`，当孤儿删 + redirect。
- 修：git 恢复 2 页 + router.tsx `/candidates` `/recommendation` → 指回页。tsc 过。

### 端点验证清单 ✅
`docs/verify-endpoints-2026-09-15.md`——战法信号/§44/前端页面/定时任务/架构 全端点 + 0914 failed 重跑指引。

### 知识图谱更新 ✅
Obsidian vault `strategies/` 加 3 新战法实体（[[首板涨停]] + [[龙头大跌反包]] + [[接力二三板]]）+ `index.md` MOC 12→15 + edge 家族表加涨停首板/接力二三板/龙头大跌反包。

### 测试状态（全绿零回归）
108（G1-G4）+ 44（agent A/B）+ 111（fork agent broader）全过。gap_window + s070 + task_executor 3 组老 bug 修了。

## 用户明天验证
1. 起后端 `cd backend && .venv/bin/python -m uvicorn app:app --port 8900`（**.venv/bin/python 非系统**）+ 前端 `cd frontend && npm run dev`。
2. 按 `docs/verify-endpoints-2026-09-15.md` 验证。
3. 0914 failed 10 任务经 `POST /api/scheduled-tasks/{id}/run` 重跑。
4. git diff 复核（backend 战法+架构+§44 + frontend polish+路由恢复）。

## w9rkiek3c 最终验证结果（实跑非自报）

### 后端全量 pytest -m "not live"：**3664 passed / 1 skipped / 0 failed**（exit 0，455s，coverage 62.95% 达 50% 门槛）
- **6 个 pre-existing 老 bug 全清了**（fork agent 修的 gap_window+s070+task_executor）→ backend 套件**首次全绿**！
- agent A 自报 3656，实测 3664（+8，工作树含 G2 s44_verifier 等并发改动也加了测试），关键零失败。

### 前端 vitest：64 files / 456 tests PASS（exit 0）。tsc --noEmit 干净（exit 0）。

### 焦点回归：A relay_23+limitup_msc+leader_drop+first_board+registry = 76 passed；B 2 harness+s44_wire = 54 passed。

### ⚠️ 留给你定的 2 个视觉决策点（agent C 前端 polish）

1. **[HIGH] JournalLedger "已验证/豁免" 徽章转橙**——蓝→橙后与 monitoring=橙 同屏语义碰撞（validated/exempt 跟 monitoring 都橙色，用户分不清）。回退 validated=蓝 约俗，还是接受统一橙？
2. **[MEDIUM] 4 处半转换残留**——WeatherHero/GeneResultTable/S171ValueVerdict 有 text-blue-400/300 + border-blue 残留（spec 只映射 bg-blue-500/text-blue-500/600，text-blue-400/300 不在范围）。补全转 primary 还是回退纯蓝？

### [INFO] B harness stub
- main() 是 stub（不加载真实 data），真实跑须传 returns/dates/regime_map + FROZEN_COMMIT hash（当前 'synthetic' 占位）。

### agent A 额外修了 phase 1 遗留
- 3 个 stale 计数断言（test_strategy_funnel_registry/test_s081/test_s031 的 ==12→15）+ 3 张缺失战法卡（cards/first_board_limitup.md + leader_drop_reversal.md + relay_23.md，让 test_s058 战法卡完整性恢复）。



## 盘中打磨执行 + 深度优化（下午）

### P0_FIRST 落地
- **T0 venv**: 3.14→3.11.16 重建（非 planned，是 rm 误删后恢复——numba 不支持 3.14 + 传递依赖删不掉；brew install python@3.11 + python3.11 -m venv + 91 deps；app/tests OK）。教训记 corrections + learned-rules 5 条硬门
- **T2 dual_pressure 删非修**: `_compute_dual_pressure` 三态 unavailable/no_pressure/pressure + `_is_seal_status_degraded` per stock-type；pytest 21 passed；首板涨停 经 HTTP 仍 fired
- **T3 情绪速览条**: SentimentStrip 加到 IntradayCockpit 顶部（score/zone/zt/seal/break/ad_ratio + 采样时间），空态分 error/loading/no-data
- **T4 0914 重跑**: ofi_collect + weekly_brainstorm_remind success，0 崩溃 0 stale-reap（mini_racer fix + 3.11 venv 验证有效）
- **T5 stale-reap 注释**: cron_runner.py 3 处 >800s→>1300s

### 深度优化（深度思考 + 一起优化）
- **baostock 网络**: 之前 login 坏（10002007）是临时，现已恢复 login success——T6 回补 + K 线回退能用
- **value_funnel 前向引用 bug 修**: `models.py:110` 引用 AnomalyAssessment（:128 才定义）无 `from __future__` 致 NameError，2 test collection 失败 + app import warning。加 `from __future__ import annotations` 1 行 fix，22 测试过 warning 消。**pre-existing bug 非本会话引入**
- **0 字节 orphan DB 清理**: backend/.vibe-research/ 10 个 + 项目根 2 个（intraday_accumulation + scheduled_tasks），真数据在项目根有实大小
- **RightPanel 主区显示**: 变纯图标 rail（content 移主区 ChartCenter slot）+ 日期默认今日北京时区；tsc 零错
- **tsc + full pytest**: tsc clean；full pytest collection 修了 value_funnel 后重跑（之前 2 collection error 是它）

### 自进化沉淀
- corrections.jsonl +2 条（venv rm / IntradayMonitor 早删建议），learned-rules.md +1 section（5 条硬门），项目 memory destructive-command-verify-before-rm
- IntradayMonitor 纠正：是 unrouted 孤儿但含 4 层情绪 wiring 参考，正确序 T13 迁移→T15 删，不能早删

### 待 P1 fork 完成
- K 线 fork: 修 mootdx bars 0 + 接回退 + 多时间维度切换（日/周/月/60min）
- 4-P1 fork: T7 instrumented logging / T11 worldmonitor deprecate / T12 T+1 砍 / T6 baostock 回补（baostock 现能用）
