# S049 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。

## S1 后端子项 B（情绪梯队 + market_emotion）

- [ ] T1 `candidate_funnel/models.py`：IndicatorSet 删 `seal_rate`/`bomb_rate`/`advance_rate` 三字段（B1）
  - 验证：grep 无残留引用；test_models.py 绿
- [ ] T2 `candidate_funnel/sources/board_ladder.py`：只返 `lianban_stocks`（+missing）；新增 `get_market_emotion_raw(date)` TTL 缓存包装（B3/D6 共用）
  - 验证：test_sources_live 结构断言改写后绿
- [ ] T3 `routers/workflow.py`：`_fetch_market_emotion` 重写——get_market_emotion_raw + STI engine.compute（同一份 emotion 不重复外调）+三率+ladder+涨跌停家数；失败 missing（B4）
  - 验证：新增单测绿（见 T5）
- [ ] T4 测试修复：`test_sources_live.py:34-38` 改断言只含 lianban_stocks；`test_funnel.py:28` fixture 删三键（B7）
- [ ] T5 新增 `tests/test_s049_market_emotion.py`：_fetch_market_emotion 三分支（emotion 有/空/抛错）+ STI 失败降级（B7）
- [ ] G1 commit 门：`pytest candidate_funnel/tests tests/test_s049_market_emotion.py tests/test_workflow_snapshot.py -m "not live"` 全绿

## S2 后端 D 采集层（全参数 + 去重）

- [ ] T6 `candidate_funnel/funnel.py` R1 passed：加 `consec_boards`（board.lianban_stocks 按 code 匹配）（D1）
- [ ] T7 R2 passed：加量价 `turnover_pct`/`vol_ratio`/`amount_yi`/`amplitude_pct` + 资金流 `main_net_inflow`/`main_net_5d`/`northbound`；None 记 missing 文案（D1）
- [ ] T8 R3 passed：加 `auction_open_pct` + `matched_triggers`（已有）+ `catalyst_summary`（D1）
- [ ] T9 `funnel.py`：`run_funnel` 加 `_FUNNEL_CACHE`（键=date+config 排序 JSON，TTL 300s，done 即清）（D6）
- [ ] T10 `routers/workflow.py`：live done 分支 `_cache.update(... funnel_layers=...)` + 快照存入 + status 响应透出（D5）
- [ ] T11 新增测试：passed dict 字段契约（test_funnel_passed_scores.py 扩展或新文件）+ 缓存命中不重复采集（mock fetch 计数）
- [ ] G2 commit 门：candidate_funnel 全量绿

## S3 后端 D 状态机 + 战法明细

- [ ] T12 `workflow_state_machine.py`：`WATCHING: [MONITORING, FILTERED, CANDIDATE]`（D9）
- [ ] T13 状态机测试补 watching→candidate 合法；grep 既有 watching 流转测试是否需更新
- [ ] T14 `strategies/strategy_backtest.py`：trades 补 `date`/`code`/`name`（gene.name）（D8）
- [ ] T15 `routers/strategy.py`：新增 `GET /api/strategy/backtest/trades?strategy_code=&lookback_days=60`（返 trades+available_days）（D8）
- [ ] T16 测试：trades 字段断言 + 端点 filter/未知战法空/lookback 透传
- [ ] G3 commit 门：相关测试绿

## S4 后端子项 C（诊断时点 + 快照卡）

- [ ] T17 `sources/fund_flow.py`/`activity.py`：entry 加内部键 `_as_of`=最新行日期 YYYY-MM-DD（C2）
- [ ] T18 `funnel.py::diagnose`：收集各源 `_as_of` 取 min 作 as_of；无则 now()（C1/C3）
- [ ] T19 `routers/workflow.py`：快照存 `diagnosis_cards`（final_candidates model_dump）；status 快照路径透出（C4）
- [ ] T20 测试：as_of 最早/fallback；快照 diagnosis_cards 存取（C5）
- [ ] G4 commit 门：相关测试绿

## S5 后端全量回归

- [ ] T21 `cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov` 全绿（A1 基线）

## S6 前端 B（types + 简报页）

- [ ] T22 `lib/api/types.ts`：MarketEmotion 补 sti/三率/ladder/涨跌停；FunnelLayer passed 补全参数字段；BacktestTrade 类型（B5/D1/D8）
- [ ] T23 `PreMarketBriefing.tsx` 市场情绪区重写：STI 评分+phase 中文直出+三率 chips+ladder 分布+涨跌停家数；删死 phaseLabel 映射；缺数据 "--"（B5）
- [ ] T24 因子段跳过 `factor_id==='candidate_funnel'` 卡（D3）
- [ ] T25 CandidateFunnelEmbed 数据源改读 `briefing.funnel_layers`（done/snapshot 响应携带），删额外 GET（D4）
- [ ] T26 vitest：市场情绪区渲染 ladder/三率 + candidate_funnel 卡不渲染
- [ ] G5 commit 门：tsc + vitest 绿

## S7 前端 FunnelMatrix

- [ ] T27 `components/candidate/FunnelMatrix.tsx`（新）：行=union，列=R1/R2/R3（✓分/✗/—）+全参数列（连板/量价/资金流/催化/打分），排序 R3>R2>R1 分降，前 15+展开，行点击 onPick，overflow-x-auto（D2）
- [ ] T28 状态 chips 筛选（复用 useWorkflowStates，toggle 取消，空集不筛）（D7）
- [ ] T29 PreMarketBriefing：CandidateFunnelEmbed 换用 FunnelMatrix（行点击=setDrawerCode）
- [ ] T30 FunnelMatrix.test：✓/✗/— 语义 + 排序 + chips toggle + 点击回调
- [ ] G6 commit 门：组件测试绿

## S8 前端 战法展开 + 抽屉 + 状态卡

- [ ] T31 `WinRateComparePanel.tsx`：战法行展开=当日命中（l2Passed 按 best_strategy，candidate/watching 未持仓），措辞"未持仓 · 命中战法"，onPickCandidate（D8）
- [ ] T32 展开行回溯明细懒加载（点击触发 fetchTrades，样本 N 天如实标）（D8）
- [ ] T33 `CandidateDetail.tsx`：diagnosis 调用透传 date；快照诊断卡优先；情绪梯队块只留 consec_boards；量价补 auction_open_pct（C1/C4/B6）
- [ ] T34 `WorkflowStateCard.tsx`：watching 态"取消观察"+candidate 态"取消选中"按钮（D9）
- [ ] T35 `FunnelLayerCard.tsx` 紧凑化：紧凑网格/max-w-2xl/filtered 原因截断 title（D10）
- [ ] T36 测试：展开 toggle+懒加载、状态按钮 mutate、CandidateDetail date 透传
- [ ] G7 commit 门：tsc + vitest 全绿

## S9 验收

- [ ] T37 dev server（:8900）冒烟：run 一次 → A2-A11 逐项人工过（A11 live 端到端含诊断卡）
- [ ] T38 勾选 spec A1-A12；task.md 全 ✅；最终 commit
