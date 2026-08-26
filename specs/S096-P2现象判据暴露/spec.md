# Spec: S096 — P2 现象判据暴露（P2RiskPanel 补"为何此 tier"）

> 状态：**已实现（grill Q1 完整链 + Q2 红期 override 显覆盖 + 数据降级标注, 2026-08-23 落地）**
> 作者：Claude 会话  日期：2026-08-23
> 级别：small-medium（backend 暴露既有计算中间态 + 前端展示，非新算法）
> 起因：S094 R25 "P2 仓位闸显示（P2RiskPanel，补现象判据）"——briefing 只透传 market_phase/cap/tier（结果），无判据（因子值 + 触发规则）→ 用户看不到"为何绿档/红档"。
> 依赖：S079 R6（_market_phase 4 因子扩展已落地，pre_market_workflow._compute_market_phase_factors 已算 5 因子）。
> grill 收敛：Q1=完整链（factors+fired_rule+phase→tier→cap）；Q2=红期 override 显覆盖 + 数据降级标注（两都要）。

## 0. 问题

P2RiskPanel 当前显示：
- market_phase（冰点/普通/活跃/亢奋/红期，结果）
- market_phase_cap（绿1.0/黄0.5/红0.2，结果）
- position_cap_tier（green/yellow/red，结果）

**缺失**：用户看到"绿档 cap=100%"但不知**为何**——是 zt_count=85（活跃）？还是 big_loss=10（红期硬熔断）？判据（5 因子值 + 触发规则）未暴露。

## 1. 既有计算（S079 R6 已落地，不重算）

`_market_phase`（first_board_filter.py:100）5 因子输入：
- zt_count（涨停家数）
- big_loss（大面股≥10% 家数）
- floor（跌停家数）
- ladder_success（连板晋级率）
- ladder_height（连板最高高度）

判定：
- 红期硬熔断（优先）：big_loss≥8 或 floor≥20 → "红期"
- 四档：zt_count<30→冰点 / <60→普通 / <100→活跃 / ≥100→亢奋

映射：
- PHASE_TO_CAP_TIER：活跃/亢奋→green，普通→yellow，冰点/红期→red
- MARKET_PHASE_CAP：green=1.0 / yellow=0.5 / red=0.2

`pre_market_workflow._compute_market_phase_factors(trade_date)`（:322）已算 5 因子 dict（zt_count/big_loss/floor/ladder_success/ladder_height）。
`_market_phase(factors...)` → phase。phase → tier → cap。

## 2. 目标

暴露判据到 briefing，P2RiskPanel 显示"为何此 tier"：因子值 + 触发规则（哪条 fired）+ phase→tier→cap 链。用户能看到"涨停 85 → 活跃 → 绿档 cap=1.0"或"大面 10 ≥8 → 红期硬熔断 → 红档 cap=0.2"。

## 3. 开放设计问题（grill 讨论定稿）

- **Q1 粒度**：暴露多少？(a) 仅 5 因子值（前端 infer 规则）；(b) 因子值 + 触发规则字符串（"zt_count=85→活跃" / "big_loss=10≥8→红期硬熔断"）；(c) 完整链（因子 + 规则 + phase→tier→cap）。
- **Q2 字段 shape**：单 `p2_criteria` dict（factors + rule + chain）vs 多个独立字段（p2_factors/p2_fired_rule/p2_chain）。
- **Q3 计算位置**：_compute_market_phase_factors 已算因子；判据组装放 pre_market_workflow（p2_fields 加字段）还是 P2RiskPanel 前端拼？
- **Q4 向后兼容**：additive 字段，旧快照默认 None（P2RiskPanel 已有 `if !phase && ...` 不渲染逻辑）。
- **Q5 规则暴露形式**：规则是 backend 算（返 fired_rule 字符串）还是前端硬编码阈值表（drift 风险）？倾向 backend 算（单一事实源，防 drift）。

## 4. 受影响文件（grill 定稿后填实）

- `pre_market_workflow.py`：p2_fields 加判据字段（_compute_market_phase_factors 因子 + _market_phase fired rule）。
- `routers/workflow.py`：_collect + snapshot + GET 透传判据（镜像 market_phase 透传）。
- `frontend/src/lib/api/types.ts`：PreMarketBriefing 加判据字段。
- `frontend/src/components/workflow/P2RiskPanel.tsx`：显示判据（因子值 + 触发规则）。

## 5. 验收（grill 定稿后细化）—— ✅ 全过（2026-08-23 落地）

- ✅ briefing 透传判据字段（additive，旧快照 None 不破）。
- ✅ P2RiskPanel 显示"为何此 tier"（因子 + 触发规则）。
- ✅ 红期硬熔断场景显式标注（big_loss≥8/floor≥20 fired）。
- ✅ pytest + vitest + tsc 绿。

## 6. 合规自查（弱合规）

- 工程底线：判据基于既有 _market_phase 计算（S079 R6 已落地），不臆造因子/规则；私有数据隔离（p2_fields 走 briefing，.vibe-research 不涉）；无 em_get（_compute_market_phase_factors 读 _emotion 本地）。
- 风险提醒：P2 仓位参数是参考值非执行指令（param_disclaimer 已存）。
