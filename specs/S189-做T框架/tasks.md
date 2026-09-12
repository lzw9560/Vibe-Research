# Tasks: S189 — 做 T 框架

> 状态：未实现。逐项勾，每条带验收点。

## T1 · accounting T+0 成本
- [ ] T1.1 `engine/accounting.py` 加 `t0_cost(entry_price, size, date)`——T+0 往返成本（佣金 5 元×2 side + 印花 0.1% 卖侧 + 滑点），非建仓单边。返百分点。
- [ ] T1.2 单测：t0_cost 小单（100 股@50 元）≈0.4%，大单（1000 股@50 元）≈0.1%（最低佣金占比降）。

## T2 · OFI 分钟级拐点检测
- [ ] T2.1 `engine/intraday_ofi.py` 加 `ofi_turn_points(ofi_series)`——序列拐点（正转负=卖点 idx，负转正=买点 idx）。
- [ ] T2.2 单测：给定 [0.9, 0.9, -0.1, -0.5, 0.3] → 卖点 idx=2（正转负），买点 idx=4（负转正）。
- [ ] T2.3 集合竞价时段剔除（is_auction_period 已有，调用处过滤）。

## T3 · JournalRecorder T+0 fill
- [ ] T3.1 `engine/journal_recorder.py` 加 `record_t0_fill(journal_id, fill_type, price, ts)`——fill_type in/buy/sell，记同日 T+0 pair。
- [ ] T3.2 `engine/trade_journal.py` JournalRecord 加 `t0_fills_json` 字段（建仓 fill + T+0 fill list）+ 迁移加列。
- [ ] T3.3 单测：建仓 + 1 次 T+0（买 100 卖 100）→ t0_fills_json 含 2 pair，PnL 结算含 T+0 收益。

## T4 · t0_simulator 历史验证（核心）
- [ ] T4.1 `tools/t0_simulator.py` 新建——对 trade_journal breakout 966 笔，拉建仓日 mootdx tick → 算 OFI proxy 分钟序列 → ofi_turn_points → 模拟 T+0 → 算 net 收益。
- [ ] T4.2 输出对比表：纯持有 net（D+1 -1.14%）vs 做 T net（补回多少）+ per-trade diff。
- [ ] T4.3 §44 lift 框架：OFI-confirmed 做 T 子集（拐点明确日）vs 全日做 T，day_paired + permutation（≥60 天后跑，先搭框架）。

## T5 · forward_test arm t0_mode
- [ ] T5.1 `strategies/forward_test.py` breakout arm 加 `t0_mode=False` 开关（默认纯持有，True 启用 T+0 模拟）。
- [ ] T5.2 t0_mode=True 时 forward_test 跑完纯持有 picks 后，对每 pick 拉盘中 OFI 模拟 T+0，记 t0_fills。
- [ ] T5.3 验收：t0_mode=False 行为不变（纯持有，向后兼容），True 时 t0_fills_json 非空。

## 验收
- [ ] A1 t0_cost 正确（往返佣金+印花，对账不漏）
- [ ] A2 966 笔模拟做 T 输出 net vs 纯持有对比表
- [ ] A3 做 T net > 纯持有 net（补成本 gap 方向对）
- [ ] A4 §44 lift 框架搭好（≥60 天数据后跑）
- [ ] A5 pytest not live 全绿（deselect flaky 三条）
