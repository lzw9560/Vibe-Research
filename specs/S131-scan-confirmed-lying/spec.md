# Spec: S131 — scan #3/#5/#6 confirmed_lying + lockup-expiry（10+1 项诚实化）

> 状态：待实现
> 作者：lzw9560  日期：2026-09-01
> 关联：scan workflow `wf_cad164bc-f17`（3 维 finder + per-finding 对抗 verify + critic，16 agent 0 error）确认 10 confirmed_lying（#3 顶层聚合 3 / #5 AI工具 1 / #6 em_get消费者 6）+ 1 actually_honest（strategy_funnel_registry:485 死代码，false positive 抓到）+ 1 uncertain（query_news 未证实，留观察）。本 spec 修 10 confirmed + lockup-expiry（registry:418 非 scan 已知）。critic flag 的 16 个未深扫区域**登记 follow-up，不本 spec**（对齐"别陷验证循环"，需下轮 scan+verify 才确认）。

## 1. 问题 / 目标

10 条 scan-confirmed + 1 条已知，分 3 维：

| # | crack | where | sev | 维 | 撒谎机制（scan verify 实锤） |
|---|---|---|---|---|---|
| 1 | storm_internal_factor_gene_datasource_unchecked | storm_predictor.py:255 | MEDIUM | #3 | `_collect_internal_factor` 读 `g.factors.get("炸板后溢价",0) or 0`——gene `data_source='kline_rebuild'` 时该因子 NULL→0（data.py:153 `or 0`），rebound_score=50（中性 fabricated），StormFactor data_status 默认 'ok'（不查 g.data_source/missing_factors）→ _worst_factor_status 返 ok → StormPrediction 顶层 ok 当权威。probability 偏差 ~5.8pt 可跨 50/70 阈值改 suggested_position |
| 2 | sti_phase_silent_failure_not_in_merge | risk_models.py:153 | MEDIUM | #3 | `get_current_sti_phase` bare `except Exception: pass`（无 log）→ None → thresholds 默认 DIVERGENCE；`_merge_data_status`（:219-222）不含 STI phase status → composite risk 可在 STI 源断时仍 ok |
| 3 | query_valuation hithink PS/PCF failure masked as null | astock.py:148 | MEDIUM | #5 | hithink valuation_snapshot（PS/PCF 唯一源）失败→字段 None；mapper `valuation_from_full_valuation`（mappers.py:263-264）透传 None 当"无估值"喂 LLM，无 data_status 区分"源断"vs"真无" |
| 4 | concept_blocks swallow→empty-blocks | eastmoney.py:740 | HIGH | #6 | `except Exception: return {"total":0,"boards":[],"concept_tags":[]}`——源断与合法空同形，下游 catalyst/topology SectorEdgeProvider 当合法空消费 |
| 5 | em_zt_topic_pool swallow→empty list | eastmoney.py:205 | HIGH | #6 | `except Exception: return []`（虽不缓存让重试，但下游 limitup/metrics/topology 当合法空算 zero-cache）。extreme_market_detector:128 已用 get_with_fallback_meta 包同款函数，余 callers 未包 |
| 6 | market_turnover_rank swallow→empty list | eastmoney.py:345 | MEDIUM | #6 | 双 host `except: continue` → list-comp over empty diff → []；get_turnover_top 不标 missing |
| 7 | sector_fund_flow swallow→empty list | eastmoney.py:321 | MEDIUM | #6 | 双 host `except: continue` → return []；overview build 无 per-field data_status |
| 8 | industry_comparison swallow→empty ranking | eastmoney.py:773 | LOW | #6 | `except: return {"top":[],"bottom":[],"total":0}`；/api/industry 不透 data_status（对齐 sector_divergence.py:150-159 应范式） |
| 9 | eastmoney_datacenter default-swallow | eastmoney.py:375 | LOW | #6 | `except: if raise_on_failure: raise; return []`（默认 False）——info-panel callers 不传 True，源断返 [] 当合法空 |
| 10 | lockup-expiry no-raise-on-failure | event_factors.py:156 + eastmoney.py:705 | LOW | registry:418 | `lockup_expiry` 用 eastmoney_datacenter 默认 swallow → 源断返 `{"history":[],"upcoming":[]}` → fetch_share_unlock 返 [] events → "无解禁" vs "源断"不可分（非 scan，registry 已知） |

