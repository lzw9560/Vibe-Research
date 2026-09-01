# Spec: S132 — query_global_stock + profit_forecast 源断诚实化（S131 R3 范式扩展，advisory AI-tool 级）

> 状态：待实现
> 作者：lzw9560  日期：2026-09-01
> 关联：S132 verify workflow `wf_8681ebb0-b63`（3 维对抗 verify 16 missed areas + critic）确认 2 confirmed_lying（#5 AI工具 advisory 级）+ 13 actually_honest + 1 uncertain。critic s133_recommendation: **STOP**（承重链 S118-S131 全 honest，剩 2 advisory-display 级 trivial 修，不开 scan 周期）。本 spec 修 2 confirmed（S131 R3 ps_pcf_status 范式扩展）。

## 1. 问题 / 目标

2 条 confirmed_lying（S132 verify 实锤，均 MEDIUM advisory AI-tool display 级，不进 position/risk 决策）：

| # | crack | where | 撒谎机制（verify 实锤） |
|---|---|---|---|
| 1 | query_global_stock source-fail-on-valid-symbol masked as null quote | gstock.py:289-302 (us_hk_stock) | valid symbol（resolve_symbol 成功）+ 源断（_push2_stock_get 返 None = 双 host 全挂/限流）→ `_quote_from({})` 全 null quote dict → us_hk_stock 返非空 dict {code,name,market,quote:{全 None},metrics} → query_global_stock `if not raw` False → mapper → GlobalStock null quote → LLM 见"valid result 无 price"非"源断"。`if not raw` 只挡 invalid symbol（resolve_symbol 失败→{}），不挡 valid+源断 |
| 2 | profit_forecast empty-DataFrame silent null eps/peg | astock.py:176 (full_valuation) | akshare 装了但 stock_profit_forecast_ths 返空 DataFrame（soft-block/无覆盖）→ profit_forecast 返 [] 无 exception → rows=[] → 无 forecast_note/data_status → eps_26e/eps_27e/peg/digest_years 留 None（init:134）→ LLM 见 null eps/peg 无法辨"无分析师覆盖"（合法，小盘股常见）vs"源断" |

**严重度**：均 advisory AI-tool display 级（喂 LLM via query_global_stock/query_valuation），**不进 risk_score/winrate/position 承重链**（critic 确认）。修法对齐 S131 R3 ps_pcf_status 范式（加 status flag → mapper 透传 → model 字段 → LLM 见"源断"非"无数据"）。

**目标**：2 条全修，加测试钉死，全量 pytest 0 回归。critic STOP——不开 S133 scan（1 uncertain query_reports + query_news parallel 登记 follow-up，需下轮 scan+verify 确认，非已确认）。

## 2. 背景

- **S131 R3 范式**：astock.py:149 `out["ps_pcf_status"]="hithink_unavailable"`（except 块）→ data/mappers.py:267 `data_status=raw.get("ps_pcf_status")` → models/valuation.py:38 `data_status: str | None = None`。本 spec 同款加 quote_status（GlobalStock）+ forecast_status（Valuation）。
- **#1**：`_push2_stock_get`（gstock.py:63）双 host push2/push2delay fallback；全挂返 None。`_quote_from(d or {})` 注释"行情临时取不到也返回完整 null 形状，契合 GlobalQuote 类型"——type-safety 但漏 honesty flag。
- **#2**：profit_forecast（akshare_src.py:31-35）`df.to_dict('records') if df is not None and not df.empty else []`。full_valuation:176 `try: rows = profit_forecast(code) except DependencyMissing: forecast_note=...; return`——只挡 DependencyMissing（akshare 未装），不挡 empty-DataFrame。

## 3. 需求清单

### R1 query_global_stock quote_status（gstock.py + mappers + GlobalStock model）
- [ ] R1.1 `us_hk_stock`（gstock.py:289-302）：`d = _push2_stock_get(...)` 后，`quote_status = "unavailable" if d is None else None`；return dict 加 `"quote_status": quote_status`。
- [ ] R1.2 `models/global_stock.py` GlobalStock 加 `quote_status: str | None = None`。
- [ ] R1.3 `data/mappers.py global_stock_from_gstock`（:386）：`quote_status=raw.get("quote_status")`。
- [ ] R1.4 测试钉死（新 test_s132_global_stock.py）：①`_push2_stock_get` 返 None（mock 源断）+ valid symbol → GlobalStock.quote_status="unavailable"（非 None）；②正常 → quote_status=None；③invalid symbol → {}（resolve_symbol 失败，原行为不破）。

