# Spec: S162 — 反前视回测引擎三层（Decision+Accounting design-agnostic / Executor pluggable fill）

> 状态：草案 v2（S160 component 2，priority 2）
> 关联：S160 / S161 v2 / open-source-quant-framework-research-2026-09-06 / grill-foundation-holes-2026-09-06
> 分级：medium（三层引擎 + A 股规则）—— feature 分支 + grill（反前视架构级变更）+ 分步实施
> v2 修订：spec-grill 修 Trades.entry_price vs Executor 谁覆盖（两分支都破）/ simulate_holding "复用"实为"拆分重构" / day_paired+walk-forward+Bonferroni+IC 误归 Accounting（应归 verifier） / PIT FeatureStore=被砍 lake 无消费者 defer / parquet/duckdb 未装 / qlib 签名未核实。

## 0. 问题

grill #2 证"design-agnostic 回测引擎不可能"——entry/fill 绑方向。世纪大辩论化解：engine 三层解耦 Decision+Accounting design-agnostic / Executor 可插拔 fill（deferred），非 no-fill 降级。**spec-grill 抓 v2 bug**：①Trades 带 entry_price + Executor 算 entry，没说谁覆盖→两分支都破（Executor 覆盖则 gap 被 T+1OpenFill 重算丢 overnight=§44v1 错窗口复现；Executor 用 entry_price 则无架构约束=策略层自律，正是 R2 声称"不是"）；②simulate_holding（kline_returns.py:84-119）是 fill+accounting 一体函数（line 101 算 entry=fill/Executor + lines 104-119 stop/take/path+return=accounting），spec 说"复用"实为"拆分重构"；③day_paired/walk-forward/Bonferroni/IC 误归 Accounting（应归 S161 verifier；IC 是 cross-sectional scalar ≠ return series，喂 verify() 是 category error）；④PIT FeatureStore=被砍的 lake 换名，NOW 无消费者（Trades 自带 signal_date，Accounting 读 pre-loaded bars list 如 simulate_holding's bars arg）→ defer；⑤generate_trade_decision qlib Nested Decision Point 签名未核实（vendor/qlib 不存在，靠 WebSearch 二手比对，S153 v1 臆造引用教训）。

## 1. 目标

建反前视回测引擎三层——Decision（Trades 生成，NOW input）+ Accounting（path return/cost/survivorship，design-agnostic，喂 S161 verifier）+ Executor（可插拔 fill，T+1OpenFill 默认，IntradayConditionalFill deferred stub 返 untradeable）。借 qlib Nested Decision Point + backtrader 0/-1 索引+cheat_on_open（开源调研采纳模式①）治 §44v1 错窗口根因（entry 时点可捕获性架构级强约束非策略层自律）。

## 2. 需求清单