**目标**：11 条全修，每条加测试钉死，全量 pytest 0 回归。critic 16 missed areas 登记 follow-up（下轮 scan+verify 确认后再修，不本 spec）。

## 2. 背景

- scan workflow `wf_cad164bc-f17` confirmedLying 10 条均经 per-finding 对抗 verify（默认 actually_honest，代码实锤才确认）+ critic 确认无 false positive。fix_hint 在 scan output（`/private/tmp/claude-501/.../tasks/wyjag35s5.output` result.confirmedLying[].fix_hint）。
- **#1** GeneScore model 有 `data_source`（models.py:54）+ `missing_factors`（:56）字段，data.py:174-175 load 时保留——storm factor 可读。kline_rebuild.py:189 设 `factors["炸板后溢价"]=None`（诚实 None），:209-210 标 data_source+missing_factors。但 storm_predictor.py grep 零引用 data_source/missing_factors。
- **#2** `get_current_sti_phase`（risk_models.py:142-155）裸 except:pass，对齐 S111 R7 calculate_base_risk 的 `except Exception → missing` 范式修。
- **#3-#9** em_get 消费者统一范式：加 `raise_on_failure` opt-in（对齐 S119 eastmoney_datacenter/dragon_tiger_board）+ 承重 callers 传 True，OR 用 `get_with_fallback_meta` 包 + per-field data_status（对齐 S111 _get_realtime_capital_flow）。
- **#10** lockup_expiry 与 S119 eastmoney_datacenter 同款 raise_on_failure opt-in 范式。

## 3. 需求清单

### R1 storm_internal_factor gene datasource（storm_predictor.py:233-255）
- [ ] R1.1 `_collect_internal_factor`（:233）读 gene 时检查 `g.data_source`（或 `g.missing_factors` 含 "炸板后溢价"/"封板率"）；若 gene 是 `kline_rebuild` 或该因子在 missing_factors → StormFactor 返 `data_status="degraded"`（非默认 ok）。
- [ ] R1.2 `炸板后溢价`/`封板率` 读法改：`g.factors.get("炸板后溢价")`（不 `or 0`），None 时 rebound_score=None 或显式标 degraded（不 fabricated 50）。
- [ ] R1.3 predict_storm 顶层 `_worst_factor_status`（:396）自然传播 internal_f 的 degraded → StormPrediction.data_status="degraded"（probability/suggested_position 不当权威）。
- [ ] R1.4 测试钉死：①gene data_source='kline_rebuild' → internal StormFactor data_status="degraded"；②_+其他 3 factor ok → StormPrediction.data_status="degraded"（顶层传播）；③正常 gene → ok 原行为不破。

### R2 sti_phase silent failure（risk_models.py:142-155）
- [ ] R2.1 `get_current_sti_phase` 返 `tuple[str|None, str]`（phase, status）：except → `(None, "missing")` + `logger.warning`；成功 → `(phase, "ok")`。
- [ ] R2.2 调用处 `get_dynamic_thresholds`（:65 附近）解构 status；`_merge_data_status`（:219-222）加 sti_status（9 statuses）。
- [ ] R2.3 测试钉死：①DB/源断 → (None,"missing") + warning；②成功 → (phase,"ok")；③merge 含 sti → sti missing 时 data_status=missing。

### R3 query_valuation hithink PS/PCF（astock.py:148 + mappers.py:263-264）
- [ ] R3.1 astock.py:148 except 块标 `out['ps_pcf_status']='hithink_unavailable'`（或 setdefault note），非静默 None。
- [ ] R3.2 mappers `valuation_from_full_valuation`（:263-264）读 ps_pcf_status → 透 data_status/note 给 query_valuation → chat.TOOLS 喂 LLM 见"源断"非"无估值"。
- [ ] R3.3 测试钉死：①hithink 失败 → ps_pcf_status='hithink_unavailable' 透传；②成功 → 无 status 标（原行为）。

