# Spec: S162 — 反前视回测引擎三层（Decision+Accounting design-agnostic / Executor pluggable fill）

> 状态：草案（S160 component 2，priority 2）
> 关联：S160 / S161 / open-source-quant-framework-research-2026-09-06 / grill-foundation-holes-2026-09-06
> 分级：medium-large（三层引擎 + PIT store + A 股规则）—— feature 分支 + grill（反前视架构级变更）+ 分步实施

## 0. 问题

grill #2 证"design-agnostic 回测引擎不可能"——entry/fill 绑方向。grill verify fix "engine 不含 fill 语义"被世纪大辩论框架架构师+风控 lens 否（降级成 simulate_holding 已有 + s144 gap-blindness 焙进 flat -3% stop overstate edge）。需 engine 三层解耦：Decision+Accounting design-agnostic / Executor 可插拔 fill（deferred），非 no-fill 降级。

## 1. 目标

建反前视回测引擎三层——Decision（Trades 生成，NOW input）+ Accounting（path return/cost/survivorship，design-agnostic，喂 S161 verifier）+ Executor（可插拔 fill，T+1OpenFill 默认，IntradayConditionalFill deferred）。借 qlib Nested Decision Point + backtrader 0/-1 索引+cheat_on_open（开源调研采纳模式①）治 §44v1 错窗口根因（entry 时点可捕获性架构级强约束非策略层自律）。

## 2. 需求清单

- **R1 三层解耦**：
  - **Decision 层**：`generate_trade_decision(signal, execute_result=None) → Trades`（list[{code, entry_date, entry_price, exit_date, exit_price, direction, size}]）。qlib Nested Decision Point 模式（决策只用当时可得信息，Executor 可嵌套日级→分钟级）。**NOW Trades 是 input**（手动喂，如 gap_window_lift 已手喂 close→next-open），未来 signal→Trades 自动生成 deferred。
  - **Accounting 层（design-agnostic）**：给定 Trades → path return / day_paired_lift（非池化）/ walk-forward / Bonferroni 全局 / cost（0.70%+印花0.1%+佣金5元）/ survivorship（unbuyable 过滤：一字板四价相等+涨停）。**喂 S161 verifier**（return series → verdict）。复用 `strategies/kline_returns.py` simulate_holding/simulate_holding_with_confirm/_is_unbuyable_next_bar + `backtest_lite.py` IC/Spearman（提取进 Accounting）。
  - **Executor 层（可插拔 fill）**：`FillPolicy` 接口。`T+1OpenFill` 默认 impl（entry=bars[idx+1].open，现有 simulate_holding 语义）。`IntradayConditionalFill` deferred（gap 方向，封板事件条件成交+不封亏损，需 P(seal) 模型）。engine **拒绝对未建模 fill 的隔夜捕获**（诚实显示不可交易，治 s144 gap-blindness）。
- **R2 反前视架构级（开源模式①）**：backtrader 0/-1 索引（策略 next() 只看已收盘 bar）+ `cheat_on_open` 显式开关（默认关，模拟集合竞价须显式开）+ qlib Nested Decision Point（决策时只用当时可得信息）。entry 时点可捕获性作**架构级强约束**（非策略层自律）。治 §44v1 错窗口根因。
- **R3 A 股成交规则建模（开源避免模式①）**：T+1 结算（当日买入不可卖）+ 涨跌停闸门（±10%/±5% ST/±20% 创业科创/±30% 北交，触板不成交）+ 停牌"该日不可交易"。放 Executor 层（学 zipline blotter 执行模拟与记账解耦），不污染策略代码。
- **R4 PIT FeatureStore（zipline Bundle 模式，开源模式②）**：ingest（em_get/baostock/akshare+breaker 防封）→本地 parquet/duckdb 按 `as_of` 键。引擎回测只读 bundle 零网络。ingest 一次固化→回测可复现。**轻量**（parquet+哈希，非 bcolz，YAGNI）。

## 3. 受影响文件

- 新建 `backend/engine/decision.py`（generate_trade_decision + Trades dataclass）。
- 新建 `backend/engine/accounting.py`（path return + day_paired_lift + walk-forward + Bonferroni 全局 + cost + survivorship，喂 S161 verifier）。
- 新建 `backend/engine/executor.py`（Executor + FillPolicy 接口）。
- 新建 `backend/engine/fill_policies.py`（T+1OpenFill impl + IntradayConditionalFill stub deferred）。
- 新建 `backend/engine/pit_store.py`（PIT FeatureStore，parquet/duckdb 按 as_of）。
- 复用 `backend/strategies/kline_returns.py`（simulate_holding/simulate_holding_with_confirm/_is_unbuyable_next_bar 提取进 Accounting/Executor）。
- 复用 `backend/backtest_lite.py`（IC/Spearman 提取进 Accounting）。

## 4. 验收标准

- [ ] R1 三层解耦（Decision input Trades / Accounting design-agnostic return+cost+survivorship / Executor pluggable fill）。
- [ ] R2 反前视架构级（0/-1 索引 + cheat_on_open 显式 + Nested Decision Point，entry 可捕获性强约束）。
- [ ] R3 A 股成交规则（T+1 + 涨跌停闸门 + 停牌，Executor 层，不污染策略）。
- [ ] R4 PIT FeatureStore（parquet as_of，回测只读 bundle 零网络，ingest 固化可复现）。
- [ ] Accounting 喂 S161 verifier（return series → verdict 闭环）。
- [ ] IntradayConditionalFill 标 deferred stub（不 impl，诚实显示 gap 不可交易，不焙进 s144 gap-blindness）。
- [ ] pytest 单测（三层解耦 + 反前视 + A 股规则 + PIT 复现）+ tsc 0。

## 5. 合规与工程底线自查

- [x] 不臆造：engine 实算（path return/cost/survivorship 公式从 kline_returns 现有 + López de Prado），禁心算。PIT bundle 快照固化可复现。
- [x] 私有数据隔离：PIT bundle 写 .vibe-research 不进 git。
- [x] em_get 防封：ingest 走 em_get+breaker（非裸 requests，治 grill #10）。
- [x] §44 降级参考性建议：engine Accounting 喂 verifier（判定器），fill deferred 诚实显示不可交易。
- [x] verdict 外推禁令：IntradayConditionalFill deferred 标"gap 不可交易"非"无 edge"。
- [x] 不闭门造车：借 qlib Nested Decision Point + backtrader 0/-1+cheat_on_open + zipline blotter 模式（开源调研）+ López de Prado。

## 6. 分级

medium-large（三层引擎 + PIT store + A 股规则）。feature 分支 + grill（反前视架构级变更，本 spec 涉架构层）。分步实施：Decision input 先（NOW Trades 手动喂）→ Accounting（提取 kline_returns/backtest_lite 现有）→ Executor pluggable（T+1OpenFill 默认）→ IntradayConditionalFill stub deferred → PIT FeatureStore。