- **R1 三层解耦**：
  - **Decision 层（R1a NOW + R1b deferred 待 qlib 源码核实）**：
    - R1a（NOW 可实现）：Decision 层**取 Trades 作 input**（手动喂，如 gap run 直接构造）。`Trades` dataclass = {code, signal_date, fill_type, entry_price: Optional (Executor 填，Decision 不带), direction, size, exit_date: Optional, exit_price: Optional}。**v2 修**：移除 entry_price/exit_price 自 Trades INPUT（batch path），改带 signal_date + fill_type；Executor FillPolicy 是 entry_price **唯一源**（治 grill #6 两分支都破——Executor 覆盖丢 gap / Executor 用则无约束）。
    - R1b（deferred + 待核实）：`generate_trade_decision(signal, execute_result=None) → Trades` 签名标 **"待 gh-proxy clone qlib/backtest/executor.py 核实后确定"**——qlib Nested Decision Point 模式靠 WebSearch 中文二手交叉比对，vendor/qlib 不存在（S153 v1 臆造引用教训，不可凭未核实签名定接口契约）。§3 decision.py 起初只含 Trades dataclass + generate_trade_decision stub/TODO。
  - **Accounting 层（design-agnostic，v2 修边界）**：`path_return(filled_Trades, bars, stop/take/max_hold_params) → return`。**只算**：path return + cost（0.70%+印花0.1%+佣金5元）+ survivorship（unbuyable 过滤）。**v2 删**：day_paired_lift / walk-forward / Bonferroni 全局 / IC（这些归 S161 verifier，非 Accounting；IC 是 cross-sectional scalar ≠ return series 喂 verify() 是 category error）。**接 filled Trades + bars**（bars needed for intrabar stop/take triggers at simulate_holding lines 104-106/114；非"给定 Trades → path return"）。**喂 S161 verifier（raw per-trade return series → verdict 闭环）**。复用 `strategies/kline_returns.py` simulate_holding/simulate_holding_with_confirm/_is_unbuyable_next_bar（**拆分重构非复用**，见 R2）+ `backtest_lite.py` IC/Spearman 提取进 S161 verifier（非 Accounting）。
  - **Executor 层（可插拔 fill，v2 修）**：`FillPolicy` 接口。`T+1OpenFill` 默认 impl（`fill(signal_date, bars) → entry_price = bars[signal_idx+1].open`，offset≥1 anti-lookahead，现有 simulate_holding line 101 语义）。`IntradayConditionalFill` deferred stub（gap 方向，封板事件条件成交+不封亏损，需 P(seal) 模型）——**stub 主动返 status=untradeable（活哨兵非死代码，治 grill yagni refuted）**。engine **拒绝对未建模 fill 的隔夜捕获**（诚实显示不可交易，治 s144 gap-blindness）。**Accounting 只对 Executor ACCEPTED 的 fills 算 return**；refused fills→status=untradeable 无 return（否则 simulate_holding 仍从 bars[idx+1].open 算=错窗口）。
- **R2 反前视架构级（开源模式①）**：backtrader 0/-1 索引（策略 next() 只看已收盘 bar）+ `cheat_on_open` 显式开关（默认关）+ qlib Nested Decision Point（决策时只用当时可得信息）。**entry 时点可捕获性作架构级强约束**（FillPolicy offset≥1，非策略层自律）。**v2 注**：backtrader 0/-1+cheat_on_open 是借鉴概念模式（"借"框架），实际 batch-mode enforcement = R1 FillPolicy offset（bars[idx+1] 现有 simulate_holding 语义，非 event-driven cursor）。治 §44v1 错窗口根因。
- **R3 A 股成交规则建模（开源避免模式①）**：T+1 结算（当日买入不可卖）+ 涨跌停闸门（±10%/±5% ST/±20% 创业科创/±30% 北交，触板不成交）+ 停牌"该日不可交易"。放 Executor 层（学 zipline blotter 执行模拟与记账解耦），不污染策略代码。`_is_unbuyable_next_bar` 归 Executor fillability check（非 Accounting）。
- **R4 PIT FeatureStore DEFERRED（v2 修，治 grill yagni #20）**：**移 S160 §3 defer list**（PIT store = 被砍 lake 换名，NOW 无消费者——Trades 自带 signal_date，Accounting 读 pre-loaded bars list 如 simulate_holding's bars arg from kline_cache；复现性由 S161 Recorder frozen_commit + return series hash 保证）。**砍 pit_store.py from §3 + R4 from §4 acceptance + "PIT store" from §6 scope（medium-large→medium）**。S163 §5 改"读 cache 或 S162 PIT bundle"→"读 cache"。**re-introduce 条件**：Decision auto-generates Trades from signals（deferred）/ validated 线路需 cross-source as_of joins / kline_cache mutability 不足复现（则 snapshot kline_cache 非 multi-source ingest pipeline）。若 re-introduce 用 **SQLite + as_of column**（零新依赖，匹配项目 JSON+SQLite 全栈）非 parquet/duckdb（pyarrow/duckdb 未装，project 全栈无）。
- **R5 gap §44v2 run bypasses engine（v2 注）**：gap run（S161 §3）**绕过 engine**，直接从 daily bars 算（D close→D+1 open）——IntradayConditionalFill deferred，gap Trades 会被 engine 拒绝（untradeable）；原"gap_window_lift 已手喂 close→next-open"误导，改标"gap run bypasses engine, computes directly from daily bars"。

