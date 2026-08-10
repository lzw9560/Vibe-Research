# S049 实施交接提示词（交给新会话 Claude）

你接手 Vibe-Research 仓库（/Users/lizhiwei/project/code/stock/Vibe-Research）的 S049 spec 实施。全程用中文与用户沟通。

## 任务
实施 `specs/S049-盘前简报漏斗重构与诊断修正/spec.md` 的子项 B/C/D（子项 A 已完成，commit 89768c2）。按同目录 `plan.md` 的阶段顺序与 `task.md` 的原子任务 T1–T38 执行，每完成一项勾选 task.md 对应复选框。

## 开工必读
1. `specs/S049-盘前简报漏斗重构与诊断修正/spec.md`——决策与验收 A1–A12
2. 同目录 `plan.md`——阶段依赖与风险
3. 同目录 `task.md`——原子任务清单
4. 根目录 `AGENTS.md`——分级工作流与提交纪律

## 现状
- git 在 develop，HEAD=4343796（spec/plan/task 已提交）
- dev server 跑在 :8900，勿杀
- 绝不触碰并行会话的未提交改动：backend/seat_profiles.json、frontend/src/pages/limitup/GeneScreener.tsx、GeneFilterForm.tsx、docs/superpowers/plans/

## 关键代码事实（已核实，不必重复排查）
- 状态机 backend/workflow_state_machine.py：WATCHING: [MONITORING, FILTERED]，需补 CANDIDATE；candidate→filtered 已合法；filtered→candidate 可重入
- routers/workflow.py:162 `_fetch_market_emotion` 是死的：`market.get_overview(date)` 签名不匹配 TypeError→恒 {}；get_overview() 不接收参数
- `market._emotion(date)` 可用：返 date/zt_count/dt_count/zb_count/max_boards/lianban_count/ladder/lianban_stocks/seal_rate/break_rate/promotion_rate/yzt_count；偶发返空=em_get 限流，重试一次
- STI：`limitup_sti.service.get_sti_engine()`；`engine.compute(emotion_data, sentiment_data)` 或 `precompute_daily(date)`；STIResult.score/phase（STIPhase 中文值 高潮/启动/分歧/冰点/退潮）/source_ok；情绪数据=`market._sentiment(date)`
- candidate_funnel/sources/board_ladder.py 现返 seal_rate/bomb_rate/advance_rate/lianban_stocks（市场级）；build_indicator_set 只消费 lianban_stocks（按 code 匹配 consec_boards），三率从不赋值
- candidate_funnel/funnel.py：R1/R2/R3 passed dict 现仅 {code,name,gene_score[,matched_triggers]}；diagnose() 的 as_of=now()
- strategies/strategy_backtest.py:148 trades 缺 date/code/name（gene.code/gene.name/d 均可取）；结果有 12h 缓存
- push2delay.eastmoney.com 只回 1 行 klines（子项 A 已处理：<2 行置 main_net_5d missing）
- 前端：PreMarketBriefing.tsx(292行)/FunnelLayerCard.tsx(235)/WinRateComparePanel.tsx(85)/CandidateDetail.tsx(161，diagnosis 调用不带 date)/WorkflowStateCard.tsx(142)

## 硬约束
- AGENTS.md medium 流程门：develop 直提、勤 commit、最小功能提交（wip: 可）、绝不 revert 他人改动
- 合规底线：不臆造数据；缺数据诚实标 missing（AC6）；em_get 防封；零方向结论词（战法展开措辞用"未持仓 · 命中战法"，不用"建议买入/可建仓"）
- 测试先行：每阶段相关测试绿后才 commit
- 后端测试：`cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov`
- 前端测试：`cd frontend && npx tsc --noEmit && npx vitest run`

## 完成定义
- spec A1–A12 全部勾选
- 后端 pytest -m "not live" 全绿；前端 tsc + vitest 全绿
- :8900 冒烟通过（触发 run 一次，验证市场情绪区/矩阵/战法展开/状态取消/抽屉）
- task.md 全部 ✅，最终 commit

执行顺序 S1→S9，阶段门与风险见 plan.md。
