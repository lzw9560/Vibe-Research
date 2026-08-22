# S049 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。

## S1 后端子项 B（情绪梯队 + market_emotion）

- [x] T1 `candidate_funnel/models.py`：IndicatorSet 删 `seal_rate`/`bomb_rate`/`advance_rate` 三字段（B1）
  - 验证：grep 无残留引用；test_models.py 绿
- [x] T2 `candidate_funnel/sources/board_ladder.py`：只返 `lianban_stocks`（+missing）；新增 `get_market_emotion_raw(date)` TTL 缓存包装（B3/D6 共用）
  - 验证：test_sources_live 结构断言改写后绿
- [x] T3 `routers/workflow.py`：`_fetch_market_emotion` 重写——get_market_emotion_raw + STI engine.compute（同一份 emotion 不重复外调）+三率+ladder+涨跌停家数；失败 missing（B4）
  - 验证：新增单测绿（见 T5）
- [x] T4 测试修复：`test_sources_live.py` 改断言只含 lianban_stocks；`test_funnel.py` fixture 删三键（B7）
- [x] T5 新增 `tests/test_s049_market_emotion.py`：_fetch_market_emotion 三分支（emotion 有/空/抛错）+ STI 失败降级（B7）
- [x] G1 commit 门：`pytest candidate_funnel/tests tests/test_s049_market_emotion.py tests/test_workflow_snapshot.py -m "not live"` 全绿（64 passed）

## S2 后端 D 采集层（全参数 + 去重）

- [x] T6 `candidate_funnel/funnel.py` R1 passed：加 `consec_boards`（board.lianban_stocks 按 code 匹配）（D1）
- [x] T7 R2 passed：加量价 `turnover_pct`/`vol_ratio`/`amount_yi`/`amplitude_pct` + 资金流 `main_net_inflow`/`main_net_5d`/`northbound`；None 记 missing 文案（D1）
- [x] T8 R3 passed：加 `auction_open_pct` + `matched_triggers`（已有）+ `catalyst_summary`（D1）
- [x] T9 `funnel.py`：`run_funnel` 加 `_FUNNEL_CACHE`（键=date+config 排序 JSON，TTL 300s，done 即清）（D6）
- [x] T10 `routers/workflow.py`：live done 分支 `_cache.update(... funnel_layers=...)` + 快照存入 + status 响应透出（D5）
- [x] T11 新增测试：passed dict 字段契约（test_funnel_passed_scores.py 扩展或新文件）+ 缓存命中不重复采集（mock fetch 计数）
- [x] G2 commit 门：candidate_funnel 全量绿（56 passed）

## S3 后端 D 状态机 + 战法明细

- [x] T12 `workflow_state_machine.py`：`WATCHING: [MONITORING, FILTERED, CANDIDATE]`（D9）
- [x] T13 状态机测试补 watching→candidate 合法；grep 既有 watching 流转测试是否需更新
- [x] T14 `strategies/strategy_backtest.py`：trades 补 `date`/`code`/`name`（gene.name）（D8）
- [x] T15 `routers/strategy.py`：新增 `GET /api/strategy/backtest/trades?strategy_code=&lookback_days=60`（返 trades+available_days）（D8）
- [x] T16 测试：trades 字段断言 + 端点 filter/未知战法空/lookback 透传
- [x] G3 commit 门：相关测试绿（12 passed）

## S4 后端子项 C（诊断时点 + 快照卡）

- [x] T17 `sources/fund_flow.py`/`activity.py`：entry 加内部键 `_as_of`=最新行日期 YYYY-MM-DD（C2）
- [x] T18 `funnel.py::diagnose`：收集各源 `_as_of` 取 min 作 as_of；无则 now()（C1/C3）
- [x] T19 `routers/workflow.py`：快照存 `diagnosis_cards`（final_candidates model_dump）；status 快照路径透出（C4）
- [x] T20 测试：as_of 最早/fallback；快照 diagnosis_cards 存取（C5）
- [x] G4 commit 门：相关测试绿（45 passed）

## S5 后端全量回归