## 3. 受影响文件

- 新建 `backend/engine/decision.py`（Trades dataclass NOW + generate_trade_decision stub/TODO 待 qlib 核实）。
- 新建 `backend/engine/accounting.py`（path_return + cost + survivorship，design-agnostic，接 filled Trades+bars，喂 S161 verifier；**不含 day_paired/walk-forward/Bonferroni/IC**）。
- 新建 `backend/engine/executor.py`（Executor + FillPolicy 接口 + T+1OpenFill impl + IntradayConditionalFill stub 返 untradeable + _is_unbuyable_next_bar fillability check）。
- 新建 `backend/engine/fill_policies.py`（T+1OpenFill impl + IntradayConditionalFill stub deferred）。
- ~~新建 `backend/engine/pit_store.py`~~（**v2 defer to S160 §3**）。
- **拆分重构** `backend/strategies/kline_returns.py` simulate_holding（FillPolicy.fill→Executor / path_return→Accounting，非"复用"）+ `backtest_lite.py` IC/Spearman 提取进 S161 verifier（非 Accounting）。

## 4. 验收标准

- [ ] R1a Trades dataclass（signal_date+fill_type，entry_price Executor 填）+ Decision 取 Trades input。
- [ ] R1b generate_trade_decision stub/TODO 标"待 qlib gh-proxy 源码核实"。
- [ ] R1 Accounting design-agnostic（path_return+cost+survivorship，接 filled Trades+bars，喂 S161 verifier raw return series；**不含 day_paired/walk-forward/Bonferroni/IC**）。
- [ ] R1 Executor pluggable fill（FillPolicy 接口，T+1OpenFill offset≥1 默认，IntradayConditionalFill stub 返 untradeable，refused fills 无 return）。
- [ ] R2 反前视架构级（FillPolicy offset≥1 batch enforcement；backtrader 0/-1+cheat_on_open 借鉴模式注释）。
- [ ] R3 A 股成交规则（T+1 + 涨跌停闸门 + 停牌，Executor 层 _is_unbuyable_next_bar）。
- [ ] R4 PIT FeatureStore **deferred**（不在 NOW acceptance；S163 §5 改"读 cache"）。
- [ ] R5 gap run bypasses engine 标注（直接 daily bars 算 D close→D+1 open）。
- [ ] Accounting 喂 S161 verifier（raw return series → verdict 闭环）。
- [ ] simulate_holding 拆分重构（非复用）+ T+1 guard (idx+2>=len) 保。
- [ ] pytest 单测（三层解耦 + 反前视 + A 股规则）+ tsc 0。

## 5. 合规与工程底线自查

- [x] 不臆造：engine 实算（path return/cost/survivorship 公式从 kline_returns 现有 + López de Prado），禁心算。**generate_trade_decision 待 qlib 源码核实非凭未核实签名**（S153 v1 教训）。
- [x] 私有数据隔离：无 PIT store（deferred），bars from kline_cache（.vibe-research）。
- [x] em_get 防封：无 ingest（PIT deferred），无防封 concern。
- [x] §44 降级参考性建议：engine Accounting 喂 verifier（判定器），fill deferred 诚实显示不可交易。
- [x] verdict 外推禁令：IntradayConditionalFill deferred 标"gap 不可交易"非"无 edge"（stub 返 untradeable 活哨兵）。
- [x] 不闭门造车：借 qlib Nested Decision Point + backtrader 0/-1+cheat_on_open + zipline blotter 模式（开源调研，**qlib 待 gh-proxy 源码核实**）+ López de Prado。spec-grill 8-lens 对抗验证修真洞。

## 6. 分级

medium（三层引擎 + A 股规则，**v2 砍 PIT store**）。feature 分支 + grill（反前视架构级变更，本 spec 涉架构层）。分步实施：Decision Trades input 先（NOW）→ Accounting（拆分重构 kline_returns simulate_holding）→ Executor pluggable（T+1OpenFill 默认）→ IntradayConditionalFill stub deferred。generate_trade_decision 待 qlib 源码核实。PIT FeatureStore defer to S160 §3。
