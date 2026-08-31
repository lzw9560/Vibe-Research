# Spec: S125 — S124 scan 3 HIGH confirmed_lying 点修（承重链 regress 闭合）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S124 scan round 2（registry S124 节）3 HIGH confirmed_lying；S121（被 portfolio 消费者反吞 + valuation sibling 漏）

## 1. 问题 / 目标

S124 scan round 2 扫出 3 HIGH confirmed_lying（全承重链/regress），本 spec 点修闭合。or-zero 契约级 sweep + 漏扫 dim 登记 follow-up（不本 spec）。

| # | crack | where | sev | 承重链 |
|---|---|---|---|---|
| 1 | portfolio-price-or-zero-defeats-s121 | portfolio.py:147 | HIGH | pf_data→position_advisor_v2:618 pnl_pct→:351 _HARD_STOP_PCT→false close advisory + GET /api/portfolio 前端伪全亏 |
| 2 | ai-valuation-tencent-zero-coercion-s121-incomplete | mappers.py:251-252 | HIGH | valuation pe_ttm/pb=0 喂 LLM 当真 PE=0（S121 只修 quote_from_tencent，valuation sibling 漏） |
| 3 | storm-prediction-no-top-level-data-status | storm_predictor.py:29-38 | HIGH | StormPrediction probability/suggested_position 从含 degraded 因子加权和算出当权威，无顶层 data_status |

目标：3 条点修闭合承重链 regress，加测试钉死，全量 pytest 0 回归。**or-zero 407 处契约级治理 + 漏扫 dim（scheduled_tasks bare except/cron DAG/funnel total_score）登记 follow-up spec。**

## 2. 背景

- **#1**：`portfolio.get_portfolio`(portfolio.py:135-172) 取 `model = quote_from_tencent(...)`（146），S121 在 mappers.py:69 把 price None 化（`price=_numf(raw.get("price")) or None`，0 永不合法）。但 portfolio.py:147 `price = model.price or 0.0` **反吞 None→0.0** → `mv=0`(148)/`pnl=-cv`(150)/`pnl_pct=-100%`(155)。row dict(151-156)+totals(159-167) 无 data_status 字段。承重链：`position_advisor_v2.advise_holdings`(590-633) `pf_data = await pf.get_portfolio()`(600) → per holding `pnl_pct = h.get("pnl_pct") or 0.0`(618)（-100.0 truthy 直通）→ `_holding_action_layer3(pnl_pct,...)`(633) → `:351 if pnl_pct <= _HARD_STOP_PCT(-5.0)` → True → `return "close", f"...止损"`(351-352) → **false close advisory** 喂 GET /api/advisory/summary。前端 GET /api/portfolio 见伪全亏。verifier 5 路 refutation 全败（None reachable via 异常 raw={} + 停牌 tencent price=0；consumer 无 data_status 过滤；承重链 mounted app.py:212,239；-100.0 truthy 直通止损阈值；无 escape field）。
- **#2**：`valuation_from_full_valuation`(mappers.py:245-263) `pe_ttm=_numf(raw.get("pe_ttm"))`(251)/`pb=_numf(raw.get("pb"))`(252) **无 `or None`**。S121(quote_from_tencent mappers.py:76-77) 加了 `or None`（"0 永不合法"），valuation sibling 漏。pe_ttm=0.0 当真 PE=0 喂 query_valuation→chat.py LLM（极度低估）。critic cross-cutting：S121 是点修非契约，sibling mappers（valuation/gstock_us_hk）未守约。
- **#3**：`StormPrediction`(storm_predictor.py:29-38) dataclass 无 `data_status` 字段。`predict_storm`(341-377) `probability = global_f.score*0.35 + internal_f.score*0.35 + news_f.score*0.20 + calendar_f.score*0.10`(361-366)，4 因子各有 `data_status`（StormFactor:26，ok|degraded|fallback_current|missing），但顶层 probability/suggested_position 无 data_status——含 degraded/missing 因子的加权和当权威呈现。对齐 risk_models._merge_data_status(216) 范式（OneDayRisk.data_status 聚合最差子状态）。