### R2 profit_forecast forecast_status（astock.py + mappers + Valuation model）
- [ ] R2.1 `full_valuation`（astock.py:176 后）：`rows = profit_forecast(code)` try/except DependencyMissing 之后，`if not rows: out["forecast_status"] = "empty_or_source_unavailable"`（empty-DataFrame 路径，非 DependencyMissing——后者已 return）。
- [ ] R2.2 `models/valuation.py` Valuation 加 `forecast_status: str | None = None`（与 data_status 分立——data_status=PS/PCF 源，forecast_status=eps/peg 源，两源独立）。
- [ ] R2.3 `data/mappers.py valuation_from_full_valuation`（:267 附近）：`forecast_status=raw.get("forecast_status")`。
- [ ] R2.4 测试钉死（新 test_s132_profit_forecast.py）：①profit_forecast 返 []（mock akshare empty DataFrame）→ Valuation.forecast_status="empty_or_source_unavailable"（eps/peg None 有标）；②正常返 rows → forecast_status=None；③DependencyMissing → forecast_note（原行为不破）。

### R3 registry + 回归
- [ ] R3.1 registry 加 S132 节标注 2 条闭合 + critic STOP（16 missed: 2 confirmed 修 / 13 honest / 1 uncertain query_reports + query_news parallel 登记 follow-up）。
- [ ] R3.2 全量 `pytest -m "not live"` 0 回归。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/gstock.py` | R1.1 us_hk_stock 加 quote_status |
| `backend/models/global_stock.py` | R1.2 GlobalStock 加 quote_status 字段 |
| `backend/data/mappers.py` | R1.3 global_stock_from_gstock 透传 quote_status |
| `backend/astock.py` | R2.1 full_valuation 加 forecast_status |
| `backend/models/valuation.py` | R2.2 Valuation 加 forecast_status 字段 |
| `backend/data/mappers.py` | R2.3 valuation_from_full_valuation 透传 forecast_status |
| `backend/tests/test_s132_*.py` | R1.4/R2.4 新测 |
| `specs/S111-真实裂缝登记册/registry.md` | R3.1 S132 节 |

> 6 处 edit + 2 测试文件，均 S131 R3 范式扩展，blast radius 极小。

## 5. 设计方案

**统一 S131 R3 范式**：源断处设 status flag（astock/gstock）→ mapper 读 raw 透传 → model 加字段 → model_dump 喂 LLM 见"源断"非"无数据"。forecast_status 与 data_status 分立（两源独立：PS/PCF vs eps/peg）。

**critic STOP 服从**：不开 S133 scan 周期。1 uncertain（query_reports eastmoney_reports HTTP error masking，结构脆弱未证实）+ query_news parallel（akshare empty-DataFrame 同款，S131 scan 已记 uncertain）登记 follow-up，需下轮 scan+对抗 verify 确认，非已 confirmed_lying。

**scope 守 2 confirmed**：13 actually_honest 不动（d3 9-status data_status backstop 闭合 / d6 consumer 已处理 / d5 query_quote/skyrocket/cache-stale 已 honest）。

## 6. 验收标准

- [ ] A1 R1：源断+valid symbol → GlobalStock.quote_status="unavailable"；正常→None；invalid→{}
- [ ] A2 R2：empty DataFrame → Valuation.forecast_status="empty_or_source_unavailable"；正常→None；DependencyMissing→forecast_note
- [ ] A3 全量 `pytest -m "not live"` 0 回归
- [ ] A4 registry S132 节 + critic STOP

## 7. 合规与工程底线自查

- [x] 不臆造：#1 源断标 quote_status 非"valid null quote"；#2 empty DataFrame 标 forecast_status 非"无分析师覆盖"
- [x] 判断可复现：S132 verify 实锤 + 测试 mock 钉死
- [x] 私有数据：不涉
- [x] em_get 防封：#1 _push2_stock_get 走 em_get（已有限流/熔断/代理），改的只是返 None 时加 flag 不改取数路径；#2 akshare 非 em_get
- [x] §44：均 advisory AI-tool display 级，非 winrate/r/verdict 承重链（critic 确认）

## 8. 测试计划

`pytest -m "not live"` + 新 test_s132_*.py（R1.4 三测 + R2.4 三测 = 6 测）。

## 9. 风险与回滚

- **风险**：model 加字段（quote_status/forecast_status）加性兼容，不破既有 consumer；mapper 透传 raw.get（缺失→None）。无回归风险。
- **回滚**：每 R 独立，model 字段可删、flag 可撤。