### R4 concept_blocks raise_on_failure（eastmoney.py:732-740）
- [ ] R4.1 `concept_blocks(code, raise_on_failure=False) -> dict` 加 opt-in；except → `if raise_on_failure: raise`（对齐 S119 范式），否则原返空 dict（向后兼容）。
- [ ] R4.2 承重 callers（catalyst, topology SectorEdgeProvider）传 `raise_on_failure=True` + 上游 try/except/get_with_fallback_meta 兜成 degraded。
- [ ] R4.3 测试钉死：①raise_on_failure=True + 源断 → raise；②默认 False → 返空 dict（向后兼容）。

### R5 em_zt_topic_pool raise_on_failure（eastmoney.py:178-205）
- [ ] R5.1 `em_zt_topic_pool(..., raise_on_failure=False)` 加 opt-in；except → raise if True，否则 []。
- [ ] R5.2 limitup/metrics + topology callers 传 True，OR 包 `get_with_fallback_meta`（对齐 extreme_market_detector:128 已范式）。
- [ ] R5.3 测试钉死：①raise_on_failure=True+源断→raise；②默认→[]（向后兼容）；③extreme_market_detector 路径不破。

### R6 market_turnover_rank data_status（eastmoney.py:345 + get_turnover_top）
- [ ] R6.1 `market_turnover_rank` 双 host 失败 → raise 或返带 data_status 的空结构；`get_turnover_top`/build 检测空 → 标 `data_status='missing'`。
- [ ] R6.2 测试钉死：双 host 断 → data_status='missing'（非合法空）。

### R7 sector_fund_flow data_status（eastmoney.py:321 + overview build）
- [ ] R7.1 双 host 失败 → overview build 加 per-field `sectors_status='missing'`（或 raise + _sectors 标 missing）。
- [ ] R7.2 测试钉死：双 host 断 → sectors_status='missing'。

### R8 industry_comparison provenance（eastmoney.py:773 + /api/industry）
- [ ] R8.1 `industry_comparison` 源断 → /api/industry 用 `get_with_fallback_meta` + 透 data_status（对齐 sector_divergence.py:150-159），或标 data_status='missing'。
- [ ] R8.2 测试钉死：源断 → data_status='missing' 透传。

### R9 eastmoney_datacenter callers raise_on_failure（eastmoney.py:375 + info-panel callers）
- [ ] R9.1 info-panel callers（grep `eastmoney_datacenter(` 承重消费方）传 `raise_on_failure=True`，上游 try/except→502/missing 兜底；非承重留默认 False（KISS，YAGNI）。
- [ ] R9.2 测试钉死：承重 caller 源断 → raise/missing（非合法空）。

### R10 lockup-expiry raise_on_failure（eastmoney.py:705 + event_factors.py:156）
- [ ] R10.1 `lockup_expiry(code, trade_date=None, forward_days=90, raise_on_failure=False)` 加 opt-in；except → raise if True，否则原返 `{"history":[],"upcoming":[]}`（向后兼容）。
- [ ] R10.2 `fetch_share_unlock`（event_factors.py:152-156）传 `raise_on_failure=True` + try/except 兜底返 `[]` + 标 data_status/None（区分"源断"vs"无解禁"）。
- [ ] R10.3 测试钉死：①lockup_expiry raise_on_failure=True+源断→raise；②fetch_share_unlock 源断→返 [] + data_status 标（非当合法空）；③默认 False 向后兼容。

