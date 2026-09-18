# Spec: S166 — Trade Journal + Risk Ledger（resurrect S149 + re-wire，risk carve-out）

> 状态：草案（S160 component 6，priority 3，design-agnostic risk carve-out）
> 关联：S160 / grill-foundation-holes-2026-09-06（#8 风控无牙）/ S149 P3（cb54a96 添加 → f9898f9 删除，develop 自身历史）
> 分级：medium —— issue 层单轮 review；**非 feature→develop port，是从 develop 自身 git 历史复活 + 重新接线**

## 0. 问题

grill #8（stop 护不住隔夜 gap-down，s144 path_lift<1 "edge 来自风控"数学谬误 / kill_switch 只 prepend 警告不阻断 / 风控 core 依赖 OMS deferred 无牙）。风控 reframe"无 OMS 不称保护"。但 Trade Journal + Risk Ledger 是 design-agnostic（不依赖 OMS）——gap-down excursion 数据唯一来源，没它每个 stop 数字都是猜。

**git 力学校正**：原 framing"port S149 自 feature 分支"是事实错误。cb54a96（添加 journal/excursion/at_risk/risk_rules/attribution/inbox + routers/journal.py）与 f9898f9（**删除**同一批文件）**都是 develop 自身历史**上的 commit（`git merge-base --is-ancestor` 两者均 exit 0，均 develop 祖先）。文件在 HEAD 缺失不是因为"在 feature 分支没合并"，而是 f9898f9 故意移除（commit message"移除旧 journal_risk 家族"）。故本 spec 是 **从 git 历史复活（resurrect）+ 重新接线（re-wire）**，非 port。复活取法：`git show cb54a96:backend/<file> > <file>`（工作树 + develop HEAD 均无此批文件）。

**为何 f9898f9 删除——未定，spec 不假设"port 非新建"**。cb54a96（19:02 添加）→ f9898f9（23:37 同日删除）间隔 4h。f9898f9 message"移除旧 journal_risk 家族"暗示主动废弃（"旧"），但同一 message 末句"本提交仅捕获 worktree 工作树状态"又否认意图（worktree 快照事故）。grep develop HEAD 核实"语义是否被 vibe-astock 模块吸收"：`gap.?down|excursion|MFE|MAE` 及 `at_risk/risk_rules/attribution/inbox/journal` import 均无命中——**未被吸收**（排除"吸收"选项）。故 WHY 实际悬于 (a) 主动废弃为过时 / (c) worktree 快照事故 之间，未定。若为 (a)，按 §6 design-agnostic **新建**可能比复活旧独立文件更干净（复活前须先核 cb54a96 版本是否仍适配 develop 当前结构）。

## 1. 目标