## 3. 需求清单

### R1 portfolio 反吞 None 诚实化 + position_advisor 跳 degraded
- [ ] R1.1 `portfolio.get_portfolio`(portfolio.py:145-156)：`model.price is None` 时 row 标 `data_status="degraded"`，`price=None`/`market_value=None`/`pnl=None`/`pnl_pct=None`（**不 `or 0.0` 造伪 -100%**）。price 有值时维持原计算 + `data_status="ok"`。
- [ ] R1.2 totals(159-167)：若任一 holding degraded → `totals.data_status="degraded"`，`market_value`=sum(非 degraded holdings 的 mv)（不把缺失股的 0 加进总额造伪缩水），`pnl`/`pnl_pct` 同理 sum 非 degraded + 标 degraded。全 ok 时 `data_status="ok"`。
- [ ] R1.3 `position_advisor_v2.advise_holdings`(616-633)：读 `h.get("data_status")`，degraded → **跳过该 holding 的 advisory**（不喂伪 pnl_pct 给 layer1/2/3 触发 false close），返 `AdvisoryItem(action="hold", reason="行情取数失败，数据缺失不判止损")` 或 skip。**不基于伪 -100% 触发 close。**
- [ ] R1.4 测试钉死（test_portfolio 或 test_position_advisor）：①price=None（tencent 失败/停牌）→ row data_status=degraded + price/mv/pnl/pnl_pct=None（非 0/-100%）；②position_advisor 跳过 degraded holding 不触发 close（action=hold/skip，非 close）；③price 有值 → data_status=ok + 正常 pnl_pct。

### R2 valuation mappers S121 契约补全
- [ ] R2.1 `valuation_from_full_valuation`(mappers.py:251-254)：`pe_ttm`/`pb`/`ps_ttm`/`pcf_ttm` 加 `or None`（0 永不合法，对齐 S121 quote_from_tencent:76-87 范式）。`price`(249)/`dividend_yield`(255)/`forward_pe`(257)/`consensus_eps`(258)/`cagr_pct`(259)/`peg`(260) 不动（0 合法或非 PE 类）。
- [ ] R2.2 测试钉死（test_s008_mappers）：valuation pe_ttm/pb/ps_ttm/pcf_ttm 0→None；真值不变（19.92→19.92）；None→None。