### R11 registry + 回归
- [ ] R11.1 registry 加 S131 节标注 11 条闭合 + critic 16 missed areas 登记 follow-up。
- [ ] R11.2 全量 `pytest -m "not live"` 0 回归。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/storm_predictor.py` | R1 _collect_internal_factor 查 gene data_source + StormFactor degraded |
| `backend/risk_models.py` | R2 get_current_sti_phase 返 (phase,status) + merge 含 sti |
| `backend/astock.py` | R3 valuation hithink PS/PCF 失败标 ps_pcf_status |
| `backend/mappers.py` | R3 valuation_from_full_valuation 透 ps_pcf_status |
| `backend/data/sources/eastmoney.py` | R4 concept_blocks + R5 em_zt_topic_pool + R6 market_turnover_rank + R7 sector_fund_flow + R8 industry_comparison + R9 eastmoney_datacenter callers + R10 lockup_expiry raise_on_failure |
| `backend/strategies/event_factors.py` | R10 fetch_share_unlock 传 raise_on_failure + 兜底 |
| `backend/tests/test_s131_*.py` | R1.4/R2.3/R3.3/R4.3/R5.3/R6.2/R7.2/R8.2/R9.2/R10.3 新测 |
| `specs/S111-真实裂缝登记册/registry.md` | R11.1 S131 节 + 16 missed 登记 |

> R4-R9 + R10-eastmoney 部分均触 eastmoney.py 同文件 → 单 agent 顺序改（不可并行）。R1/R2/R3/R10-event_factors 不同文件可并行。R2 + S130 R1 均触 risk_models.py → 合并到同一 agent（S130 R1 _build_risk_factors + S131 R2 sti_phase）。

## 5. 设计方案

**统一范式**：
- em_get 消费者（R4-R10）统一 `raise_on_failure` opt-in（对齐 S119 eastmoney_datacenter/dragon_tiger_board 范式）：默认 False 向后兼容（既有 `[]` mock 测试不破），承重 callers 传 True 让上游 try/except→502/missing 兜底。备选 `get_with_fallback_meta` 包（对齐 _get_realtime_capital_flow）——extreme_market_detector:128 已用此范式包 em_zt_topic_pool，R5 优先复用。
- StormFactor（R1）+ sti_phase（R2）用 `data_status` 传播（对齐 S125 StormPrediction.data_status + S129 trio _meta 范式）。

**critic 16 missed areas 处理**：登记 follow-up（registry S131 节列），**不本 spec 修**——需下轮 scan+对抗 verify 确认（部分可能 actually_honest，如 strategy_score_no_data_status 首轮即被 verify 推翻）。对齐"别陷验证循环"：scan→confirm→fix 闭环，critic missed 侧记 follow-up 不自动 spiral。

**scope 守 11 条**：#1-#10 scan-confirmed + lockup-expiry。critic 16 missed（risk_score/risk_level fallback 呈现 / score_components 无 status / OneDayRisk.last_updated / StormPrediction 最终聚合 / query_quote/query_reports/query_global_stock/skyrocket 等 AI工具 / hithink cache-stale / gstock/hot_money_seats/fund_flow/bids 等 em_get 间接消费者）留下一轮。

## 6. 验收标准

- [ ] A1 R1：gene kline_rebuild → StormFactor degraded → StormPrediction 顶层 degraded
- [ ] A2 R2：sti 源断 → (None,missing)+warning → merge 含 sti → data_status=missing
- [ ] A3 R3：hithink PS/PCF 断 → ps_pcf_status 透传 LLM
- [ ] A4 R4-R10：em_get 消费者源断 → raise/missing（非合法空），向后兼容默认 False
- [ ] A5 全量 `pytest -m "not live"` 0 回归
- [ ] A6 registry S131 节 11 条闭合 + 16 missed 登记

## 7. 合规与工程底线自查

- [x] 不臆造：#1 degraded gene 不当 authoritative ok；#2 sti 断标 missing 非 DIVERGENCE 默认；#3 PS/PCF 断标源非"无估值"；#4-#10 em_get 源断标 raise/missing 非"合法空"
- [x] 判断可复现：scan verify 实锤 + 测试 mock 钉死
- [x] 私有数据：不涉
- [x] em_get 防封：R4-R10 加 raise_on_failure **不改变取数路径**（仍走 em_get 限流/熔断/代理），只在源断时 raise 而非 swallow []（防封安全不变，对齐 S119 已实锤）
- [x] §44：#1 probability 偏差~5.8pt 跨阈值（非胜率数字，§44 参考性）；余均 display/factors 非胜率承重链

## 8. 测试计划

`pytest -m "not live"` + 新 `test_s131_*.py`（R1.4 四测 / R2.3 三测 / R3.3 二测 / R4.3 二测 / R5.3 三测 / R6.2/R7.2/R8.2/R9.2 各一测 / R10.3 三测 ≈ 20 测）。

## 9. 风险与回滚

- **风险**：R4-R10 `raise_on_failure` 若承重 callers 上游无 try/except → 500（须 grep 每个 caller 确认上游兜底；extreme_market_detector:128 已范式）。R1 StormFactor degraded 可能致 StormPrediction 频繁 degraded（诚实化预期，非回归）。R2 sti_phase 签名改 tuple 可能破直调测试（须 grep 调用方）。
- **回滚**：每 R 独立可 revert；raise_on_failure 默认 False 向后兼容；data_status 字段加性兼容。
