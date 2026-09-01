# Spec: S136 — premarket 开盘后 kill_switch 实时核（market_note 承诺落地）

> 状态：已实现(2026-09-01) · 草案
> 作者：lzw9560  日期：2026-09-01
> 级别：medium（backend scheduled_tasks + 通知 content；涉交易信号风控→合规自查）
> 关联：S071（premarket_selection market_note 承诺"开盘后实时核 [kill_switch]"）/ S090（premarket §2.1 路线图已 done：接 endpoint+live kline 日更+风控+前端）/ S101（9:25/9:35 premarket 通知）/ execution_model.check_market_kill_switch（§16.4 市场熔断，上证<-3%/创业板<-4%→不开新仓）

## 1. 问题 / 目标

premarket_selection 的 `market_note`（`premarket_selection.py:220`）承诺：
> "盘前选股：market_kill_switch 需盘中指数，盘前不判（开盘后实时核）"

但 **"开盘后实时核" 未实现**：
- `check_market_kill_switch`（`execution_model.py:116`，上证跌幅>3%/创业板>4%→`triggered=True` 不开新仓）存在，仅 endpoint `/api/strategy/funnel/market-kill-switch`（`strategy.py:298`）调用。
- 9:35 `_execute_premarket_open_notify`（`scheduled_tasks.py:1055`）+ 9:25 `_execute_premarket_auction_notify`（:1027）**都不查** kill_switch——只 fetch quotes + 推送通知。

后果：市场开盘暴跌（上证<-3%/创业板<-4%）时，premarket 候选仍被推送 + 风控价（止损/止盈/仓位）照发，**无熔断 gate**。grill verdict 说"edge 主来自风控非对称"——kill_switch 是核心风控，却没 wire 进开盘后 path。这是**风控缝 + 诚实缝**（market_note 承诺的功能没建）。

目标：9:25/9:35 premarket 通知调 `check_market_kill_switch`，熔断时通知 content 前置「⚠️ 市场熔断：{reason}。不开新仓」+ 候选标"熔断抑制"。落地 market_note 的"开盘后实时核"承诺。

## 2. 背景

- `check_market_kill_switch(indices)`（`execution_model.py:116`）：indices=[{name,change_pct}]，上证<-3% 或 创业板<-4% → `MarketKillSwitch(triggered=True, reason, sh_pct, gem_pct)`；indices 空 → 不触发（不臆造）。
- 数据源：`astock.index_quote()`（`strategy.py:306` kill_switch endpoint 已用此）——9:25/9:35 盘中返实时上证/创业板指数。
- 9:25 `_execute_premarket_auction_notify`：竞价确认通知（open vs last_close gap_pct）。
- 9:35 `_execute_premarket_open_notify`：开盘 5min 表现通知（现价/涨跌幅/封板）。
- 两者都 `_load_final_cards(f_date)` → `_fetch_quotes(codes)` → `_build_*_notify_content` → `_send_notify`。无 kill_switch 调用。
- premarket §2.1 路线图（grill-reframe-final-verdict："接 endpoint+live kline 日更+风控+前端"）已 S071+S090 全 done——本 spec 是 §2.1 之外 market_note 承诺的遗留风控缝。

## 3. 需求清单

- [ ] **R1**：`_execute_premarket_open_notify`（9:35）调 `check_market_kill_switch(astock.index_quote())`；`triggered=True` 时通知 content 前置「⚠️ 市场熔断：{reason}。不开新仓」+ 每候选标"熔断抑制（不开新仓）"。
- [ ] **R2**：`_execute_premarket_auction_notify`（9:25）同理——竞价时上证/创业板已开盘价可查。
- [ ] **R3**：`check_market_kill_switch` 返 `triggered=False`（市场正常）或 indices 空（指数未取得）→ 通知不变（不臆造熔断，不加多余警告）。
- [ ] **R4**：通知返体加 `kill_switch: {triggered, reason}` 字段（可观测，飞书通知 + 返体都带）。
- [ ] **R5**：backend gate 绿（`pytest -m "not live" --deselect <newsradar> --deselect <s032>`）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | `_execute_premarket_open_notify` + `_execute_premarket_auction_notify` 加 kill_switch 检查 + content 前置警告 + 返体字段（R1/R2/R4） |
| `backend/scheduled_tasks.py` | `_build_open_notify_content` / `_build_auction_notify_content`（或其 caller）接收 kill_switch 参数，前置熔断块（R1/R2 content） |
| `backend/tests/test_s093_notification.py` 或新测 | 加 kill_switch triggered→通知含熔断警告 + 候选标抑制；indices 空→通知不变（R3） |

## 5. 设计方案

### 5.1 kill_switch 检查时机——9:25 + 9:35 两个盘中 hook

9:25 集合竞价确认时上证/创业板已有开盘价（集合竞价 9:15-9:25 产生开盘价）→ 可查。9:35 开盘 5min 后指数更稳。两者都查 = "开盘后实时核"的最小落地（scheduled hook）。**不做** continuous real-time monitor（盘后 follow-up，YAGNI——scheduled 9:25/9:35 覆盖开盘关键时点）。

### 5.2 通知 content 前置熔断块——honest 标注非屏蔽

