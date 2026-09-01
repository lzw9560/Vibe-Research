# Spec: S135 — 延时数据（is_delayed）前端诚实消费

> 状态：已实现(2026-09-01) · 草案
> 作者：lzw9560  日期：2026-09-01
> 级别：medium（跨层：backend 模型+mapper + frontend 类型+渲染；涉数据输出→合规自查）
> 关联：S112 R7（gstock 产 is_delayed，push2delay 镜像标 True）/ S126（前端渲染诚实 data_status 范式）/ S134（新浪 breaker data_status 诚实缝，同 last-mile 模式）

## 1. 问题 / 目标

gstock 已产 `is_delayed`（S112 R7，`gstock.py:100/128/153`——push2delay 延时镜像 ~15min 标 True，push2 实时标 False），但**两处断**导致用户看延时数据当实时：

1. `/api/global/stock`（`market.py:106`）经 `response_model=_GlobalStockResponse`（`data: GlobalStock`，`quote: Quote`）——mapper `quote_from_gstock_us_hk`（`mappers.py:124`）**不读** `inner["is_delayed"]`，`Quote` 模型**不声明**该字段 → pydantic 剥离，前端拿不到。
2. `/api/global/indices`（`market.py:97`）无 response_model，raw dict 透传**已带** is_delayed——但前端零消费（`grep is_delayed frontend/src/` 0 命中）。

目标：is_delayed 从 gstock 透传到前端渲染，延时数据显式标"延时"（不撒谎把 push2delay 当 push2 实时）。这是 S112 R7 诚实意图的 last-mile 落地。

## 2. 背景

- gstock `_push2_stock_get`（`gstock.py:52-75`）注入 `_is_delayed`（host 名含 "delay" → True）；`_quote_from`（:99-100）透传为 `is_delayed`；`global_indices`（:127-128）+ `_fetch_sox_datacenter`（SOX 走 datacenter 日频，显式 False）都带 is_delayed。
- mapper `quote_from_gstock_us_hk`（`mappers.py:124`）读 `inner=raw["quote"]` 映射 price/change_pct 等，**漏** is_delayed。
- `Quote` 模型（`models/quote.py:27`）无 is_delayed 字段——A股 quote（tencent 实时）语义上 is_delayed=False（默认）。
- 前端 `lib/api/types.ts:14 interface Quote` + `:183 GlobalStock` + global index 类型（:167 区）均无 is_delayed。
- 前端渲染点：`DailyReview/index.tsx:82 <GlobalMarket globalIdx>`（全球指数卡）+ `StockData.tsx:243-256`（美港股视图，`gstock.quote.price/change_pct`）。

## 3. 需求清单

- [ ] **R1**：`models/quote.py` `Quote` 加 `is_delayed: bool = False`（默认 False——A股 tencent 实时，非延时）。
- [ ] **R2**：`data/mappers.py` `quote_from_gstock_us_hk` 读 `is_delayed=bool(inner.get("is_delayed", False))` 传入 Quote。A股 mapper（`quote_from_tencent` 等）不动（默认 False）。
- [ ] **R3**：`frontend/src/lib/api/types.ts` 三处加 `is_delayed?: boolean`：`interface Quote`（:14）、`GlobalStock.quote` 子类型（:183 区）、global index item 类型（:167 区）。
- [ ] **R4**：前端渲染延时标记：
  - `DailyReview`（`GlobalMarket` 组件）：globalIdx 项 is_delayed → 该指数卡显"延时"徽标（轻量 inline，不破坏布局）。
  - `StockData.tsx`：美港股视图 `gstock.quote.is_delayed` → 现价行附近显"延时"徽标。
