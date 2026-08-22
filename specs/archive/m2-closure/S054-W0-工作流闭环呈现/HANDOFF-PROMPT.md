# S054 实施交接提示词（交给新会话 Claude）

你接手 Vibe-Research 仓库（/Users/lizhiwei/project/code/stock/Vibe-Research）的 S054 spec 实施（W0 工作流闭环呈现：盘后三问去桩 + 简报行为卡恢复）。全程用中文与用户沟通。

## 任务
实施 `specs/S054-W0-工作流闭环呈现/spec.md` 的 R1–R7。按同目录 `plan.md` 的阶段顺序（S1→S5）与 `task.md` 的原子任务 T1–T7 执行，每完成一项勾选 task.md 对应复选框。

## 开工必读
1. `specs/S054-W0-工作流闭环呈现/spec.md`——裁决记录 §2、需求 R1–R7、设计取舍 §5、验收 A1–A6、明确不做 §10
2. 同目录 `plan.md`——阶段依赖与回滚预案；`task.md`——原子任务与 commit 门
3. 根目录 `AGENTS.md`——分级工作流与提交纪律（medium：develop 直提、勤 commit、绝不 revert 他人改动）
4. `docs/workflows/short-term-win-rate-optimization-workflow.md` §2/§12.2/§12.4——每日循环与复盘三问的上位定义（只读背景，不扩大范围）
5. `specs/S050-W0-行动闭环/spec.md` §3/§5——数据层既有实现与票根优先级口径（本 spec 复用，不改语义）

## 现状
- git 在 develop（HEAD 附近为 9aaa2a5，以实际为准）；dev server 跑在 :8900（uvicorn --reload + vite），勿杀
- 绝不触碰并行会话的文件：`backend/seat_profiles.json`（已改动）、`docs/superpowers/plans/`（未跟踪）、`frontend/src/pages/BehaviorLoop.tsx` 及其测试（7ccc5d2/3e39858/470638e 三个 commit 的产物一律不动不 revert）

## 关键代码事实（已核实，不必重复排查）
- 影子对照：`backend/routers/win_rate.py::_shadow_comparison_impl(window_days, tracker)`（约 :140），含 `_bucket` 辅助；follow=signal_source ∈ (funnel_candidate, strategy_hit)、feeling=feeling、missed=快照 final_candidates − 当日持仓，收益用 `_calc_next_day_return`；模块级 `_tracker` 注入。daily-review 端点加在同一文件，复用这些私有函数
- 票根关联：S050 R2 逻辑在 `backend/settlement_recorder.py::record_settlement` 内（按 (code, trade_date) 查快照 final_candidates → funnel_candidate；未命中查战法回测 trades → strategy_hit；皆无 → feeling）。R2 抽取时保持优先级与语义不变，结算路径改为调用纯函数；既有三分支单测（S050 A2）是回归门
- 快照读取：`backend/snapshot_store.py`（S050 已抽），禁止直接 import `routers/workflow.py` 私有函数；快照 payload 的 `final_candidates` 字段含 code/name/gene_score 等
- 次日收益：`backend/backtest_lite.py::_calc_next_day_return(code, date_str, kline_cache=None)`——信号日 close→次日 close，K 线缺返 None；`_next_trading_day(date_str)` 可复用；只读本地 K 线缓存零外呼
- 盘后复盘桩：`frontend/src/pages/workflow/PostMarketReview.tsx` 现用 `WorkflowStage` 的 `notImplemented` 桩（S036）；S036 注释提到 hook 桩在 `lib/query/limitup.ts`（usePostMarketReview），新实现不必复用该桩 hook，直接写 useDailyReview
- 简报页：`frontend/src/pages/workflow/PreMarketBriefing.tsx`（S049 重构版：市场情绪区+漏斗区）；ShadowComparisonSection 已被 3e39858 移出——R4 是**新写**行为干预卡加回该页，不要恢复旧组件旧位置，数据直接调 `GET /api/winrate/shadow-comparison?window_days=28`（既有端点，useShadowComparison hook 在 `frontend/src/lib/api/`，S050 已建）
- 结算动线：状态机流转 settled 走 `TransitionForm.tsx`（含 attention_mode A/B/C 选择，S050/D8d）；「去结算」按钮携 code 跳转既有入口即可，不新建批量结算
- 测试样板：后端 `backend/tests/test_s034_settlement.py`、`test_migrate_dbs.py::_make_test_db`；前端 vitest 参照 `BehaviorLoop.test.tsx`（同目录 __tests__ 或同级 *.test.tsx 模式，随现有布局）
- 基线：后端 `pytest -m "not live" --no-cov` 983 passed / 9 deselected；前端 `npx tsc --noEmit && npx vitest run` 36 files / 257 tests。全测不得低于该基线

## 硬约束
- AGENTS.md medium 流程门：develop 直提、最小功能提交（wip: 可）、勤 commit、绝不 revert 他人改动
- 合规底线：不臆造数据；缺数据诚实标记（no_snapshot / missing_kline / 空态文案）；本 spec 零新外部调用（不得新增 em_get/网络请求）
- 口径纪律：三问页与简报卡只出客观算账+教学点，**不出方向建议词**（方向建议单一出处＝BehaviorLoop 行为研判区）；n<5 明示「样本不足，参考价值低」；两页挂「历史统计特征，市场有风险，研究参考」
- 私有数据：winrate.db/workflow_state/快照均 gitignored，测试一律临时库 fixture，绝不写用户真实库
- 导航/路由零改动；不新开页面
- 测试先行：每阶段相关测试绿后才 commit（G1–G5 门见 task.md）
- 后端测试：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`
- 前端测试：`cd frontend && npx tsc --noEmit && npx vitest run`

## 范围外（spec §10，勿扩张）
- 时刻表页/当前环节高亮（W-C）、批量结算、票根修正端点、教学点开关、周末 tear sheet（W5/N5）、BehaviorLoop 页任何改动

## 完成定义
- spec A1–A6 全部勾选（含闭环对照表逐行达标）
- 后端/前端全测绿且不低于基线
- :8900 冒烟：盘后页三问（含空态与昨日漏的结算条）+「去结算」跳转正确 + 简报行为卡渲染（含 caveat/风险注记/深看链接）；用户走查通过
- task.md 全部 ✅，spec.md 状态改"已实现"，最终 commit `feat(S054): ...` + `docs(S054): 验收`

执行顺序 S1→S5，阶段门与回滚见 plan.md。
