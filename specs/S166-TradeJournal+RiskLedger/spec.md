# Spec: S166 — Trade Journal + Risk Ledger（port S149，risk carve-out）

> 状态：草案（S160 component 6，priority 3，design-agnostic risk carve-out）
> 关联：S160 / grill-foundation-holes-2026-09-06（#8 风控无牙）/ S149（journal.py/excursion.py/at_risk.py feature cb54a96/f9898f9）
> 分级：medium —— issue 层单轮 review，S149 P3 已实现 port 非 新建

## 0. 问题

grill #8（stop 护不住隔夜 gap-down，s144 path_lift<1 "edge 来自风控"数学谬误 / kill_switch 只 prepend 警告不阻断 / 风控 core 依赖 OMS deferred 无牙）。风控 reframe"无 OMS 不称保护"。但 Trade Journal + Risk Ledger 是 design-agnostic（不依赖 OMS）——gap-down excursion 数据唯一来源，没它每个 stop 数字都是猜。

## 1. 目标

port S149 `journal.py`/`excursion.py`/`at_risk.py`/`risk_rules.py`/`attribution.py`/`inbox.py` 到 develop（现仅 feature cb54a96/f9898f9，develop 缺）。Trade Journal（成交时序结算）+ Risk Ledger（gap-down excursion 数据）+ Honest Risk Label（stop 对 gap-down 是仪式非保护，诚实标）。借 backtrader Analyzers 接口（开源调研采纳模式③）。

## 2. 需求清单

- **R1 Trade Journal**：port S149 `journal.py`（CRUD + fills/fee 结算 + threading.Lock 防静默丢单 + `_market_context` 零网络盖章）。
- **R2 Risk Ledger**：port S149 `excursion.py`（MFE-MAE bars 多源防封）+ `at_risk.py`（在险资金）+ `risk_rules.py`（风险宪法）+ `attribution.py`（判断执行归因）+ `inbox.py`（异常收件箱）。⛔ 不接入 AI prompt（S149 既有隔离）。
- **R3 Honest Risk Label（grill #8）**：每候选/持仓挂 `risk_status` = "stop 对 gap-down 是仪式非保护（s144 path_lift<1）" / "kill_switch 通知级非阻断" / "真实风控=仓位 sizing + gap-down 诚实标"。不宣称"core 风控保护"。
- **R4 借 backtrader Analyzers 接口**（DrawDown/TradeAnalyzer/PositionsValue）——可插拔评估器，与策略解耦。

## 3. 受影响文件

- port S149 `backend/journal.py` + `excursion.py` + `at_risk.py` + `risk_rules.py` + `attribution.py` + `inbox.py`（feature cb54a96 → develop）。
- port `routers/journal.py` + `routers/risk.py`（S149 P3 已有 7+9 端点）。
- 借 backtrader Analyzers 模式（开源调研采纳模式③，可插拔 `get_analysis()` 接口）。

## 4. 验收标准

- [ ] R1 Trade Journal port（CRUD + 结算 + 盖章，S149 既有测试 port 绿）。
- [ ] R2 Risk Ledger port（excursion + at_risk + risk_rules + attribution + inbox，不接入 AI prompt）。
- [ ] R3 Honest Risk Label（stop 对 gap-down 仪式标，不宣称保护）。
- [ ] R4 backtrader Analyzers 接口（可插拔评估器）。
- [ ] pytest 单测（S149 既有测试 port）+ 不接入 AI prompt 验证。

## 5. 合规与工程底线自查

- [x] 不臆造：journal/excursion 实算（S149 既有，port 非 新建）。
- [x] 私有数据隔离：journal 写 .vibe-research 不进 git。
- [x] §44 诚实标注：risk label 准确（stop 对 gap-down 仪式非保护，治 grill #8 "edge 来自风控"数学谬误）。
- [x] 不闭门造车：port S149 既有 + backtrader Analyzers 模式（开源）。

## 6. 分级

medium（port S149 5 模块 + routers + risk label）。issue 层单轮 review。S149 P3 已实现（cb54a96），port 非新建。design-agnostic（gap-down excursion 数据任何线路需）。
