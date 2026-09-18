# Spec: S170 — 摘帽中线 event edge

> 状态：草案 | 日期：2026-09-08 | 分级：medium | 关联：S169/S161/S148/multiline-strategy-direction

## 0. 问题/目标

S169 PEAD 短线证否（falsified，A 股预告后 drift 为负）。转摘帽 event edge（撤销风险警示公告后 drift）。摘帽识别最干净（二值关键词"撤销风险警示"无歧义，误识别最低），design events lens 建议先做。

GAP：历史摘帽事件回溯收集（em_get 扫全 A ~25min + cache）。st_play_radar 只当前 ST 白名单，历史要扫全 A 历史公告。

## 1. 需求清单

- [ ] R1 采集 scan_st_removal_history.py：扫全 A 5226 股历史公告（em_get announcements limit=200，0.3s/次限流）→ 过滤 _ZHAIMAO_KEYWORDS（撤销风险警示/摘帽，排除"申请"待批）→ 缓存 st_removal_events.json（{code, notice_date/pub_date, title}）
- [ ] R2 midline_st_removal_run.py：读 cache → build_return_series + run_event_verdict（复用 midline_event_harness）→ 5 horizon verdict 落 Recorder + lineage
- [ ] R3 event 识别：撤销风险警示公告 notice_date（披露日，反前视——非报告期）
- [ ] R4 guards：volume>0 + date adjacency + exit bar 存在（复用 midline_event_harness.build_return_series）
- [ ] R5 edge_type="event" + n_comparisons=5（5 horizons BH K=5 多重比较校正，verifier event 分支已加 p_bonf/p_bh）
- [ ] R6 input_files：传 st_removal_events + kline_cache hash（复现锚点）

## 2. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/tools/scan_st_removal_history.py | 新建：扫全 A 历史公告采集摘帽事件 |
| backend/tools/midline_st_removal_run.py | 新建：复用 midline_event_harness 出 5 horizon verdict |
| specs/S170-摘帽event/spec.md | 本 spec |

## 3. 验收标准

- [ ] A1 采集 25min background → st_removal_events.json（N 摘帽事件，N 预期 50-200/年）
- [ ] A2 midline_st_removal_run 出 5 verdict（5 horizons），落 Recorder + lineage
- [ ] A3 所有 verdict edge_type=="event"，selection_lift is None
- [ ] A4 reproduce 验证 OK（reproduce_verdict 重算不崩，status 一致）
- [ ] A5 pytest -m "not live" --deselect 3 flaky 全绿（无回归）

## 4. 合规与工程底线自查

- [x] 不臆造：em_get 真实公告数据，guards 跳过无效 bar 不假收益
- [x] 私有数据隔离：st_removal_events.json 在 backend/.scratch/（.gitignore）
- [x] em_get 防封：走 em_get 限流/熔断/代理探测（非裸 requests）
- [x] §44 降级参考性建议：验证管道非用户可见推荐

## 5. deferred

- 摘帽子类型（撤销其他风险警示 vs 撤销退市风险警示）分类——YAGNI NOW
- engine path_return 可交易版本——robust_edge 才接
- 重组/PEAD SUE 后续线路