- [ ] **R5**：backend gate 绿（`pytest -m "not live" --deselect <newsradar> --deselect <s032>`）+ frontend `tsc --noEmit` 0 + `vitest run` 绿。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/models/quote.py` | Quote 加 `is_delayed: bool = False`（R1） |
| `backend/data/mappers.py` | `quote_from_gstock_us_hk` 加 is_delayed 映射（R2） |
| `frontend/src/lib/api/types.ts` | Quote + GlobalStock.quote + global index 类型加 `is_delayed?: boolean`（R3） |
| `frontend/src/pages/DailyReview.tsx` 或 `DailyReview/` | `GlobalMarket` 渲染延时徽标（R4） |
| `frontend/src/pages/StockData.tsx` | 美港股视图延时徽标（R4） |

## 5. 设计方案

### 5.1 徽标呈现——轻量 inline 标记

延时徽标 = 小号灰字「延时」紧贴价格/名称，不抢主信息视觉。**不**用红色/警告色（延时非错误，是数据源态）。**不**隐藏价格（延时仍有参考价值，仅标注来源态）。对齐 S126 `data_status` 渲染范式：诚实标注而非屏蔽。

### 5.2 默认 False 的语义

A股 quote（tencent/astock 实时）is_delayed 默认 False——诚实（实时即 False）。韩股 quote（gstock 美港股路径，push2delay 降级时 True）。SOX 走 datacenter 日频显式 False（非延时镜像，是日频报告——语义不同，但 is_delayed=False 一致）。前端 `is_delayed?` 可选字段，undefined/False 都按非延时渲染（向后兼容）。

### 5.3 不碰 /api/global/indices 后端

indices 端点已 raw 透传 is_delayed（无 response_model）——后端不改，前端直接消费 `globalIdx[i].is_delayed`。

## 6. 验收标准

- [ ] A1：`GET /api/global/stock?symbol=AAPL` 响应 `data.quote.is_delayed` 字段存在（bool）。
- [ ] A2：gstock 走 push2delay 降级时（mock `_is_delayed=True`）→ `data.quote.is_delayed===true`；push2 实时 → `false`。
- [ ] A3：`GET /api/global/indices` 响应每项含 `is_delayed`（已存在，回归不破）。
- [ ] A4：前端 DailyReview 全球指数卡：某指数 is_delayed → 显「延时」徽标；StockData 美港股视图同理。
- [ ] A5：A股 quote（/api/quote）is_delayed 默认 false（不误标实时为延时）。
- [ ] A6：backend gate 绿 + frontend tsc 0 + vitest 绿。

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：N/A（纯数据呈现标记，无研判输出）。
- [x] **判断可复现**：is_delayed 由 gstock host 名确定性推导（"delay" in host），可复现。无财务计算，无需 financial_rigor。延时如实标，非臆造。
- [x] **涨停四池/连板股榜**：N/A。
- [x] **用户私有数据隔离**：gstock 是公开美港股行情，无私有数据。is_delayed 标记在响应体，不落盘私有目录。
- [x] **东财端点走 `em_get`**：gstock._push2_stock_get 已走 `astock.em_get`（限流+熔断，S134 sina breaker 不涉——gstock 是东财 push2 非 Sina）。本 spec 不加东财端点，仅透传既有 is_delayed 字段。

**工程底线备注**：§1.2 三条全过。延时数据显式标"延时"= 不臆造（不把延时当实时）；私有数据不涉；防封不涉（gstock 已走 em_get）。S112 R7 的诚实意图（"让前端可见这是延时数据，不撒谎"）经本 spec last-mile 落地。

## 8. 测试计划

- backend：现有 `test_s008_*` / `test_data_honesty` 锁住 gstock is_delayed 产出的测试应不破（mapper 加字段是加法）。加 1 测：`quote_from_gstock_us_hk` raw inner.is_delayed=True → Quote.is_delayed==True（A2）。
- frontend：tsc 0（类型加可选字段不破）+ vitest（现有 DailyReview/StockData 测不破）。可视情况加 1 测：GlobalMarket 收 is_delayed 项 → 渲染延时徽标（若组件有测）。
- 离线：无网络（gstock 测都 mock em_get）。

## 9. 风险与回滚

- **R-fail1（Quote 加字段破消费者）**：is_delayed 默认 False，加法不破既有消费者（A股 quote 多个 is_delayed=false，无害）。**接受**。
- **R-fail2（前端类型可选 `?`）**：`is_delayed?: boolean` 向后兼容（undefined 按非延时渲染）。**接受**。
- **回滚**：纯加法（1 backend 字段 + 1 mapper 行 + 3 frontend 类型行 + 2 渲染徽标）——revert commit 即回滚，无数据迁移。
