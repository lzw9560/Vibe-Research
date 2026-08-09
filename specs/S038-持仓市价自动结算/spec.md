# Spec: S038 — 持仓市价自动结算（holding 流转 settled 时自动拉价填 exit_price）

> 状态：草案
> 作者：Codex  日期：2026-08-08
> 关联：`../S034-结算接线/spec.md`（transition 即结算，本 spec 补自动拉价步骤）、`../S037-gene-db-迁移/spec.md`（gene_score 回查路径依赖 #5 先落）、`backend/routers/workflow.py`（`_settle_on_transition`）、`backend/settlement_recorder.py`、`backend/astock.py`（`tencent_quote` 行情源）
>
> 级别：**large**（碰外部数据源 `tencent_quote` + 改 S034 已稳定的 transition 结算路径）

## 1. 问题 / 目标

S034 已实装 transition 即结算：用户在 workflow_state 流转 holding→settled 时，需手动填 entry_price / exit_price，`_settle_on_transition` 调 `settlement_recorder.record_settlement()` 写 winrate.db。用户痛点：每次结算都要手动查当前价再填 exit_price。

**目标**：settled 流转时自动拉 `astock.tencent_quote` 当前价，预填 exit_price（用户可覆盖）。拉价失败 fallback 到 S034 既有行为（手填则用，没填则跳过结算）。

**不做**：portfolio.json 按市价结算——portfolio 和 workflow_state 是两套独立数据系统（无代码层关联），强行按 code 关联是假关联（详见 grilling 会话 Q9 记录）。推迟到数据模型整合 spec。

## 2. 背景

- S034 `_settle_on_transition(code, date, state)`：检查 `entry_price` / `exit_price` 是否齐 → 齐 则调 `record_settlement` → 写 winrate.db + `settled_at` 幂等锚点。
- `astock.tencent_quote([code])` 返回 `dict[str, dict]`，经 `mappers.quote_from_tencent(code, raw)` 投影成 `Quote` 模型（含 `price` 字段）。`portfolio.get_portfolio()` 已在用同一行情源拉持仓浮动盈亏——行情源接通。
- 行情源特性：`tencent_quote` 是腾讯实时行情接口，盘中返回实时价，盘外返回最近收盘价。不需要 em_get（不碰东财，无封 IP 风险）。
- S034 结算链路：`transition` 端点 → `_settle_on_transition` → `record_settlement` → `SettlementEngine.settle()` → `WinRateTracker.add_record()`。本 spec 只在链路入口加一步"拉价预填"，不改后续链路。
- `gene_score` 回查路径（`load_gene_scores(date)` 读 `limitup_screener/vibe_research.db`）——S037 迁移后路径变 `.vibe-research/gene_scores.db`。**依赖 S037 先合并**。

## 3. 需求清单

