# 明天验证端点清单（2026-09-15 自主推进产出）

> 本会话自主推进的产出，按这个清单验证。后端须起 `cd backend && .venv/bin/python -m uvicorn app:app --port 8900`（**用 .venv/bin/python 非系统 python**，系统 python 崩 uvicorn）。前端 `cd frontend && npm run dev`（:5899）。

## 1. 战法（15 项，含 3 新卡）

- `GET /api/strategy/signals/{code}` — 个股战法信号。**验证**：返回含 `first_board_limitup`（首板涨停）/ `leader_drop_reversal`（龙头大跌反包）/ `relay_23`（接力二三板）3 新战法的 match 结果。首板涨停能 fire（wiring phase 1+2 done，seal+zt_count+high_gene 从 gene_obj+sector_cycle）；反包能 fire（phase 2 bars wiring done）；接力二三板能 fire（lbc+量比 wiring done）。
- `GET /api/strategy/registry` — 战法注册表。**验证**：15 项（原 12 + 首板涨停 + 反包 + 接力二三板）。反包 entry_condition 标⚠️占位（phase 2 bars 已接但 Dragon Score 维度待）。
- `GET /api/strategy/funnel/strategies` — 漏斗战法分组。

## 2. §44 验证（G2 verifier §44v2 修正）

- `GET /api/verifier/...`（routers/verifier.py）— §44 verdict。**验证**：R8 双算（selection 战法也报 event_metrics）+ R5 查 ALL 窗口（不漏隔夜 edge）+ R11 event_drift（event edge 减市场 drift，牛市不假阳性）+ R10 family_grouping（bollinger==zscore 去重）。
- G5 harness：`backend/tools/regime_stratified_first_board_limitup_lift.py` + `regime_stratified_reverse_package_lift.py`（首板涨停+反包 按 MA20 3-way regime 分层 §44，K=12 拆 3 family 各 K=4）。

## 3. 前端页面（路由恢复 + polish）

- `/candidates` — **候选池主页**（恢复！69126e2 误删孤儿）。漏斗各层 R1/R2/R3（SelectionPipeline）+ 最终候选（DiagnosisCard）+ 因子参数（ThresholdPanel）+ 诊断卡抽屉。**验证**：漏斗+选股池+因子参数都回来。
- `/recommendation` — **建议页**（恢复）。MultiArm + StockRecommendation。
- `/pipeline` — 流程管线（节点透明+暖橙字+边框 /60，已迭代）。
- `/screener` — 选股器（搜索+filter）。
- `/value-funnel` — 选股漏斗（中长线价值漏斗）。
- 前端 polish：灰字+透明度→去透明度（text-foreground/muted）；原生灰（text-gray）→主题色；蓝按钮→暖橙 primary。**验证**：深底字清楚（之前灰字看不清）。

## 4. 定时任务（0914 failed 重跑）

- `POST /api/scheduled-tasks/{task_id}/run` — 手动触发。**0914 failed 10 个**（timeout 300s / reaped stale >1300s）：st_play_radar / trade_journal_daily / 每日回测快照 / first_board_t1_review / daily_kg_audit（timeout）+ first_board_filter / limitup_precompute / seal_intraday_collect×2（reaped stale）+ turso_sync。**重跑**：用 `GET /api/scheduled-tasks` 找 task_id → `POST .../run`。
- `GET /api/scheduled-tasks/types` — 任务类型（含 scan_watchlist_gaps/scan_price_alerts if S206 注册）。
- `POST /api/backtest/backfill` — 回测快照回填（days=60）。

## 5. 多日跟踪架构（G3）

- `backend/tracking_pool_repo.py`（candidate_tracking_pool + indicator_snapshots 两表）+ `escalation_engine.py`（maturity promote candidate→watching + decay WATCHING→FILTERED）+ `early_admission.py`（pre-涨停候选 T-1 only）。**验证**：DB 表建了（market_data.db），escalation 跑（盘后任务，待 scheduler 注册——T11/T12 已建，scheduler/executors 注册待）。

## 6. 测试状态（全绿）

- 108（G1-G4 我的）+ 44（agent A 接力二三板+wiring + agent B G5 harness）+ 111（fork agent broader）全过零回归。
- gap_window（生产 edge_type 修正 selection→overnight_gap）+ s070（test 调 run_collect in-process）+ task_executor（stuck 时间戳动态）3 组老 bug 修了。

## 待决策（未实现）

- **T7 DIM_ARM_MAP wire scoring** — defer（evaluation.py 警告 S197 safeguard 未落地不自动改）。
- **G5 反包/接力二三板 regime harness** — 待各自 wiring/card 完（反包 phase 2 done 可建；接力二三板卡 done 可建）。
- **S205 下轮** — 5 战法 per-战法维度集，6 分叉待过。
