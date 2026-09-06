# 主力意图判断 · 讨论与数据策略（2026-09-06）

> 项目讨论范畴落盘。关联：multiline-strategy-direction memory（对抗市场维度）、data-source-capabilities memory、§1.2 工程底线。
> 用户原则："一定有办法获取，不依赖单一数据源"——多源替代 + §1.2 防封路由 + tool-augmented LLM。

## §1.2 边界（先立）

主力真实意图**不可直接观测**（hidden），只能从**可复现 proxies** 推断。禁臆测 intent（LLM fabricate 不算）。"判断主力意图" = 规则化组合 proxies → accumulation/distribution/trap 信号，可复现。

**LLM 边界**：
- ✅ tool-augmented LLM（hithink 经 query_quote/query_valuation/query_reports/query_news 等工具取数）= 工具取数，§1.2 OK。
- ✅ LLM 分析（对 proxies 数据推理主力意图）= 分析，§1.2 OK。
- ❌ LLM fabricate（无工具，LLM 权重"猜"数据/意图）= 臆造，§1.2 违反。

## Proxies 清单（数据可得性 + 多源替代）

| proxy | edge | 主源 | 多源替代 | §1.2 路由 |
|---|---|---|---|---|
| 大宗交易折价 | STRONG | eastmoney block_trade（datacenter 非 IP封）| akshare stock_fund_flow_big_deal | em_get（datacenter）|
| 龙虎榜机构席位 | STRONG | akshare stock_lhb（历史日期）| ths 龙虎榜 | akshare（polite）|
| 大单净流入 vs 价背离 | STRONG | push2his | akshare stock_individual_fund_flow / stock_main_fund_flow / sina | em_get+breaker+proxy（push2his IP封→降级 akshare/sina）|
| 封单撤单（假封板）| STRONG（诱多）| push2ex 实时 | — | live-only（无历史，需采集）|
| 股东增减持 | STRONG | akshare/ths stock_ggcx | event_factors 已有 | akshare（polite）|
| 限售解禁 | STRONG（负向）| eastmoney lockup_expiry | akshare | em_get（datacenter）|
| 北向资金 | STRONG | HKEX（2024-08-19 停实时）| akshare stock_hsgt_hist_em（历史 T+1）/ stock_hsgt_hold_stock_em（持股）| akshare（polite，历史/T+1 非 real-time）|
| 资金流（主力净流入）| STRONG | push2his | akshare stock_individual_fund_flow / stock_main_fund_flow / sina_financial | em_get+breaker+proxy |

**数据硬伤 + 替代**：
- 北向 2024-08-19 停 real-time → 用 akshare stock_hsgt_hist_em 历史 + T+1 daily（非 real-time 但回测够）。
- 资金流/大单 push2his IP封 → 走 em_get+breaker+proxy（§1.2），降级 akshare stock_individual_fund_flow / sina。
- 封单撤单 live-only → 设采集 pipeline（每日 push2ex cached）。
- **不依赖单源**：每 proxy ≥2 源（主源+替代），em_get 路由防封。

## 陷阱检测（诱多/诱空，可复现 intraday pattern）

- **假涨停（诱多）**：封板后开板（open_count>0）+ 次日跌。H2 测封板时间但没作"诱多 pattern"——可加。
- **假突破（诱多）**：突破 20d 后回落（breakout_20d=True 但 D+1 跌）。
- **假破位（诱空）**：破位后反弹。
- 需 intraday 数据：baostock 5min（31 天）/ 1min（~8 天 via akshare stock_zh_a_minute）。

## 推断规则化（示例，非臆测）

- **隐蔽吸筹** = 大宗溢价 + 机构买席（龙虎榜）+ 大单净流入 + 价不涨（大单-价背离）。
- **隐蔽出货** = 大宗折价>5% + 机构卖席 + 股东减持 + 解禁临近。
- **诱多陷阱** = 假涨停（封板后开板）+ 次日跌 + 大宗折价。
- **诱空陷阱** = 假破位 + 次日反弹 + 大宗溢价。
- 规则可复现（proxy 组合，阈值显式），非 LLM 臆测。

## 待验证（§44 v2 在对窗口+n够）

- 上述 proxies + trap patterns 用 §44 v2 验（前置窗口 sanity→对窗口+n够重方法论→不外推）。
- 数据起 8 月（baostock 8 月 / zt_history 26 天 / push2his IP封），部分需 live 积累 30-60 天。
- 多源策略：每 proxy ≥2 源，em_get 路由，不依赖单源（用户原则）。