`triggered=True` 时通知 content **前置**：
```
⚠️ 市场熔断：{reason}（上证 {sh_pct}% / 创业板 {gem_pct}%）
不开新仓。premarket 候选风控价仅供参考，熔断中不入场。
---
[原 content：候选 + 风控价]
```
**不**跳过通知（用户需知熔断 + 候选，非闷声不发）——前置警告 + 候选标"熔断抑制（不开新仓）"让用户明确 gate 状态。对齐 S126 诚实范式（标注非屏蔽）。

> **收口（2026-09-01 审查）**：R1/A1/§8 中的"每候选标'熔断抑制（不开新仓）'"判定为冗余——顶部块「不开新仓。premarket 候选风控价仅供参考，熔断中不入场」已覆盖全部候选的 gate 状态。impl 采顶部块方案（`_prepend_kill_switch_warning` 由 caller 前置，`_build_*_notify_content` 不变），不逐候选标。验收以顶部块为准（`content.startswith("⚠️ 市场熔断")` + "不开新仓"），不验 per-candidate。此为 spec 与 impl 一致性收口，非功能缺陷——安全目标已由顶部块达成。

### 5.3 indices 缺失→不触发（不臆造）

`astock.index_quote()` 盘中可能返空（tencent 不可达）→ `check_market_kill_switch([])` 返 `triggered=False, reason="指数数据未取得，不触发熔断"`。此时通知**不加**熔断警告（不臆造），但返体 `kill_switch.triggered=False, reason="指数未取得"`（诚实标 missing）。对齐 §1.2 不臆造底线。

### 5.4 不改 premarket endpoint

`/api/strategy/premarket-selection` 盘前调用时 `astock.index_quote()` 返昨日收盘（非盘中）→ kill_switch 不可靠。endpoint 的 `market_note` 已诚实说"盘前不判"——不改 endpoint，只 wire 9:25/9:35 scheduled hook（真正"开盘后"）。endpoint 盘中调用若需 kill_switch，用户查 `/api/strategy/funnel/market-kill-switch` 独立端点（已存在）。

## 6. 验收标准

- [ ] A1：9:35 open_notify，mock `check_market_kill_switch` 返 `triggered=True` → 通知 content 含「⚠️ 市场熔断」+ 候选标"熔断抑制（不开新仓）" + 返体 `kill_switch.triggered==True`。
- [ ] A2：9:25 auction_notify 同理（triggered→熔断警告）。
- [ ] A3：mock `check_market_kill_switch` 返 `triggered=False` → 通知 content 不含熔断警告（不变）+ 返体 `kill_switch.triggered==False`。
- [ ] A4：mock `astock.index_quote()` 返 [] → `check_market_kill_switch` 返 `triggered=False, reason="指数..."` → 通知不加警告 + 返体 reason 标 missing（不臆造熔断）。
- [ ] A5：backend gate 绿。

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：kill_switch 是风控 gate（"不开新仓"= 明确操作建议）。§1.1 弱合规（私人助理，可给操作建议，用户最终决策）允许。honest_label + 熔断 reason 诚实标注。**不**强制清仓（只 gate 新仓），用户保留决策权。
- [x] **判断可复现**：kill_switch 由 astock.index_quote() + 固定阈值（-3%/-4%）确定性推导，可复现。无财务计算，无需 financial_rigor。
- [x] **涨停四池/连板股榜**：N/A。
- [x] **用户私有数据隔离**：indices 是公开市场指数，无私有数据。kill_switch 状态在通知/返体，不落盘私有目录。
- [x] **东财端点走 `em_get`**：`astock.index_quote()` 走 tencent（非东财 push2），不涉 em_get。本 spec 不加东财端点。

**工程底线备注**：§1.2 三条全过。熔断不臆造（indices 空→不触发）；私有数据不涉；防封不涉（tencent index_quote 非东财）。market_note 承诺的"开盘后实时核"经本 spec 落地（诚实缝闭合）。

## 8. 测试计划

`test_s093_notification.py` 或新 `test_s136_kill_switch_gate.py`：
1. `test_open_notify_with_kill_switch_triggered`：mock check_market_kill_switch→triggered=True → 通知 content 含「市场熔断」+ 候选标抑制 + 返体 kill_switch.triggered（A1）
2. `test_auction_notify_with_kill_switch_triggered`：同理 9:25（A2）
3. `test_open_notify_market_normal_no_warning`：triggered=False → content 无熔断警告（A3）
4. `test_open_notify_indices_missing_no_false_alarm`：astock.index_quote→[] → 不触发 + reason 标 missing（A4）

mock `astock.index_quote` + `check_market_kill_switch`（不联网）。离线。

## 9. 风险与回滚

- **R-fail1（indices 盘中未就绪）**：9:25 集合竞价上证指数可能瞬时未稳定。**接受**——9:25 开盘价已产生（集合竞价 9:15-9:25），index_quote 应返；若空走 A4 不臆造路径。
- **R-fail2（通知 content 格式）**：前置熔断块需对齐飞书 markdown。**缓解**：用现有 `_build_*_notify_content` 的格式风格（--- 分隔 + ⚠️ emoji）。
- **回滚**：2 函数加 kill_switch 检查 + content 前置 + 返体字段 + 测——纯加法（triggered=False 时行为不变）。revert commit 即回滚。
