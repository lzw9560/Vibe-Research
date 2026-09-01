# Spec: S133 — _emotion date-keyed 缓存重构

> 状态：待实现
> 作者：lzw9560  日期：2026-09-01
> 级别：medium（1 文件 2 函数改 + 1 简化，~12 直调方验证不改；涉及数据输出走 spec + 合规自查）
> 关联：S109（§10 留 _emotion date-keyed 重构另立 spec）/ S094（_sentiment date-keyed 范式镜像）/ S128（or-zero 契约）/ S131（market caller wiring）

## 1. 问题 / 目标

S109 §10 留 `_emotion date-keyed 重构`（blast radius ~8 直调方，单独 spec）。understand workflow（2026-09-01）实测核实：

- `backend/market.py:154 def _emotion(date)` 函数体（154-408）**零 _cached/_CACHE 写**——直调 `_emotion(date)` 全程不缓存，每次 fresh em_get。
- `backend/market.py:410 get_short_term_emotion() return _cached("emotion", _emotion)`——扁平 key="emotion" **不带 date**，只此路径缓存，且只存 date=None（auto-locate latest）结果。
- ~12 直调方（pre_market_workflow / scheduled_tasks / routers/workflow / first_board_* / limitup_sti / verification_card / board_ladder / backfill_raw_break_rate）每次裸打 em_get 无去重——backfill 循环多日 + 多条 15:30 task 同日重复打，浪费 + 加封 IP 风险。
- get_short_term_emotion 扁平 "emotion" key 是潜在跨日污染 footgun（若后续有人天真给 _emotion 加扁平 `_cached` 即触发跨日返旧）。

**目标**：镜像 `_sentiment`（market.py:40-47）已落地的 date-keyed 范式，`_emotion` 内置 date-keyed 缓存——12 直调方零改动透明获益（去重 + 降封 IP + 防 footgun）。

## 2. 前提校正（独立判断）

- 任务描述的"跨日污染（调 `_emotion('08-20')` 缓存后再调 `_emotion('08-21')` 返 08-20）"当前是 **LATENT 非 active**——`_emotion` 体零缓存 = 直调方永远 fresh/正确。**无 ACTIVE 数据损坏**。
- 现存实际代价：(1) 12 直调方无去重（浪费 + 封 IP 风险）；(2) 扁平 key footgun。
- 故本 spec 性质 = 底座 Tier-2 清理（去重 + 预防），非修活 bug。置信度中高。

## 3. 需求清单

- **R1 拆 `_emotion`→`_emotion_uncached`**：market.py:154-408 函数体原样改名 `_emotion_uncached(date)`（体不变；内部 `_sentiment(resolved_dash)` 调用照旧——它本就 date-keyed 缓存）。
- **R2 新 `_emotion(date)` 缓存壳**：
  ```python
  def _emotion(date: str | None = None) -> dict:
      return _cached(f"emotion:{date or 'latest'}", lambda: _emotion_uncached(date))
  ```
  默认 `valid=bool`（与 `_sentiment` 一致；空 `{}` 不缓存，非空含 `data_status:"missing"` 的 dict 缓存——同当前 get_short_term_emotion 行为，零语义变化）。
- **R3 `get_short_term_emotion` 简化**：market.py:410-412 `return _emotion()`（`_emotion()` 自带 `emotion:latest` 缓存，删冗余扁平 `_cached("emotion", _emotion)` 双层缓存）。
- **R4 调用方零改动验证**：~12 直调方只验不改（确认行为不变 + 缓存透明）。清单见 §4。
- **R5 全量 gate 绿**：`cd backend && .venv/bin/python -m pytest -m "not live" --deselect tests/test_newsradar* --deselect tests/test_s032*` 0 回归（按 memory deselect newsradar + s032 flaky）。

## 4. 受影响文件

- **改**：`backend/market.py`（R1-R3，1 文件 2 函数改 + 1 简化）。
- **验证不改**（确认行为不变 + 缓存透明）：
  - `backend/pre_market_workflow.py:378`
  - `backend/scheduled_tasks.py:676`
  - `backend/routers/workflow.py:786`（+ `:349` _fetch_market_emotion 间接包装）
  - `backend/tools/first_board_premium_baseline.py:234`
  - `backend/strategies/first_board_filter.py:593, :1416`
  - `backend/strategies/first_board_market_env.py:262, :277`
  - `backend/limitup_sti/service.py:336`
  - `backend/workflow/verification_card.py:340`
  - `backend/candidate_funnel/sources/board_ladder.py:35`
  - `backend/scripts/backfill_raw_break_rate.py:88`
  - `backend/routers/market.py:46`（get_short_term_emotion）
  - `backend/data/mappers.py:184/332/346`（仅 docstring 引用，无需改）

## 5. 验收标准

1. **date-keyed 不污染**：`_emotion("2026-08-20")` 后 `_emotion("2026-08-21")` 同 TTL 内命中不同 key（`emotion:2026-08-20` vs `emotion:2026-08-21`），断言 `astock.em_zt_topic_pool` 各被调一次且 date 参数不同。
2. **同日去重**：`_emotion("2026-08-28")` 5min 内连调两次 → `em_zt_topic_pool` 仅调一次（缓存命中）。
3. **get_short_term_emotion() 行为不变**：返 latest emotion，经 `emotion:latest` key；`test_s008_t10_emotion_router` 绿。
4. **透明性**：`monkeypatch.setattr(market, "_emotion", ...)` 仍可 patch（签名未变）；`_patch_guards` patch `market._sentiment` 仍被 `_emotion_uncached` 内部命中（test_s131 全绿）。
5. **全量 gate 绿**：R5。

## 6. 合规自查（弱合规·工程底线）

- ☑ 不臆造：缓存只 memoize `_emotion` 原返回值，不臆造数据。空 `{}` 不缓存（`valid=bool`）。
- ☑ 私有数据隔离：`_emotion` 是公开市场情绪数据，无私有数据。
- ☑ 防封：`_emotion` 走 em_get 限流（`em_zt_topic_pool` 等）。date-keyed 缓存**降** em_get 重复打（去重），符合防封精神，不违背。
- 备注：`data_status:"missing"` 被缓存 5min（源断恢复后 5min 内仍返 missing）——PRE-EXISTING（当前 get_short_term_emotion 同行为），镜像 _sentiment 一致性优先，保守留 `valid=bool`（不改 retry-on-missing，避免破坏 _sentiment 一致性）。

## 7. 不在本 spec 范围

- **第 2 层口径仲裁**（新浪三表 revenue/net_profit 仲裁）——understand workflow 判盲目强接 = 噪声非信号（口径异构：新浪利润表原始 vs akshare 同花顺 curated，结构性差异系统性触发 >5%），违反 S106「不打扰」原则。真正护栏是东财 datacenter 财务摘要（同口径），但未接 = 新源集成 spec（scope 大），且需先采集 divergence 数据证明是信号。**无数据就接线 = 投机（YAGNI）**，不做。
- `date=None 'emotion:latest'` 短 TTL（交易日边界盘前→盘后新日头 5min 服务昨日）——PRE-EXISTING（当前扁平 "emotion" 同窗口），镜像 _sentiment 同 tradeoff，单独议题 YAGNI。
- 新浪源熔断器——属第 1/5 层（缓存治理/真实裂缝），单列 work-list。
- 缓存统一公共工具抽离——YAGNI（各源自治 + market._cached 范式复用够）。
