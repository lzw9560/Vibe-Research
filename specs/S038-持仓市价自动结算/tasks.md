# 任务拆分 · S038 持仓市价自动结算

> 级别：large，feature/S038-auto-settlement 分支。依赖 S037。

## 阶段 A · fetch_current_price（R1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `backend/market_price.py` 新建：`fetch_current_price(code) -> float | None` | — | `backend/market_price.py` | mock tencent_quote 返有价 -> 返 price | A1 |
| A2 | 单测：mock tencent_quote 返空/异常 -> 返 None | A1 | `backend/tests/test_s038_market_price.py` | pytest 过 | A1 |

## 阶段 B · _settle_on_transition 改写（R2/R3/R4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| B1 | transition 请求体加 `auto_fill_exit_price` 可选字段 | — | `backend/routers/workflow.py` | Pydantic body 含字段 | — |
| B2 | `_settle_on_transition`：exit_price 为空 + auto_fill=true -> 调 fetch_current_price 预填 | A1 | `backend/routers/workflow.py` | mock 拉价成功 -> exit_price = 市价 | A1 |
| B3 | exit_price 已手填 -> 不调 fetch_current_price，source = "manual" | B2 | `backend/routers/workflow.py` | mock 确认零调用 | A2 |
| B4 | 拉价失败 -> fallback S034 缺价跳过，source = null | B2 | `backend/routers/workflow.py` | mock 拉价返 None -> recorded: false | A3 |
| B5 | 结算响应含 `exit_price_source` 字段 | B2 | `backend/routers/workflow.py` | 响应 JSON 含字段 | A1,A2 |
| B6 | 单测：3 个分支全覆盖（market/manual/null） | B3,B4 | `backend/tests/test_s038_settle.py` | pytest 过 | A1-A3,A5 |
| B7 | 确认 S034 后续链路零改动（record_settlement / SettlementEngine / WinRateTracker） | — | — | grep 确认无改动 | A7 |

## 阶段 C · 前端（R5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| C1 | `WorkflowStateCard.tsx` 加"按市价自动结算" toggle | — | `frontend/.../WorkflowStateCard.tsx` | tsc 过 | A4 |
| C2 | toggle on -> transition 请求体加 `auto_fill_exit_price: true` | C1 | `frontend/.../WorkflowStateCard.tsx` | 请求体含字段 | A4 |
| C3 | 响应含 exit_price -> 预填输入框（用户可改） | C1 | `frontend/.../WorkflowStateCard.tsx` | 预填值显示 | A4 |
| C4 | 响应含 exit_price_source -> 标注"市价自动"/"手动填写" | C1 | `frontend/.../WorkflowStateCard.tsx` | 标注显示 | A4 |
| C5 | vitest：toggle + 预填 + 可覆盖 | C3 | `frontend/.../__tests__/` | vitest 过 | A4 |

## 阶段 D · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| D1 | pytest -m "not live" 全过 | B6,A2 | — | 全绿 | A5 |
| D2 | `npx tsc --noEmit` + vitest 全过 | C5 | — | 全绿 | — |
| D3 | live 冒烟：holding 股流转 settled -> winrate.db 新记录，source = "market" | B5 | — | DB 确认 | A6 |
| D4 | live 冒烟：手填 exit_price -> source = "manual" | B5 | — | DB 确认 | A6 |
| D5 | 合并到 develop：squash merge + 一 commit | D1-D4 | — | develop 干净 | — |
