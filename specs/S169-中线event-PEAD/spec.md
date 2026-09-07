# Spec: S169 — PEAD 中线 event edge 验证（选股层死路转 event edge 第一类）

> 状态：草案 | 日期：2026-09-08 | 分级：medium（2 新文件 + 1 注释 + 测试）issue 层单轮 review | 关联：S161/S168/S159/multiline-strategy-direction

## 1. 问题/目标

S168 证否选股层 12 harness（全 falsified/exploratory/underpowered，跟 §44 prior gene_score 0.942x 一致——选股层死路）。转中线 event edge：不问"能不能挑出更好的股"（selection），问"事件发生后买入持有 N 天扣成本还赚不赚"（event）。

第一类选 PEAD（业绩预告 drift）——数据全量已缓存（forecast_reports.json 3.2MB 4972 事件 130 天 + kline_cache 160MB 5226 股），零收集工作，写完即跑出 15 verdict。

**现有 pead_event_study.py 有方法论错误（category mismatch）**：用 selection 方法（day_paired lift + permutation）测 event drift——问"预告股是否跑赢全市场"（lift ~1.0 = no_edge），而非"预告后 drift 均值扣成本后是否 >0"（实际全负，应为 falsified）。selection 框架掩盖真实结论。本 spec 用 edge_type="event"（day-clustered t-test mean>0）修正。

## 2. 背景

- §44v1 category mismatch 教训：event edge（单样本 mean>0）vs selection edge（双样本 lift）。verifier.py:328-394 event 分支走 day_clustered_t_test，不走 lift/permutation。
- 现有 pead_event_study.py：collect_forecast_reports()（line 67，baostock query_forecast_report，已缓存 forecast_reports.json）**复用**；分析层 four_state/day_paired_lift_fast/permutation_null_fast（selection 方法）**废弃**。
- matrix.json 实测（selection 框架）：good_news D+1 mean=-1.13% D+5=-2.69%（全负），但标 no_edge（lift~1.0）。event 框架应标 falsified（mean<0）。
- 预期 verdict：day-clustered t-test 下所有 arm×horizon 大概率 falsified（pooled mean 全负，day-clustered 不翻正）。A 股预告后 drift 为负（与美国文献正漂移相反，散户主导+T+1+涨跌停闸门特征）。

## 3. 需求清单

- [ ] R1 新建 backend/tools/midline_event_harness.py——共享 return series builder + verdict runner，后续摘帽/重组复用
- [ ] R2 新建 backend/tools/midline_pead_run.py——PEAD 专用：import collect_forecast_reports → good/bad/all 分类 → 多 horizon × wire_verdict
- [ ] R3 return series = D+1 open → D+N close，decimal 制（exit_close/entry_open - 1.0 - 0.0070），不乘 100（旧 pead 用百分比，新 harness 用小数匹配 wire_verdict）
- [ ] R4 guards：entry bar volume>0（零量=停牌跳过）、date adjacency（D+1 bar 日期==日历下一交易日）、T+N exit bar 存在性（不够长跳过）
- [ ] R5 horizons=[1,5,10,15,20]——N=1 隔夜基线 + N=5/10/15/20 中线 1-4 周，先跑窗口 sanity 定位 drift 在哪
- [ ] R6 edge_type="event"，绝不传 survivors_by_day/universe_by_day（避免 category mismatch）
- [ ] R7 wire_verdict 落 Recorder + lineage（复现锚点 frozen_commit + data_snapshot_id）
- [ ] R8 R6 gate 内建不 override（days_robust<60 → underpowered）
- [ ] R9 materiality floor 内建不 override（effective_floor=max(0.003, 0.0070*0.5)=0.0035）
- [ ] R10 pead_event_study.py 分析层（four_state+day_paired_lift_fast+permutation_null_fast）标 deprecated 注释，不删不改（collect 层保留复用）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/tools/midline_event_harness.py | **新建**。共享 build_return_series(events, kline_cache, calendar, entry_offset, exit_offset, cost_pct) → (returns, dates, guard_stats) + run_event_verdict(line_id, events, cache, calendar, horizon, ...) → Verdict。~120 行。|
| backend/tools/midline_pead_run.py | **新建**。import collect_forecast_reports from pead_event_study → classify good/bad/all → per arm × per horizon 调 run_event_verdict。~80 行。|
| backend/tools/pead_event_study.py | **注释标记**。four_state/day_paired_lift_fast/permutation_null_fast 上方加 `# DEPRECATED: category mismatch (selection method on event edge). See midline_pead_run.py for correct event verdict.` 不删不改。|

## 5. 设计方案

### 5.1 共享 harness（midline_event_harness.py）

