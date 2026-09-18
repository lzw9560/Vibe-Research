# Plan: S189 — 做 T 框架（持仓 + 盘中 T+0 磨成本）

> 关联：[[spec.md]]、[[../S188-breakout多窗口holding-return/]]（A 数据支撑）、`breakout-multiwindow-return` memory

## 技术方案

**核心数据支撑**（S188 A，966 笔）：
- breakout D+1 gross **+0.52%**（正毛）→ 扣成本 net **-1.14%**（成本 ~1.66% 吃掉正毛）
- 窗口越长越亏（D+5 net -3.18%）→ 支持短线/盘中，反对多日持有
- 做 T 逻辑：建仓后盘中 T+0 补 ~1.6% 成本 gap → 扭亏

**T+0 交易模型**（A 股 T+1 + 持仓做 T）：
- 持底仓（T-1 breakout 建仓 100 股）
- 盘中 OFI 拐点触发 T+0：买压升→买 100 股（可卖旧仓 100 锁利），买压降→卖 100 回补
- 每日限 2-3 次 T+0（防过拟合 + 控成本）
- 成本：每次 T+0 往返佣金（5 元×2 side）+ 印花（卖侧 0.1%）≈ 0.2-0.4%/次（小单）

**OFI 择时信号**：
- 历史回测：mootdx tick OFI proxy（主动买卖方向）→ 分钟级序列 → 拐点（OFI 正转负=卖点，负转正=买点）
- 实时：tencent/mootdx 五档 → compute_multi_level_ofi（变动量）→ 拐点
- 集合竞价剔除（is_auction_period）

**模拟验证**（对 966 笔 breakout）：
- 拉建仓日盘中 mootdx tick → 算 OFI proxy 分钟序列 → 模拟 T+0 → 算净收益
- 对比：纯持有 net（D+1 -1.14%）vs 做 T net（补回多少）
- §44 v2：OFI-confirmed 做 T 子集 vs 全日做 T，lift 验证（≥60 天后）

## 取舍

- **不做空**（A 股做空受限 + 成本高）——做 T 用持仓往返，合规低成本
- **不换 arm 框架**——breakout arm 加 t0_mode 开关，纯持有路径保留（不破坏现有）
- **OFI proxy 先行**（mootdx tick 已验 370 日）——真五档实时待 live 攒够 60 天
- **不接实盘**——模拟盘先验证（trade_journal + JournalRecorder 扩 T+0 fill）

## 模块拆分

1. **accounting T+0 成本**（engine/accounting.py）——`_cost_pct` 已有 round-trip，加 `t0_cost`（T+0 往返：佣金+印花，非建仓单边）
2. **JournalRecorder T+0 fill**（engine/journal_recorder.py）——`record_t0_fill`（同日买/卖 pair）+ T+0 PnL 结算
3. **OFI 分钟级拐点**（engine/intraday_ofi.py）——`compute_multi_level_ofi` 已有，加 `ofi_turn_points`（序列拐点检测）
4. **t0_simulator**（tools/t0_simulator.py，新）——对历史 trades 模拟做 T，net vs 纯持有对比
5. **forward_test arm t0_mode**（strategies/forward_test.py）——breakout arm 加 t0 开关

## 依赖序

1 → 2 → 3 → 4（模拟器依赖前三个）→ 5（forward_test 接 t0_mode）
