# S072 · 涨停叉 pipeline 诚实可观测层

> 状态：规范先行（2026-08-17）。S071 之后的涨停叉"做透"（用户选 A）。
> 分级：medium（改 weights + 前端诚实层 + forward 基线标注，免 feature 分支，走 issue 层 review）。
> 前提：candidates/funnel pipeline 基建已完整（FunnelLayer + FunnelLayerCard），本 spec 非新建 pipeline，是给已存在的 pipeline 补诚实层 + 修 weights drift。

## 1. 问题

- **pipeline 已在**：`candidates/funnel` 的 R1→R2→R3 漏斗，FunnelLayer 字段（input_count/output_count/filtered_out/conditions/data_status）齐全且真填；前端 `FunnelLayerCard` 已渲染每步输入→输出计数、被过滤原因、通过候选得分排序。**不是从零建。**
- **缺 §44 诚实标注**：用户看 pipeline 不知道——
  - screener `total_score` §44 证伪（within-day r≈0，Phase 0b 二轮）；
  - `strategy_weights.json` limitup 主因子 `rebound_rate 0.5783` 用的是被 spec §4.1 二轮证伪的 pooled-r（within-day r=-0.010，日级市场变量），spec 已写"~~升主因子~~（收回）"但 weights 没改；
  - forward_test verdict lift 0.98<1（劣于随机）。
- 修 weights drift + 加诚实层 = 让涨停叉选股**诚实可观测**（信号无 edge 前置可见），而非把无 edge 流程漂亮化。

## 2. 目标

涨停叉 pipeline 诚实可观测：信号无 edge 前置可见 + weights 回诚实等权 + 每步执行已展示（确认）。

## 3. 需求

- **R1（weights drift 修复）**：`.vibe-research/strategy_weights.json` 的 `limitup` 权重集 → `equal_weight_pending`：rebound/seal/red 三因子各 0.3333，method/note 标"§4.1 二轮证伪后等权诚实起点，rebound pooled-r 已收回"。forward_test 历史基线标注（2026-08-17 前 records=伪信号权重期，后=等权期）。
- **R2（§44 诚实层）**：candidates/funnel 页（`/candidates`）顶部加诚实横幅——展示 forward_test verdict（lift/winrate vs random，来自 `/api/strategy/funnel/forward-test`）+ screener total_score §44 证伪 + 策略分等权 placeholder。诚实标注"无 validated edge，前向测试期间不投真金"。
- **R3（每步执行确认）**：FunnelLayerCard 已渲染 input/output/filtered_out/conditions（S031 实现）——验收确认已满足，不重建。
- **R4（S071 暂留标注）**：诚实层标注 S071 breakout 孤立（universe=1121 涨停史股非当日、定位撕裂待决 A/B/C、未并入涨停叉 pipeline）。
- **R5**：不投真金。

## 4. 受影响文件

- `.vibe-research/strategy_weights.json`（limitup → equal_weight_pending）
- `backend/strategies/strategy_funnel_registry.py`（确认 `compute_strategy_score` 等权兜底兼容 equal_weight_pending method）
- `backend/strategies/forward_test.py`（基线标注，weight 期切换字段）
- `frontend/src/components/candidate/FunnelLayers.tsx`（顶部 §44 诚实横幅）
- `frontend/src/lib/query/strategy.ts`（forward-test verdict 查询，若未接则接）

## 5. 验收标准

- [ ] weights.json limitup: `method=equal_weight_pending`，三因子各 0.3333，note 标证伪收回
- [ ] `compute_strategy_score` 等权跑通（score_candidates 单测 / pytest not live）
- [ ] candidates 页顶部 §44 诚实层展示 forward verdict（lift 0.98<1）+ total_score 证伪 + 等权 placeholder
- [ ] FunnelLayerCard 每步 input/output/filtered_out 渲染（已有，验收确认）
- [ ] 诚实层标注 S071 孤立 + 定位撕裂待决
- [ ] forward_test 基线标注（伪信号期 vs 等权期，可区分）
- [ ] `pytest -m "not live"` 过 + tsc 0 错

## 6. 合规自查（弱合规）

- 工程底线·可复现：weights 等权可复算 ✓（rebound 0.578 不可复现为"validated"，等权诚实）
- 工程底线·私有数据隔离：weights.json 在 `.vibe-research/`，不进 git ✓
- honest 标注：§44 无 edge 前置 ✓
- 不投真金 ✓