```python
def build_return_series(events, kline_cache, calendar, entry_offset, exit_offset, cost_pct) -> (returns, dates, guard_stats):
    """return = exit_close / entry_open - 1.0 - cost_pct (decimal)
    date = event pub_date (day-clustering key)
    Guards: volume>0 at entry + date adjacency + exit bar exists"""

def run_event_verdict(line_id, events, kline_cache, calendar, horizon, cost, frozen_commit, params) -> Verdict:
    returns, dates, guards = build_return_series(events, kline_cache, calendar, 1, horizon, cost)
    return wire_verdict(line_id=line_id, returns=returns, edge_type="event", dates=dates,
        frozen_commit=frozen_commit, round_trip_cost=cost, n_comparisons=K, script=__file__,
        params={"horizon": horizon, "n_events": len(events), "n_valid": len(returns), **guards, **params})
```

### 5.2 PEAD run（midline_pead_run.py）

import collect_forecast_reports + GOOD_NEWS_TYPES/BAD_NEWS_TYPES from pead_event_study → 3 arms (all/good_news/bad_news) × 5 horizons [1,5,10,15,20] = 15 verdict。

### 5.3 为什么直接算 return 不走 engine path_return

跟 gap run 一致：event drift 是"持有到期"测度，不需 stop/take/max_hold 路径模拟。robust_edge 才接 engine path_return 加 stop/take 做可交易版本（progressive refinement，没信号不上重方法论）。

### 5.4 为什么不修 pead_event_study.py 而新建

collect_forecast_reports() + kline cache 读取复用，但分析层（four_state+lift+permutation）是 selection 方法，跟 event edge 不兼容。新建 midline_pead_run.py import collect 层、废弃分析层，比改现有文件干净（不破坏现有 matrix.json 产出，可对比新旧 verdict）。

## 6. 验收标准

- [ ] A1 midline_event_harness.py build_return_series 输出 decimal 制 returns（非百分比），与 gap run 一致
- [ ] A2 midline_pead_run.py 跑完产出 15 verdict（3 arms × 5 horizons），全部落 Recorder + lineage
- [ ] A3 所有 verdict edge_type=="event"，selection_lift is None（不跑 lift）
- [ ] A4 good_news D+1 verdict day_mean 为负（与 matrix.json pooled mean -1.13% 方向一致），event_status="event_falsified"（day_mean<=0）
- [ ] A5 days_robust≥60 的 arm（good_news 120 天 / all 130 天）不受 R6 gate 阻塞，能出正式 verdict（非 underpowered）
- [ ] A6 pead_event_study.py 分析层函数有 deprecated 注释，collect_forecast_reports 无改动
- [ ] A7 pytest -m "not live" --deselect 3 flaky 全绿（无回归）

## 7. 合规与工程底线自查

- [x] 不臆造：build_return_series 的 guards（volume/date adjacency/exit existence）跳过无效 bar 不产生假收益；frozen_commit + data_snapshot_id 锁定复现
- [x] 私有数据隔离：kline_cache + forecast_cache 在 .vibe-research/ + backend/.scratch/（.gitignore）
- [x] em_get 防封：本 spec 不调东财（PEAD 数据来自 baostock，免防封）
- [x] §44 降级参考性建议：验证管道非用户可见推荐

## 8. 测试计划

- 离线：pytest -m "not live" + 3 deselect（s040/s032/newsradar flaky，非本 spec）
- 手动：cd backend && .venv/bin/python -m tools.midline_pead_run → 15 verdict 摘要
- 验证：对比新 verdict（event edge）与旧 matrix.json（selection edge）——同数据 event 框架标 falsified 的 arm×horizon，selection 框架标 no_edge。证明 category mismatch 修正。

## 9. 风险与回滚

- 风险：PEAD 全负可能是数据窗口偏差（2025-12-25~2026-09-04 下跌市）。但 event edge 测"事件后净收益是否>0"不是"是否跑赢市场"——下跌市中 event drift 为负本身是有效信息（不该在下跌市买预告股）。
- 回滚：两新文件不影响现有代码（pead_event_study.py 只加注释不改逻辑），删掉两新文件即回滚。

## 10. deferred

- 超预期判定（SUE）：需 analyst consensus（akshare profit_forecast，稀疏+非 PIT 有前视风险）。本 spec 先用 ftype 方向版（公司自评预增/预减）。deferred 到数据覆盖够+PIT 对齐方案确定。
- engine path_return 可交易版本：simple return 出 robust_edge 才接。本例预期 falsified，deferred。
- 摘帽 run（midline_st_removal_run.py）：需历史摘帽公告批量采集（em_get 全 A 扫 ~25min + cache + pit_store pin）。PEAD 跑完验证 harness 正确后做。
- 重组 run（midline_restructuring_run.py）：需关键词增强（子类型+初始/进展过滤）+ 批量采集 + 停牌 guard。同摘帽后做。
- baostock_src.py 批量封装：pead collect_forecast_reports 内联 baostock 调用，未来摘帽/重组需 baostock 业绩快报/财报数据时可提取。YAGNI NOW。
