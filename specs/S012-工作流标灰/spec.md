# Spec: S012 — 工作流标灰（realtime/post_market 桩 + pre_market 清理）

> 状态：草案
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 6 步）、`../S011`（状态机接线在本 spec 之前）、`../../ARCHITECTURE.md`（打板工作流）

---

## 1. 问题 / 目标

`realtime_workflow.py`(139) 几乎全 TODO 桩：`monitor_stock` return None、红预警 TODO、`_signals` 永远空。`post_market_workflow.py`(122) 核心方法全 TODO：`_settle_recommendations` 返 `[]`、`_generate_llm_review` 返"待实现"、`_generate_next_day_strategy` 同。这些未实现的桩却被 UI 当成品呈现，误导用户。`pre_market_workflow.py` 有 `_build_strategy_match` 死代码（`run` 未调它，内联了同样逻辑）。

**目标**：明确"已实现/未实现"边界——realtime/post 桩改 `raise NotImplementedError` + UI 标灰徽标「未实现」；pre_market 删死代码。**本次不补功能**（补实现涉买卖时机，需独立 spec + 合规审查）。

## 2. 背景

- 打板工作流七态状态机（pending→...→settled，旁路 filtered）；`trading_workflow.py` 按时段分发 pre/intraday/post。
- S011 接线状态机落库；本 spec 维持 realtime/post 桩，但显式标注未实现。
- 用户决策（2026-07-29）：工作流桩标灰不补。

## 3. 需求清单

- [ ] R1 `realtime_workflow.py` 的 TODO 桩方法改 `raise NotImplementedError("realtime 盘中信号未实现，见 S0xx")`，保留方法签名
- [ ] R2 `post_market_workflow.py` 同上（`_settle_recommendations`/`_generate_llm_review`/`_generate_next_day_strategy` 标 `NotImplementedError`）
- [ ] R3 `pre_market_workflow.py` 删 `_build_strategy_match` 死代码
- [ ] R4 UI 标灰：前端 workflow 页对应未实现阶段显示「未实现」徽标 + 禁用操作，不展示空数据当结果
- [ ] R5 `realtime_workflow.get_market_status`（仅按小时返字符串，非桩）保留
- [ ] R6 不补任何新功能；盘中信号/盘后结算/LLM 复盘留独立 spec（涉合规审查）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/realtime_workflow.py` | ✏️桩→NotImplementedError |
| `backend/post_market_workflow.py` | ✏️桩→NotImplementedError |
| `backend/pre_market_workflow.py` | 🩹删 `_build_strategy_match` 死代码 |
| `frontend/src/pages/workflow/IntradayMonitor.tsx` | ✏️未实现阶段标灰徽标 |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | ✏️同上 |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | ✏️适配死代码删除后的接口 |

## 5. 设计方案

- **明确边界**：桩方法保留签名（状态机/编排不破坏）但抛 `NotImplementedError`，调用方 try/except 捕获后返回「未实现」状态而非空结果。前端据状态显示灰徽标。
- **不补功能**：补盘中信号/盘后结算/LLM 复盘涉买卖时机研判，按新合规边界需独立 spec + 合规自查 + 免责声明，不在本 spec。
- **取舍**：宁可显式标灰，不伪装实现。对齐用户决策"标灰不补"。

## 6. 验收标准

- [ ] A1 realtime/post 桩方法抛 `NotImplementedError`，签名保留
- [ ] A2 前端 workflow 页未实现阶段显示「未实现」灰徽标，不展示空数据当结果
- [ ] A3 `pre_market_workflow` 无 `_build_strategy_match` 死代码
- [ ] A4 `trading_workflow.run("intraday"/"post_market")` 不崩溃，返回带 `not_implemented` 标记的结构
- [ ] A5 `pytest -m "not live"` 全过
- [ ] A6 不新增任何功能逻辑（diff 审查无新实现）

## 7. 合规自查（按新 CLAUDE.md §1）

- [ ] 桩不输出任何方向性判断或买卖时机
- [ ] 「未实现」徽标客观，不误导
- [ ] 不涉及研究性判断输出（桩无输出）

## 8. 测试计划

- 单测：test_realtime_post_stubs（确认抛 NotImplementedError + 编排不崩）
- 前端：workflow 页未实现徽标渲染（vitest 快照）
- `pytest -m "not live"` 全量

## 9. 风险与回滚

- 🟢 低风险：桩显式化 + 删死代码，不改业务逻辑
- 🟡 前端依赖空数据的展示需适配「未实现」状态
- 🟢 回滚：git revert