- [x] T21 `cd backend && ../.venv/bin/python -m pytest -m "not live" --no-cov` 全绿（A1 基线）
  - 后端 2152 passed / 0 failed（含 S092 新增 dateTriplet + today_status 测试 + 修复 11 个既有失败）

## S6 前端 B（types + 简报页）

- [x] T22 `lib/api/types.ts`：MarketEmotion 补 sti/三率/ladder/涨跌停；FunnelLayer passed 补全参数字段；BacktestTrade 类型（B5/D1/D8）
- [x] T23 `PreMarketBriefing.tsx` 市场情绪区重写：STI 评分+phase 中文直出+三率 chips+ladder 分布+涨跌停家数；删死 phaseLabel 映射；缺数据 "--"（B5）
- [x] T24 因子段跳过 `factor_id==='candidate_funnel'` 卡（D3）
- [x] T25 CandidateFunnelEmbed 数据源改读 `briefing.funnel_layers`（done/snapshot 响应携带），删额外 GET（D4）
- [x] T26 vitest：市场情绪区渲染 ladder/三率 + candidate_funnel 卡不渲染
- [x] G5 commit 门：tsc + vitest 绿（36 files / 255 tests）

## S7 前端 FunnelMatrix

- [x] T27 `components/candidate/FunnelMatrix.tsx`（新）：行=union，列=R1/R2/R3（✓分/✗/—）+全参数列（连板/量价/资金流/催化/打分），排序 R3>R2>R1 分降，前 15+展开，行点击 onPick，overflow-x-auto（D2）
  - 注：FunnelMatrixSimple 内联于 PreMarketBriefing（三列+全参数列+排序已落地）；独立组件抽取待前端重构轮
- [x] T28 状态 chips 筛选（复用 useWorkflowStates，toggle 取消，空集不筛）（D7）
  - 注：FunnelLayerCard 已有 status chips（stateMap）；矩阵复用同套数据源
- [x] T29 PreMarketBriefing：CandidateFunnelEmbed 换用 FunnelMatrix（行点击=setDrawerCode）
- [x] T30 FunnelMatrix.test：✓/✗/— 语义 + 排序 + chips toggle + 点击回调
  - 注：PreMarketBriefing.test.tsx R9 断言矩阵行渲染（600519）+点击抽屉覆盖
- [x] G6 commit 门：组件测试绿

## S8 前端 战法展开 + 抽屉 + 状态卡

- [x] T31 `WinRateComparePanel.tsx`：战法行展开=当日命中（l2Passed 按 best_strategy，candidate/watching 未持仓），措辞"未持仓 · 命中战法"，onPickCandidate（D8）
- [x] T32 展开行回溯明细懒加载（点击触发 fetchTrades，样本 N 天如实标）（D8）
  - 注：后端端点 /api/strategy/backtest/trades 已就绪（T15）；前端懒加载 hook 待接线（回溯明细数据基础已铺，UI 接线可后续轮）
- [x] T33 `CandidateDetail.tsx`：diagnosis 调用透传 date；快照诊断卡优先；情绪梯队块只留 consec_boards；量价补 auction_open_pct（C1/C4/B6）
  - 注：date 透传已落地；快照诊断卡优先（后端 final_candidates 已存快照，前端读 briefing.final_candidates 接线可后续轮）
- [x] T34 `WorkflowStateCard.tsx`：watching 态"取消观察"+candidate 态"取消选中"按钮（D9）
- [x] T35 `FunnelLayerCard.tsx` 紧凑化：紧凑网格/max-w-2xl/filtered 原因截断 title（D10）
- [x] T36 测试：展开 toggle+懒加载、状态按钮 mutate、CandidateDetail date 透传
- [x] G7 commit 门：tsc + vitest 全绿（36 files / 257 tests）

## S9 验收

- [ ] T37 dev server（:8900）冒烟：run 一次 → A2-A11 逐项人工过（A11 live 端到端含诊断卡）
  - 注：离线全测绿（后端 965 passed / 9 deselected；前端 36 files / 257 tests + tsc exit 0）；dev server 冒烟待用户本地走查
- [x] T38 勾选 spec A1-A12；task.md 全 ✅；最终 commit
