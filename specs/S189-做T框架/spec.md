# Spec: S189 — 做 T 框架（持仓 + 盘中 T+0 磨成本）

> 状态：草案
> 作者：Claude  日期：2026-09-12
> 关联：[[../S187-历史因子baostock回溯/spec.md]]（breakout 0 picks 调查）、[[../S188-breakout多窗口holding-return/spec.md]]、P1-3、做 T 框架（用户 2026-09-12 提出）

## 1. 问题 / 目标

breakout 多窗口 holding-return 实测（S188 A，966 笔）：D+1 gross **+0.52%** 但扣成本 net **-1.14%**，窗口越长越亏（D+5 net -3.18%）。**核心矛盾**：breakout 选股次日毛收益正，但纯持有扣成本亏——成本 ~1.66% 把正毛吃成负。

用户决策（2026-09-12）：**不做空**（A 股做空受限+成本高），改**做 T**——breakout 建仓后，盘中用 OFI 做 T+0 磨出额外收益补成本 gap，扭亏为盈。

**目标**：设计"breakout 选股建仓 + OFI 盘中择时 T+0 执行"框架，模拟盘先验证能否补回 1.6% 成本 gap + 出 net 正。

## 2. 背景

- **A 股 T+1 + 持仓做 T**：净新买 T+1 锁；但持底仓后可当日卖旧仓买新仓（T+0 往返），磨盘中波动降成本。
- **breakout 选股**：高波动股天然做 T 空间大（S188 实测 gross 正证明选股不亏方向）。
- **OFI 做盘中择时**：主动买卖方向（mootdx 历史分笔 [[mootdx-tick-ofi-proxy-2026-09-12]]）或实时五档（tencent/mootdx/stoke）告知盘口买卖压转折点。
- **alpha 来源**：做 T 磨损（盘中波动捕获），非方向性选股预测——绕开"选股死/edge 在盘中"矛盾。
- **数据支撑**：S188 A（gross+net-扣成本），OFI proxy（[[mootdx-tick-ofi-proxy-2026-09-12]]），trade_journal 1092 trades（breakout 1040 + floor 52）。

## 3. 需求清单

- [ ] R1：T+0 交易模型——持仓 + 当日买卖往返，accounting 扩展支持 T+0 成本计算（往返佣金+印花，非建仓单边）。
- [ ] R2：OFI 盘中择时信号——用 OFI proxy（主动买卖方向转折）或实时五档（买压升→加仓/卖持仓，买压降→卖/回补）触发 T+0 买卖点。
- [ ] R3：做 T 执行器——JournalRecorder 扩展记录 T+0 fills（同日买/卖 pair），区分"建仓 fill"vs"T+0 fill"。
- [ ] R4：模拟盘验证——对 S188 的 966 笔 breakout trades，模拟"建仓后盘中按 OFI 做 T"，算 net 收益 vs 纯持有 net，验证补回成本 gap。
- [ ] R5：§44 lift——OFI-confirmed 做 T 子集 vs 纯持有子集，day_paired 胜率对比 + permutation（§44 v2，≥60 天后）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/accounting.py` | 扩展 T+0 成本（往返佣金+印花，非单边建仓）——`_cost_pct` 已有 round-trip，T+0 复用但区分 pair 逻辑 |
| `backend/engine/trade_journal.py` | JournalRecord 加 `fills` 字段支持 T+0 pair（建仓 fill + T+0 fill list）——fills_json 已有结构，扩展 |
| `backend/engine/journal_recorder.py` | `record_t0_fill`（T+0 买卖 pair 记录）+ T+0 PnL 结算 |
| `backend/engine/intraday_ofi.py` | 复用 `compute_multi_level_ofi` + mootdx tick OFI proxy 做 T+0 触发信号 |
| `backend/tools/t0_simulator.py` | **新增**——对历史 trades 模拟做 T，算 net vs 纯持有 |
| `backend/strategies/forward_test.py` | arm 加 t0 模式（breakout arm T+0 enabled） |

## 5. 设计方案

**T+0 交易模型**（R1）：
- 持底仓（T-1 breakout 建仓 1 手 = 100 股）
- 盘中触发 T+0：OFI 买压升 → 买 100 股（当日可卖旧仓 100 股锁定利润），OFI 买压降 → 卖 100 股回补
- 每日最多 N 次 T+0（限 2-3 次防过拟合 + 控成本）
- 成本：每次 T+0 往返佣金（5 元×2 side）+ 印花（卖侧 0.1%），约 0.2-0.4%/次（小单）

**OFI 择时**（R2）：
- 历史回测：mootdx tick OFI proxy（主动买卖方向）→ 分钟级 OFI 序列 → 转折点（OFI 从正转负 = 卖点，负转正 = 买点）
- 实时：tencent/mootdx/stoke 五档 → `compute_multi_level_ofi`（变动量）→ 转折点
- 集合竞价剔除（`is_auction_period`）

**模拟验证**（R4-R5）：
- 对 966 笔 breakout：拉建仓日盘中 mootdx tick → 算 OFI proxy 序列 → 模拟 T+0 → 算净收益
- 对比：纯持有 net（S188 D+1 -1.14%）vs 做 T net（T+0 补回多少）
- §44 v2：OFI-confirmed 做 T 子集（OFI 信号明确日）vs 全日做 T，lift 验证（≥60 天后）

**为何不做空**：A 股做空受限（融券难+成本高+标的小），反信号做空实操差。做 T 用持仓+盘中往返，合规+低成本+高可操作。

## 6. 验收标准

- [ ] A1：T+0 accounting 正确（往返佣金+印花，对账不漏）。
- [ ] A2：对 966 笔 breakout 模拟做 T，输出 net vs 纯持有 net 对比表。
- [ ] A3：做 T net > 纯持有 net（验证补回成本 gap 的方向对）。
- [ ] A4：§44 lift 脚本（OFI-confirmed 子集）框架搭好（≥60 天数据后跑）。
- [ ] A5：`pytest -m "not live" --deselect`（flaky 三条）全绿。

## 7. 合规与工程底线自查

- [x] 研判属系统能力，做 T 是模拟盘执行非代客决策（用户定盘）。
- [x] 判断可复现：mootdx tick + OFI proxy 规则可重算，禁臆造。
- [x] 成本诚实：T+0 往返成本全计（佣金+印花+滑点），不美化。
- [x] 私有数据未进 git（trade_journal.db 在 resolve_data_dir）。
- [x] mootdx/tencent 不走东财 em_get，无防封顾虑。

## 8. 测试计划

- 单元：T+0 accounting 成本计算（往返 vs 单边）。
- 集成：t0_simulator 对单笔 breakout trade 跑通（建仓→盘中 T+0→结算）。
- §44：OFI-confirmed vs 全日做 T lift（≥60 天后）。
- 离线：`pytest -m "not live" --deselect <flaky>`。

## 9. 风险与回滚

- mootdx tick 历史分笔回补慢（4300 笔/股/日 × 966 股 × 多日）→ 限 5-10 股 × 69 日优先（够验证）。
- OFI proxy 精度低（主动方向 ≠ 挂单深度）→ 做为 proxy 验证方向，真五档实时（stoke/mootdx 五档）做实盘。
- 做 T 过拟合 → 限每日 T+0 次数 + §44 permutation 验证。
- 回滚：T+0 是新 arm 模式不破坏现有 breakout arm（纯持有路径保留）。