### R3 StormPrediction 顶层 data_status
- [ ] R3.1 `StormPrediction`(storm_predictor.py:29-38) 加 `data_status: str = "ok"` 字段（# ok|degraded|fallback_current|missing，对齐 StormFactor:26）。
- [ ] R3.2 `predict_storm`(341-377)：算 `data_status = _worst_factor_status([global_f, internal_f, news_f, calendar_f])`（取 4 因子 data_status 最差，severity missing>degraded/fallback_current>ok）。`StormPrediction(..., data_status=data_status)`（371-377）。
- [ ] R3.3 `_worst_factor_status` helper（模块内，inline severity map `{"ok":0,"degraded":1,"fallback_current":1,"missing":2}`，对齐 risk_models._merge_data_status:597-601 范式，避免 import risk_models 循环依赖）。
- [ ] R3.4 测试钉死（test_s088 或 storm 测）：①全因子 ok→StormPrediction.data_status=ok；②任一因子 missing→data_status=missing；③degraded+fallback_current→data_status=degraded。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/portfolio.py` | R1.1 row 不反吞 None + data_status / R1.2 totals degraded 标 |
| `backend/strategies/position_advisor_v2.py` | R1.3 跳 degraded holding 不触发 close |
| `backend/data/mappers.py` | R2.1 valuation pe_ttm/pb/ps_ttm/pcf_ttm `or None` |
| `backend/strategies/storm_predictor.py` | R3.1 StormPrediction data_status / R3.2 predict_storm 算 / R3.3 helper |
| `backend/tests/test_data_honesty.py` 或对应测 | R1.4/R2.2/R3.4 钉死 |

> 测试文件分派互不重叠（R1→test_position_advisor 或 test_data_honesty / R2→test_s008_mappers / R3→test_s088_storm 或 test_data_honesty），impl 各自加不冲突。

## 5. 设计方案

**R1 不反吞 None + position_advisor 跳 degraded**（非 totals=None）：row 标 degraded + 字段 None，totals 聚合非 degraded + 标 degraded（用户见部分总额+degraded 徽章，比 None 总额有用）。position_advisor 跳 degraded holding 返 hold/skip（不喂伪 -100% 给止损层）。对齐 S111 R4 `_empty_capital_flow(status)` + sentiment_context._empty_context 范式（缺失不编值，data_status 区分）。

**R2 只补 PE 类比值字段**（pe_ttm/pb/ps_ttm/pcf_ttm `or None`）：0 永不合法（PE/PB/PS/PCF=0 意味无盈利/无净资产/无营收/无现金流，应为 None 表示"未定义"而非 0）。不动 price/dividend_yield/forward_pe/consensus_eps/cagr_pct/peg（0 可合法或非同语义）。对齐 S121 quote_from_tencent:76-87（"0 永不合法"字段加 `or None`）。

**R3 inline severity map**（非 import risk_models._merge_data_status）：storm_predictor 已 import storm_daemon，加 risk_models 可能循环；inline `{"ok":0,"degraded":1,"fallback_current":1,"missing":2}` 3 行 helper 自足。StormPrediction 是 frozen dataclass，加字段默认 `"ok"` 向后兼容（既有构造无 data_status → ok）。

## 6. 验收标准

- [ ] A1 R1：price=None → row data_status=degraded + price/mv/pnl/pnl_pct=None（非 0/-100%）；position_advisor 不触发 close
- [ ] A2 R2：valuation pe_ttm/pb/ps_ttm/pcf_ttm 0→None；真值不变
- [ ] A3 R3：StormPrediction.data_status = 最差因子 status（missing>degraded/fallback>ok）
- [ ] A4 全量 `pytest -m "not live" --deselect` 既有 flaky（newsradar/s032/spec_consistency/test_s040/test_market_degrades_without_akshare）0 回归
- [ ] A5 S124 scan 3 HIGH confirmed_lying 全修（registry S125 节）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐：3 条均诚实化（不反吞 None/补 S121 契约/加顶层 provenance），系统能力，无新方向建议
- [x] 判断可复现：纯代码逻辑 + S124 scan 已抽验实锤；测试 mock 钉死
- [x] 涨停四池/连板：不涉
- [x] 私有数据：不涉
- [x] em_get 防封：不改取数路径（R1 改消费层，R2 改 mapper，R3 改 dataclass）

## 8. 测试计划

`pytest -m "not live"` + R1.4/R2.2/R3.4 钉死测试。`--deselect` 既有 flaky 集。

## 9. 风险与回滚

- **风险**：R1 position_advisor 跳 degraded holding 可能漏真 close 信号（若 price 真断而非停牌）——但 degraded 标 hold/skip 比 false close 更安全（保守误差非 lie）；运维侧 tencent 失败应修源非靠 advisory 兜底。R2 valuation 0→None 若下游消费者（query_valuation）假设 float 不容 None→查 Valuation dataclass 字段须 `float|None`（S121 Quote 已 `float|None`，Valuation 应同）。R3 StormPrediction 加字段，frozen dataclass 默认值兼容。
- **回滚**：每 R 独立 commit。R1 portfolio `or 0.0` 回 + position_advisor 删 data_status 跳过；R2 mappers 删 `or None`；R3 StormPrediction 删 data_status 字段 + predict_storm 删算。
