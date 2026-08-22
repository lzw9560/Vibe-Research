# 任务拆分 · S044 候选池漏斗数据源补全

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含依赖、改动文件、验收方式、映射 AC。
> 实现顺序：阶段 0（探测）→ 阶段 1-4（4 项数据源，串行）→ 阶段 5-7（过滤/防护/历史）→ 阶段 8（验收）

---

## 阶段 0 · 端点探测（风险前置，spec 风险点）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 0a | 写探测脚本 `_probe_northbound.py`：探测东财个股北向端点候选（push2his hsgt / datacenter RPT_STOCK_HSGT_HOLD），确认端点可用 + 返回结构含个股北向净流入 | — | `backend/_probe_northbound.py`（临时，探测完删） | 脚本输出：可用端点 URL + 第一行返回结构 | A1 |
| 0b | 探测 `push2 clist` 板块资金流端点历史日期参数支持：传历史 date 参数看是否返回历史数据 | — | `backend/_probe_sector_fund_flow.py`（grill 期间已有，补历史参数探测） | 脚本输出：支持/不支持历史参数 | A7 |

---

## 阶段 1 · 北向 fetcher（R1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 1a | `predict/features/fund_flow.py` 新增 `fetch_northbound(code, date) -> float | None`：走 `em_get` 拼探测成功的端点；返回值统一"万元"；取不到返 None | 0a | `backend/predict/features/fund_flow.py` | 单测 mock em_get 返回固定值，确认解析正确 | A1 |
| 1b | `candidate_funnel/sources/fund_flow.py` 调 `fetch_northbound` 填 `northbound` 字段，替换写死 `"北向数据不可得"`；missing 标原因 | 1a | `backend/candidate_funnel/sources/fund_flow.py` | 单测：mock fetch_northbound 返 None → missing["northbound"] 有原因 | A1 |
| 1c | 单测：北向 fetcher + sources 调用全链路（mock em_get） | 1b | `backend/candidate_funnel/tests/test_fund_flow_northbound.py` | pytest -m "not live" 过 | A10 |

---

## 阶段 2 · 板块联动 fetcher（R2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 2a | `predict/features/fund_flow.py` 新增 `fetch_sector_flow(code, date) -> float | None`：走 `push2 clist` 端点取个股所属板块主力净流入（f62）；板块口径（申万 vs 东财概念）实现期定 | 0b | `backend/predict/features/fund_flow.py` | 单测 mock em_get 返回板块资金流数据，确认解析正确 | A2 |
| 2b | `candidate_funnel/sources/catalyst.py` 调 `fetch_sector_flow` 填 `sector_flow`，替换恒 `None`；missing 标原因 | 2a | `backend/candidate_funnel/sources/catalyst.py` | 单测：mock fetch_sector_flow 返 None → missing["sector_flow"] 有原因 | A2 |
| 2c | 单测：板块联动 fetcher + sources 调用全链路（mock em_get） | 2b | `backend/candidate_funnel/tests/test_catalyst_sector_flow.py` | pytest -m "not live" 过 | A10 |

---

## 阶段 3 · 公告类型化（R3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 3a | `candidate_funnel/sources/catalyst.py` 加 `_classify_announcement(ann) -> str`：按 title 关键词分类（预增/重组/回购/其他）；announcement 输出加 `type` 字段 | — | `backend/candidate_funnel/sources/catalyst.py` | 单测：各类型 title 关键词命中正确分类 | A3 |
| 3b | `candidate_funnel/funnel.py` `_filter_r3` 加 `ann_types: list[str] | None` 参数；非空时只保留公告类型在列表里的标的；默认 None 向后兼容 | 3a | `backend/candidate_funnel/funnel.py` | 单测：ann_types=["预增"] → 只保留预增公告标的 | A3 |
| 3c | 单测：公告类型化 + R3 过滤扩展 | 3b | `backend/candidate_funnel/tests/test_funnel_ann_types.py` | pytest -m "not live" 过 | A10 |

---

