# Plan: S012 — 工作流标灰技术方案

> 对应 `spec.md`。细化桩→NotImplementedError、UI 标灰、pre_market 清理。

## 1. 桩→NotImplementedError

### `realtime_workflow.py`
- `monitor_stock(code)` → `raise NotImplementedError("realtime 盘中监控未实现")`
- `check_bomb_alerts` 红预警分支 → `raise NotImplementedError`
- `_signals` 保留空 list（不返 None 误导）
- `get_market_status`（按小时返字符串，非桩）**保留**

### `post_market_workflow.py`
- `_settle_recommendations` → `raise NotImplementedError`
- `_generate_llm_review` → `raise NotImplementedError`
- `_generate_next_day_strategy` → `raise NotImplementedError`
- `_calculate_win_rate`/`_optimize_strategies`（有真逻辑）保留，标 `# 依赖未实现的 settle`

### 调用方防护
`trading_workflow.run(stage)` try/except `NotImplementedError` → 返回 `{"stage": stage, "not_implemented": True}`，不崩溃。

## 2. UI 标灰

- `IntradayMonitor.tsx`/`PostMarketReview.tsx`：据 `not_implemented` 标记显示「未实现」灰徽标 + 禁用操作
- 不展示空数据当结果（`_signals` 永远空被当"无信号"，误导）
- `<WorkflowStage>`（S014）内置 `notImplemented` 渲染分支

## 3. pre_market 清理

- 删 `pre_market_workflow._build_strategy_match`（`:199-227`，`run` 未调它，内联了同样逻辑）
- 确认 `run()` 不依赖该方法

## 4. 实现步骤
1. realtime/post 桩改 NotImplementedError（保留签名）
2. trading_workflow.run 加 try/except 防护
3. 删 pre_market 死代码
4. 前端两页加「未实现」徽标
5. 单测 test_realtime_post_stubs（抛错+编排不崩）
6. 前端 vitest 快照（徽标渲染）
7. `pytest -m "not live"` + diff 审查（无新功能逻辑）

## 5. 风险点
- 桩显式化后调用方未防护会崩 → trading_workflow.run 统一 try/except
- 前端依赖空数据展示 → 改读 `not_implemented` 标记
- diff 审查须确认无新功能（A6）