**resurrect + re-wire**（非 port 非 新建）：从 cb54a96 历史复活 S149 `journal.py`/`excursion.py`/`at_risk.py`/`risk_rules.py`/`attribution.py`/`inbox.py`（6 模块）+ `routers/journal.py`（16 端点：7 /api/journal/* + 9 /api/risk/*），并回滚 f9898f9 在 8+ 消费方文件的拆线（re-wire）。Trade Journal（成交时序结算）+ Risk Ledger（gap-down excursion 数据）+ Honest Risk Label（stop 对 gap-down 是仪式非保护，诚实标）。

> **复活前先决**（§0 未定 WHY）：先 `git log/show` 核 cb54a96 + f9898f9 + grep develop 当前结构，判断删除是 (a) 主动废弃 → 评估新建 vs 复活 / (c) worktree 快照事故 → 直接复活。不假设"port 非新建"。

## 2. 需求清单

- **R1 Trade Journal**：resurrect cb54a96 `journal.py`（CRUD + fills/fee 结算 + threading.Lock 防静默丢单 + `_market_context` 零网络盖章）。
- **R2 Risk Ledger**：resurrect cb54a96 `excursion.py`（MFE-MAE bars 多源防封）+ `at_risk.py`（在险资金）+ `risk_rules.py`（风险宪法）+ `attribution.py`（判断执行归因）+ `inbox.py`（异常收件箱）。⛔ 不接入 AI prompt（S149 既有隔离）。
- **R3 Honest Risk Label（grill #8）**：每候选/持仓挂 `risk_status` = "stop 对 gap-down 是仪式非保护（s144 path_lift<1）" / "kill_switch 通知级非阻断" / "真实风控=仓位 sizing + gap-down 诚实标"。不宣称"core 风控保护"。R3 直接消费 `excursion.for_trade()` / `at_risk.report()`（plain functions），无需可插拔接口。
- ~~**R4 借 backtrader Analyzers 接口**~~（DrawDown/TradeAnalyzer/PositionsValue）—— **YAGNI 删除**：无消费方、`vendor/` 无 backtrader、DrawDown 可从 return series 直接算、TradeAnalyzer 即 journal 本身、PositionsValue 需 live positions（deferred）。保持 excursion.py/at_risk.py 为 plain functions，R3 直接调用。

## 3. 受影响文件

**复活（从 cb54a96 历史提取，工作树 + develop HEAD 均无）**：
- `backend/journal.py` + `excursion.py` + `at_risk.py` + `risk_rules.py` + `attribution.py` + `inbox.py`（6 模块）—— `git show cb54a96:backend/<file> > <file>`
- `backend/routers/journal.py`（16 端点：7 /api/journal/* + 9 /api/risk/{report,at-risk,excursion,attribution,inbox,rules,equity-base}）—— 同法提取
- 4 测试文件复活：`backend/tests/test_journal.py` + `test_journal_privacy.py` + `test_journal_risk.py` + `test_journal_router.py`（从 cb54a96 历史）

**回滚 f9898f9 拆线（re-wire，8+ 消费方）**：
- `backend/app.py`：重加 `from routers import journal as journal_router` + `app.include_router(journal_router.router)`
- `backend/daily_review.py`：重加 `money_effect_median` 字段 + `_market_context` 盖章字段；**用 ROOT import `from limitup_sti import STIEngine`** 非 `from backend.limitup_sti`（S149 backend-not-a-package 教训——后者生产 ModuleNotFoundError 被 except 吞 → sti_phase 恒 None → 盖章坏）
- `backend/chat.py`、`backend/routers/candidates.py`、`backend/routers/review.py`、`backend/routers/topology.py`：回滚 f9898f9 拆线（注：candidates/topology/review 的 `last_trading_date_str` 修复部分已被后续 commit 595fcf0/607bb17 重做，须 diff HEAD 核实哪些仍未接线、勿重复改）
- 前端 `frontend/src/components/layout/navigation.ts` + `frontend/src/router.tsx`：重加 Journal 页路由/导航

~~**port `routers/risk.py`**~~ —— **移除**：`routers/risk.py` 在 develop HEAD **已存在**（9357B/245 行，S055/S126 市场级风险仪表盘，6 端点 /api/risk/{dashboard,oneday/list,seats,stock/{code},bomb-alerts,seal-snapshots}）。`git show cb54a96 --stat` 确认未触及 routers/risk.py。S149 的 9 个 /api/risk/* 端点全在 `routers/journal.py`（复活该文件即得），与 HEAD 的 routers/risk.py 路径不重叠（不同子路径），两者共存、**勿覆盖** routers/risk.py。

## 4. 验收标准

- [ ] R1 Trade Journal resurrect（CRUD + 结算 + 盖章）。
- [ ] R2 Risk Ledger resurrect（excursion + at_risk + risk_rules + attribution + inbox，不接入 AI prompt）。
- [ ] R3 Honest Risk Label（stop 对 gap-down 仪式标，不宣称保护；直接消费 excursion/at_risk plain functions）。
- ~~[ ] R4 backtrader Analyzers 接口~~ —— **YAGNI 删除**。
- [ ] pytest 单测（4 复活测试文件）**对 re-wire 后的 develop 环境实跑绿**——非"port 绿"假设（test_journal_router.py 在 app.py 未重接时会失败）。
- [ ] 不接入 AI prompt 验证。

## 5. 合规与工程底线自查

- [ ] 不臆造：resurrect from cb54a96 history，re-wire 后**重验绿**（非"port 非新建"假设；test_journal_router.py 无 app.py 重接必失败）。
- [x] 私有数据隔离：journal 写 .vibe-research 不进 git。
- [x] §44 诚实标注：risk label 准确（stop 对 gap-down 仪式非保护，治 grill #8 "edge 来自风控"数学谬误）。
- [x] 不闭门造车：resurrect S149 既有实现（cb54a96），不发明新轮子；先核 cb54a96 版本是否仍适配 develop 当前结构。

## 6. 分级

medium（resurrect S149 6 模块 + routers/journal.py + 4 测试文件 + 回滚 8+ 消费方拆线 + risk label）。issue 层单轮 review。**非 port 非 新建**——从 develop 自身 git 历史复活 + re-wire（cb54a96 添加 → f9898f9 删除，均 develop 祖先）。design-agnostic（gap-down excursion 数据任何线路需）。复活前先决：核 cb54a96 版本是否仍适配当前结构、判断 f9898f9 删除 WHY（§0 未定）。