## 阶段 4 · 龙虎榜游资席位接力频次（R4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 4a | `predict/features/fund_flow.py` 新增 `fetch_dt_hot_money_relay(code, date, look_back=30) -> float | None`：调 `astock.dragon_tiger_board(code, trade_date, look_back)` 取席位明细；聚合游资席位接力频次（出现 >= 2 次的席位净买入合计）；不输出个体席位名（合规） | — | `backend/predict/features/fund_flow.py` | 单测 mock dragon_tiger_board 返回席位明细，确认聚合逻辑正确 | A4 |
| 4b | `candidate_funnel/models.py` `IndicatorSet` 加 `dragon_tiger_hot_money_relay: float | None = None`（向后兼容） | — | `backend/candidate_funnel/models.py` | 单测：默认 None 不破坏现有 IndicatorSet 构造 | A4 |
| 4c | `candidate_funnel/sources/fund_flow.py` 调 `fetch_dt_hot_money_relay` 填新字段；missing 标原因 | 4a,4b | `backend/candidate_funnel/sources/fund_flow.py` | 单测：mock fetch 返 None → missing 有原因 | A4 |
| 4d | `candidate_funnel/diagnosis.py` `build_indicator_set` 拼接 `dragon_tiger_hot_money_relay` | 4c | `backend/candidate_funnel/diagnosis.py` | 单测：fund dict 有值 → IndicatorSet 字段有值 | A4 |
| 4e | 单测：龙虎榜游资频次全链路 | 4d | `backend/candidate_funnel/tests/test_fund_flow_relay.py` | pytest -m "not live" 过 | A10 |

---

## 阶段 5 · 北向进 R2 过滤（R5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 5a | `candidate_funnel/models.py` `BaseThreshold` 加 `northbound_abs_min: float = 0.0`（默认 0 = 有北向数据即保留） | 1b | `backend/candidate_funnel/models.py` | 单测：默认 0.0，ThresholdConfig 构造不破坏 | A5 |
| 5b | `candidate_funnel/funnel.py` `_filter_r2` 加北向绝对值过滤：`if nb is not None and abs(nb) < eff.northbound_abs_min: filter`；missing（nb is None）保留不过滤 | 5a | `backend/candidate_funnel/funnel.py` | 单测：nb=100, threshold=500 → 过滤；nb=None → 保留 | A5 |
| 5c | `candidate_funnel/thresholds.py` 确认 `resolve_thresholds` 传递 `northbound_abs_min`（base 字段自动透传） | 5a | `backend/candidate_funnel/thresholds.py` | 单测：eff.northbound_abs_min == base.northbound_abs_min | A5 |
| 5d | 单测：R2 北向过滤全场景（有值过滤/有值保留/missing 保留） | 5b | `backend/candidate_funnel/tests/test_funnel_r2_northbound.py` | pytest -m "not live" 过 | A5,A10 |

---

## 阶段 6 · 避免未来函数 stage 防护（R6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 6a | `candidate_funnel/funnel.py` `run_funnel` 加 stage 映射（pre_market→s1, auction→s3）；调 source 前，按 stage 过滤 future-stage 数据 | 1b,2b,4c | `backend/candidate_funnel/funnel.py` | 单测：stage=s1 跑时，availability_offset=1 的数据标 missing | A6 |
| 6b | 确认 `predict/features/registry.py` `list_for_stage` 可被 candidate_funnel sources 调用；如需扩展接口（如按 FeatureSpec.name 查 stage）则加 | — | `backend/predict/features/registry.py` | 单测：list_for_stage("s1") 返回不含 s2/s3/s4 特征 | A6 |
| 6c | 各 fetcher 内部检查 availability_offset：回溯 T-1 跑时，availability_offset=1 的数据（龙虎榜/北向）若 date == yesterday 可取，date < yesterday 标 missing | 6a | `backend/predict/features/fund_flow.py` | 单测：date=历史日 → fetch_dt_hot_money_relay 返 None + missing 标注 | A6 |
| 6d | 单测：stage 防护全链路（回溯 T-1 跑 R2，龙虎榜标 missing 保留，不引入未来信息） | 6c | `backend/candidate_funnel/tests/test_funnel_stage_guard.py` | pytest -m "not live" 过 | A6 |

---

