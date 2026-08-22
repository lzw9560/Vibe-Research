# S094 原子任务清单（task）

> 状态图例：`[ ]` 待做 / `[x]` 完成。每任务=最小可验证改动；按 stage 分组，stage 末 commit。
> 测试基线：`cd backend && .venv/bin/python -m pytest -m "not live" --no-cov`（2215 passed 起点，1 pre-existing S066 归档债）。
> 前端测试：`cd frontend && npx tsc --noEmit && npx vitest run`（428 passed 起点）。
> feature 分支：`feature/S094-战法分类与双pipeline重构`（off develop）。

## S1 后端战法分类 + score_candidates 分流 + confidence

- [ ] T1 `strategies/strategy_funnel_registry.py`：战法按 funnel_type 归组（7 limitup + 5 market_scan），加 `STRATEGIES_BY_FUNNEL_TYPE` 常量
  - 验证：python `-c "from strategies.strategy_funnel_registry import STRATEGIES_BY_FUNNEL_TYPE; print({k: [s.code for s in v] for k,v in STRATEGIES_BY_FUNNEL_TYPE.items()})"`
- [ ] T2 `score_candidates` 加 `funnel_type` 参数（默认 None=全跑向后兼容）+ 按 funnel_type 筛战法
  - 验证：score_candidates(candidates, funnel_type="limitup") 只跑 7 涨停战法
- [ ] T3 `confidence` 派生（=strategy_score/100 normalize，clamp 0-1）+ signal_strength=int(confidence*100)，score_candidates 补填
  - 验证：scored_candidates confidence 非 None / signal_strength 非 0
- [ ] T4 dragon_head 不对涨停股跑（funnel_type 分流自动验证——涨停股 candidates 跑 limitup，dragon_head 不在 limitup 组）
  - 验证：pytest tests/test_s094_strategy_classify.py
- [ ] G1 commit 门：战法分类 + 分流 + confidence 测试绿

## S2 后端双 pipeline + 板块轮动修复 + zt_real 口径

- [ ] T5 新建 `market_scan.py`：通用因子层（relative_strength/ma_bullish/volume_signal/sector_strength 全市场算一次，kline cache + sector 数据）
- [ ] T6 `market_scan.py`：K线形态子（kline cache + 形态识别：low_absorption 均线回调 / reverse_package 反包 / platform_breakout 突破平台 / pattern_reversal 突破昨日最高）
- [ ] T7 `market_scan.py`：板块领涨子（sector/industry 板块内相对强度排名，dragon_head 数据源）
- [ ] T8 `sector_divergence.py`：`calculate_sector_rotation` 数据源修复（查失败根因 L205/L227，修数据源不再返 None）
  - 验证：`/api/sector/rotation?date=2026-08-21` 不再返 {data:{}}
- [ ] T9 `market.py`：`zt_count` 改 `zt_real`（L224 `len(zt)`→`zt_real`，L53 已算）
  - 验证：market._emotion('2026-08-21').zt_count == zt_real（57 左右，非 54/79）
- [ ] T10 `routers/workflow.py`：双 pipeline 响应（涨停 candidates + 非涨停 candidates 分区透传）
- [ ] G2 commit 门：双 pipeline + 板块轮动 + zt_real 测试绿
- 验证：pytest tests/test_s094_market_scan.py tests/test_s094_sector_rotation.py

## S3 前端 UI 双 pipeline 上下分区 + 折叠 + 卡片流转（依赖 S2）

- [ ] T11 `Workflow.tsx`：前瞻双 pipeline 上下分区（涨停 pipeline 上主展开 / 非涨停 pipeline 下折叠）+ CollapsibleFold 折叠收缩
- [ ] T12 `StrategyMatchMatrix.tsx`：涨停战法（7）/ 非涨停战法（5）分区展示
- [ ] T13 卡片按 pipeline 流转顺序（①涨停池②涨停战法③breakout④交叉验证 / ⑤板块领涨⑥K线形态⑦非涨停战法）
  - 验证：vitest 前瞻双 pipeline 渲染 + 折叠
- [ ] G3 commit 门：前端双 pipeline 测试绿

## S4 前端 UI bug 修（与 S3 可并行）

- [ ] T14 `SectorCyclePanel.tsx`：股票代码 2 次修（查重复渲染根因）
- [ ] T15 advisory 摘要组件：摘要截断（不显示全部，top-N）
- [ ] T16 `P2RiskPanel.tsx`：P2 仓位闸显示问题修
- [ ] T17 `VerificationCardBlock.tsx`：验证卡对 spec 设计（查差异根因）
  - 验证：vitest UI bug 修
- [ ] G4 commit 门：UI bug 修测试绿

## S5 全量回归 + playwright 验收

- [ ] T18 `pytest -m "not live"` 全量绿（2215+ 新增）
- [ ] T19 `vitest run` + `tsc --noEmit` + `vite build` 全绿
- [ ] T20 playwright e2e AC1-AC9（新建 e2e/s094-*.spec.ts）
- [ ] T21 spec.md/task.md 勾选验收 + 归档 + MILESTONES 更新
- [ ] G5 验收门：AC1-AC9 全过

## 依赖图

```
S1(T1→T2→T3→T4) ──→ S2(T5→T6→T7→T8→T9→T10) ──┬──→ S3(T11→T12→T13) ──┐
                                              │                     ├──→ S5(T18→T19→T20→T21)
                                              └──→ S4(T14→T15→T16→T17)─┘
```

并行策略：S1 → S2 → S3+S4 并行 → S5。
