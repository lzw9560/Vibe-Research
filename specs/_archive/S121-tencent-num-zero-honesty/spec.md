# Spec: S121 — tencent quote 0 归一化诚实化（AI 出口不喂 PE=0/PB=0）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S118 scan #2 `ai-tencent-num-zero-coercion`（HIGH confirmed_lying, worth_fixing）/ §1.2 不臆造工程底线

## 1. 问题 / 目标

S118 scan 判 `ai-tencent-num-zero-coercion` confirmed_lying：tencent gtimg 对亏损股（负 EPS→PE 未定义）/新股/部分停牌股，pe_ttm/pb/price 等字段为空串/"-"哨兵，`tencent.py:56 num(i)` `return float(vals[i]) if vals[i] else 0.0` 把空/非数值归一成 0.0。经 `mappers.quote_from_tencent` `_numf(0.0)=0.0` 透传 → `Quote(pe_ttm=0.0)` → `query_quote` `model_dump` → chat.py:232 喂 LLM。0.0 是"看着有效的数值"而非 null——LLM（尤弱模型）把 PE=0 当"极度低估"、PB=0 同理、price=0 与 last_close=15.3 自相矛盾。触 §1.2 不臆造工程底线。

目标：0 永不合法字段（price/pe_ttm/pe_static/pb/last_close/open/high/low/market_cap/float_market_cap/limit_up/limit_down）的 0.0 归 None（null 喂 LLM 可辨缺失）；0 合法字段（change_pct/vol_ratio/volume/turnover/amplitude）不动。

## 2. 背景

- `num(i)`（tencent.py:56）仅用于 `_parse_gtimg` 建 raw dict（19 字段 :64-81）；"28 消费者"是 raw dict 消费者（`astock.tencent_quote` callers，可能做算术），非 num() 直调。
- `mappers._numf(v)`（:33）`return v if isinstance(v,(int,float)) else None`——`_numf(0.0)=0.0`（isinstance float→透传），`_numf(None/""/缺失)=None`。num() 的 0.0 归一破坏了 _numf 的诚实范式。
- `mappers.quote_from_tencent`（:49）经 `_numf(raw.get(X))` 投影 raw→Quote；`query_quote`（stock_tools.py:30）`model_dump(mode="json")` 喂 LLM。
- Quote 字段全 `float | None = None`（models/quote.py:38-51）——0.0→None 兼容（_numf 缺失返 None 既有范式）。

## 3. 需求清单

- [ ] R1 `mappers.quote_from_tencent` 对 0 永不合法字段把 `_numf(raw.get(X))` → `_numf(raw.get(X)) or None`（0.0 falsy→None，真值不变）：price / pe_ttm / pb / pe_static / last_close / open / high / low / limit_up_price / limit_down_price（10 直接）+ mcap / float_mcap（2 派生，`mcap = _numf(...) or None` → market_cap=None）。
- [ ] R2 0 合法字段不动：change_pct / change_amount / volume / turnover（amount_wan）/ turnover_rate / amplitude / vol_ratio（0 = 平盘/停牌/无量，合法）。
- [ ] R3 测试钉死：①亏损股 pe_ttm 空→num()=0.0→Quote.pe_ttm=None（非 0.0）；②正常股 pe_ttm=19.92→Quote.pe_ttm=19.92（真值不变）；③price=0.0+last_close=15.3 矛盾→两者均 None；④change_pct=0.0→Quote.change_pct=0.0（0 合法保留）；⑤market_cap=0.0→None。
- [ ] R4 全量 `pytest -m "not live" --deselect` newsradar/s032/spec_consistency 0 回归。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/mappers.py` | quote_from_tencent 12 个 0 永不合法字段 `_numf(...) or None` |
| `backend/tests/test_s008_t13e_misc.py` | R3 五测试钉死（或加到既有 quote_from_tencent 测试旁） |

## 5. 设计方案

**范围修（quote_from_tencent 层）而非根因修（num() 返 None）**：num()→None 会破 raw dict 28 消费者算术（`None * x` TypeError），blast radius 大且多数未 confirmed_lying。范围修只动 Quote 投影层，raw dict 不变（28 消费者零影响，YAGNI——其诚实性未扫留 scan）。`_numf(0.0) or None`=None（0.0 falsy）、`_numf(19.92) or None`=19.92、`_numf(None) or None`=None——三态正确。Quote 字段全 Optional 兼容。

备选根因修（num 返 None）否决（28 消费者 blast radius）。备选加 data_status 字段否决（Quote 是值对象非状态载体，0→None 已可辨缺失）。备选只在 num() 改返 None 且只对 0 永不合法字段——等价于范围修但散在 num() 内 19 处判断，不如投影层集中，否决。

## 6. 验收标准

- [ ] A1 亏损股 pe_ttm/pb 空 → Quote.pe_ttm=None / pb=None（非 0.0 喂 LLM）
- [ ] A2 正常股真值不变（pe_ttm=19.92 → 19.92）
- [ ] A3 price=0 + last_close=15 矛盾 → price=None / last_close=None（非 0.0）
- [ ] A4 change_pct=0 / volume=0 → 保留 0.0（0 合法）
- [ ] A5 market_cap=0 → None
- [ ] A6 全量 pytest 0 回归

## 7. 合规与工程底线自查

- [x] 研判/推荐：0→None 让 LLM 见 null 可辨缺失（不臆造 PE=0），系统能力；无新方向建议
- [x] 判断可复现：纯代码逻辑，测试钉死；不涉财务验算
- [x] 涨停四池/连板：不涉
- [x] 私有数据：不涉
- [x] em_get 防封：不涉（tencent gtimg 非 em_get）

## 8. 测试计划

`pytest -m "not live"` + R3 五测试。`--deselect` 既有 flaky（newsradar/s032/spec_consistency）。

## 9. 风险与回滚

- **风险**：raw dict 消费者（非 Quote 路径）仍读 0.0——未 confirmed，留 scan（YAGNI）。Quote 下游若硬编码 0.0 当有效→现 None 可能需调，但 Quote 本就支持 None（_numf 缺失返 None 既有，下游已适配 None）。
- **回滚**：12 处 `or None` 删掉即恢复 0.0。