## 阶段 7 · 历史取数支持（R7/R8）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 7a | `candidate_funnel/sources/activity.py` 加历史路径 `_fetch_activity_from_kline(codes, date)`：走 `astock.kline(code, offset)` 复算换手/量比/成交额/振幅；当日走原 `tencent_quote` 路径 | — | `backend/candidate_funnel/sources/activity.py` | 单测：mock kline 返回固定 bars，确认复算值正确 | A7 |
| 7b | `candidate_funnel/sources/activity.py` `fetch_activity` 加日期判断分支：`_is_historical_date(date)` 走 kline，否则走 tencent | 7a | `backend/candidate_funnel/sources/activity.py` | 单测：历史 date → 走 kline 路径；当日 → 走 tencent | A7 |
| 7c | `candidate_funnel/sources/catalyst.py` announcements/block_trade 历史路径：limit 拉大 + 按日期本地截断 | — | `backend/candidate_funnel/sources/catalyst.py` | 单测：mock announcements 返回 100 条，按日期截断取正确子集 | A7 |
| 7d | 若 0b 探测板块资金流不支持历史参数：`fetch_sector_flow` 历史日期返 None + missing 标"板块资金流历史不可得" | 0b,2a | `backend/predict/features/fund_flow.py` | 单测：历史 date → 返 None + missing | A7 |
| 7e | 单测：历史取数全链路（activity kline 复算 + 公告截断 + 板块 missing） | 7b,7c,7d | `backend/candidate_funnel/tests/test_sources_historical.py` | pytest -m "not live" 过 | A7,A10 |

---

## 阶段 8 · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| 8a | pytest -m "not live" 全绿（candidate_funnel + predict/features） | 1c,2c,3c,4e,5d,6d,7e | — | 全过 | A10 |
| 8b | live 冒烟：起 uvicorn:8900 → `GET /api/workflow/funnel/layers` 各层数据非 missing → 北向/板块/龙虎榜字段有值 | 8a | — | live 冒烟 | A1,A2,A4 |
| 8c | live 冒烟：`run_funnel("pre_market", "2026-07-01")` 用历史 date 跑，activity 走 kline 复算，北向/板块/龙虎榜按 stage 过滤 | 8b | — | live 冒烟 | A7 |
| 8d | 避免未来函数验证：回溯 T-1 跑 R2，龙虎榜（availability_offset=1）标 missing 保留，不引入未来信息 | 8c | — | live 冒烟确认 missing 标注 | A6 |
| 8e | 合规自查：弱合规下北向进过滤无障碍；输出挂轻量风险提醒；过滤口径标注"未经回测验证" | 8b | — | 代码审查确认 | A9 |
| 8f | 新增东财端点走 `em_get()` 限流确认：`grep -rn "em_get\|eastmoney_get" backend/predict/features/fund_flow.py backend/candidate_funnel/sources/` 无直接 requests | 8a | — | grep 无直接 requests 调用 | A11 |
| 8g | 删探测脚本 `_probe_northbound.py` / `_probe_sector_fund_flow.py`（临时文件不留） | 8f | — | find 无 _probe_ 文件 | — |

---

## 依赖图

```
0a ──→ 1a ──→ 1b ──→ 1c
                │
                ├──→ 5a ──→ 5b ──→ 5d
                │              │
                └──→ 6a ←── 2b,4c
                      │
                      └──→ 6c ──→ 6d

0b ──→ 2a ──→ 2b ──→ 2c
       │
       └──→ 7d

3a ──→ 3b ──→ 3c

4a ──→ 4c ──→ 4d ──→ 4e
4b ──→ 4c

7a ──→ 7b ──→ 7e
7c ──→ 7e
7d ──→ 7e

8a ←── 1c,2c,3c,4e,5d,6d,7e
8b ←── 8a
8c ←── 8b
8d ←── 8c
8e ←── 8b
8f ←── 8a
8g ←── 8f
```

---

## 总计

- 阶段 0：2 条（探测，风险前置）
- 阶段 1-4：12 条（4 项数据源，串行）
- 阶段 5-7：13 条（过滤/防护/历史取数）
- 阶段 8：7 条（集成验收）
- **合计：34 条原子任务**