- [ ] R1 新函数 `backend/market_price.py`（或 `settlement_recorder.py` 内加函数）：`fetch_current_price(code: str) -> float | None`——调 `astock.tencent_quote([code])` → `mappers.quote_from_tencent` → 返 `price`；任一异常/空返 `None`。
- [ ] R2 `routers/workflow.py` `_settle_on_transition`：settled 流转时，如果 `exit_price` 为 None → 调 `fetch_current_price(code)` 预填 → 拉到价则用市价做 exit_price 走正常结算；拉不到 → fallback S034 既有"缺价跳过"。
- [ ] R3 如果用户已手填 exit_price：不拉价，直接走 S034 正常结算（用户手填优先）。
- [ ] R4 结算响应带 `exit_price_source`：`"market"`（自动拉价）/ `"manual"`（用户手填）/ `null`（未结算）。
- [ ] R5 前端 `WorkflowStateCard`：settled 流转前，如果 exit_price 为空，显示"按市价自动结算"选项（toggle 或按钮），让用户选自动拉价或手动填。拉到价后预填 exit_price 输入框（用户可改）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/settlement_recorder.py` 或 `backend/market_price.py`（新） | R1 fetch_current_price |
| `backend/routers/workflow.py` | R2/R3/R4 _settle_on_transition 加拉价逻辑 + exit_price_source |
| `frontend/src/components/workflow/WorkflowStateCard.tsx` | R5 市价结算选项 + 预填 |

## 5. 设计方案

### D1 拉价时机：transition 端点内（非前端拉）

拉价在 `_settle_on_transition` 后端函数内做，不在前端拉——理由：
- 前端拉价需要暴露行情端点给前端或直调第三方，绕过后端（合规底线：key/限流在后端）。
- 后端拉价可以复用 `astock.tencent_quote` + `mappers.quote_from_tencent` 已有链路，不需新端点。
- 前端只需传一个 flag `auto_fill_exit_price: true` 到 transition 请求体，后端决定拉不拉。

### D2 拉价是"尽力而为"

`tencent_quote` 可能失败（网络/封/盘外空数据）。失败不阻断流转——S034 既有"缺价跳过"行为兜底。用户体验：点结算 → 后端拉价 → 拉到就结，拉不到提示"行情获取失败，请手动填写卖出价"。

### D3 用户手填优先

如果用户在流转前已填 exit_price（S033 前端表单），不拉价——手填值代表用户实际卖出价，比市价准确（用户可能盘中高位卖出，市价是收盘价）。

### D4 exit_price_source 标注

结算响应增加 `exit_price_source` 字段，让前端知道 exit_price 来源——展示时标"市价自动"或"手动填写"，透明可审计。

### D5 不做 portfolio.json 结算

portfolio.json（`{code, shares, cost}`）和 workflow_state（`{code, trade_date, entry_price, strategy, status}`）无代码层关联。按 code 关联两个独立系统是假关联——entry_price（工作流单笔）vs cost（持仓加权平均）口径不同；workflow_state 不记 shares，portfolio 支持部分平仓。需先做数据模型整合（是否给 workflow_state 加 shares、是否让 holding 流转同步写 portfolio）——另立 spec。

## 6. 验收标准

- [ ] A1 settled 流转时 exit_price 为空 → 自动拉 `tencent_quote` → 拉到价则用市价结算，响应 `exit_price_source: "market"`
- [ ] A2 exit_price 已手填 → 不拉价，直接结算，响应 `exit_price_source: "manual"`
- [ ] A3 拉价失败 → fallback S034 缺价跳过，响应 `exit_price_source: null`，`settlement.recorded: false`
- [ ] A4 前端 WorkflowStateCard 显示市价结算选项，拉到价后预填 exit_price 可覆盖
- [ ] A5 `pytest -m "not live"` 全过（mock tencent_quote）
- [ ] A6 live 冒烟：holding 股流转 settled → 自动拉价 → winrate.db 新增记录，exit_price_source = "market"
- [ ] A7 不改 S034 结算链路后续步骤（`record_settlement` / `SettlementEngine` / `WinRateTracker` 零改动）

## 7. 合规与工程底线自查

- [ ] 结算数据来自用户自填价格 + 系统自动拉取行情价 + 实际流转时间，客观记账无臆造
- [ ] 自动拉的是客观行情价（腾讯实时/收盘），不涉方向性研判
- [ ] `exit_price_source` 标注来源，透明可审计
- [ ] 胜率/收益属用户私有交易记录（winrate.db 在 `.vibe-research/`，S037 后）
- [ ] 不新增东财端点（`tencent_quote` 是腾讯源，非 em_get）
- [ ] 免责声明：结算页保留既有风险提醒

## 8. 测试计划

- **单测**：`test_s038_auto_exit_price`
  - mock `tencent_quote` 返有价 → 断言 exit_price = 市价，source = "market"
  - mock `tencent_quote` 返空/异常 → 断言 fallback 缺价跳过，source = null
  - exit_price 已填 → 断言不调 tencent_quote，source = "manual"
- **前端 vitest**：WorkflowStateCard 市价选项 + 预填 + 可覆盖
- **离线全量**：`cd backend && .venv/bin/python -m pytest -m "not live"` + `cd frontend && npx tsc --noEmit && npx vitest run`
- **live 冒烟**（手动）：holding 股流转 settled → winrate.db 新记录 → `GET /api/winrate/stats` 刷新

## 9. 风险与回滚

- 🟡 **改 S034 已稳定路径**：`_settle_on_transition` 是 S034 验收通过的代码。本 spec 在入口加拉价步骤，不改后续链路——但需确保 fallback 路径与 S034 原行为完全一致（缺价跳过）。**缓解**：拉价逻辑独立函数 `fetch_current_price`，`_settle_on_transition` 只在 exit_price is None 时调它，拉不到原路返回 S034 既有 `{"recorded": False, "reason": "..."}`。
- 🟡 **行情源依赖**：`tencent_quote` 是外部源，盘中高峰可能超时。**缓解**：设 5s 超时 + 异常返 None fallback。
- 🟡 **盘外拉到收盘价**：盘后流转 settled 拉到的是收盘价——如果用户盘中卖出但盘后才结算，exit_price 不是实际卖出价。**缓解**：用户可手填覆盖；`exit_price_source` 标 "market" 让用户知道这是自动拉的不是手填的。
- 🟢 回滚：`git revert`（feature 分支 squash 合并 develop）。
