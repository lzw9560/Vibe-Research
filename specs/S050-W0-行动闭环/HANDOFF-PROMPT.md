# S050 实施交接提示词（交给新会话 Claude）

你接手 Vibe-Research 仓库（/Users/lizhiwei/project/code/stock/Vibe-Research）的 S050 spec 实施（W0 行为闭环：票根+影子对照+独立性基线）。全程用中文与用户沟通。

## 任务
实施 `specs/S050-W0-行动闭环/spec.md` 的 R1–R7。按同目录 `plan.md` 的阶段顺序（S1→S5）与 `task.md` 的原子任务 T1–T12 执行，每完成一项勾选 task.md 对应复选框。

## 开工必读
1. `specs/S050-W0-行动闭环/spec.md`——需求 R1–R7、设计取舍 §5、验收 A1–A6、明确不做 §10
2. 同目录 `plan.md`——阶段依赖与串行纪律
3. 同目录 `task.md`——原子任务清单与 commit 门
4. 根目录 `AGENTS.md`——分级工作流与提交纪律
5. `docs/workflows/short-term-win-rate-optimization-workflow.md` §10.2/§12.4——W0 的上位定义（只读背景，不扩大范围）

## 现状
- git 在 develop，HEAD=47d4d5d（spec/plan/task 已提交）
- dev server 跑在 :8900，勿杀
- 绝不触碰并行会话的未提交改动：backend/seat_profiles.json、frontend/src/pages/limitup/GeneScreener.tsx、GeneFilterForm.tsx、docs/superpowers/plans/

## 关键代码事实（已核实，不必重复排查）
- winrate_records 现 14 列无归因列；迁移目录 `backend/migrations/win_rate_tracker/`（20250613-001/002），`WinRateTracker._migrate_schema` 用 MigrationManager 注册——003 照抄注册模式
- `WinRateRecord` dataclass 13 字段（win_rate_tracker.py），add_record INSERT 手写列清单——扩列两处同步改
- 结算链路：`routers/workflow.py:565 transition_workflow_state`（模型 `_TransitionRequest`:534，现有 entry_price/exit_price/strategy 可选字段）→ settled 流转 → `settlement_recorder.record_settlement(state)`（state=workflow_state 行 dict）→ WinRateRecord 写库；价缺返 None 不写
- 快照：`routers/workflow.py:54-100` _snapshot_dir/_load_snapshot/_list_snapshot_dates（私有函数）；快照 payload 含 `final_candidates`（诊断卡 list，字段 code/name/gene_score 等）。**先抽 `backend/snapshot_store.py` 再在 settlement_recorder 引用，禁止 settlement→routers 反向 import**
- `workflow_state_repo._ensure_columns`：幂等 ALTER 模式（现有 entry_price/exit_price/strategy/settled_at）——attention_mode 照此加
- `backtest_lite._calc_next_day_return(code, date_str, kline_cache=None)`：信号日 close→次日 close，K 线缺返 None；`_next_trading_day(date_str)` 可复用；只读本地 K 线缓存零外呼
- `strategies/strategy_backtest.py` trades 带 date/code/name（S049 T14 已落），结果有 12h 缓存——结算低频，直接调用可接受
- `routers/win_rate.py`：现有 stats/adjustments/trends/sector/strategy + POST records；模块级 _tracker——shadow-comparison 端点加在此文件
- 前端：结算表单=`frontend/src/components/workflow/TransitionForm.tsx`（entry/exit 价格表单）；对照卡宿主=`frontend/src/pages/workflow/PreMarketBriefing.tsx`(385 行，现有 WinRateCompareSection:325 可参照)；hooks 在 `frontend/src/lib/api/`（useQuery 模式）
- 测试样板：`backend/tests/test_s034_settlement.py`（结算）/`test_s038_settle.py`/`test_migrate_dbs.py::_make_test_db`（造 winrate.db 测试库）；前端 `TransitionForm.test.tsx` 模式

## 硬约束
- AGENTS.md medium 流程门：develop 直提、勤 commit、最小功能提交（wip: 可）、绝不 revert 他人改动
- 合规底线：不臆造数据；缺数据诚实标记（no_suggestion_days/missing_kline/sufficient=false）；本 spec 零新外部调用（不得新增 em_get/网络请求）
- W0 语义纪律：对照卡只出客观算账，**不出方向结论词**（"感觉单胜率 X%"是事实陈述，"你应该跟系统做"是方向结论——后者禁止）；卡片挂「历史统计特征，市场有风险，研究参考」
- 私有数据：winrate.db/workflow_state/快照均 gitignored，测试一律用临时库（test fixture），绝不写用户真实库（`_get_tracker` 注入点已存在）
- 测试先行：每阶段相关测试绿后才 commit（G1–G5 门）
- 后端测试：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`
- 前端测试：`cd frontend && npx tsc --noEmit && npx vitest run`

## 范围外（spec §10，勿扩张）
- 票根人工修正端点、edge_family UI 选择、毕业判定逻辑、明日验证条件（D7d#4，归 W1）、推送通知（归 W-C 二期）

## 完成定义
- spec A1–A6 全部勾选
- 后端 pytest -m "not live" 全绿；前端 tsc + vitest 全绿
- :8900 冒烟：简报页对照卡渲染（含空态）；真实结算一笔 → winrate_records 票根列正确（signal_source/edge_family/attention_mode）
- task.md 全部 ✅，spec.md 状态改"已实现"，最终 commit `feat(S050): ...` + `docs(S050): 验收`

执行顺序 S1→S5，阶段门与风险见 plan.md。
