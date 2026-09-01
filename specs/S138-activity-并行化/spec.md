# Spec: S138 — activity 采集并行化（per-code kline，mirror fund_flow 范式）

> 状态：草案(2026-09-01)
> 作者：lzw9560  日期：2026-09-01
> 级别：medium（2 路径 per-code 重构 + 测试）
> 关联：C2 打点（activity 7.62s，c2-cold-cache-timing-2026-09-01）/ S137（catalyst 并行化范式）/ mootdx kline 并行 80x 实测

## 1. 问题 / 目标

C2 打点 R2 `activity.fetch_activity` **7.62s**。源：两路径（当日 `:176` / 历史日 `:83`）per code `astock.kline(c, 4, 10)` **串行**（`:235` / `:120`），80 股各一次 mootdx kline。

mootdx kline 并发性实测（`/tmp/kline_concurrency_probe.py`）：5 股串行 8.03s → 并行 0.10s = **80x 加速**。`Quotes.factory` 不缓存单 client，每股独立 TCP 连接，无共享锁——并行真并发有效。

目标：两路径批量 `tencent_quote` 保留（快），per code（kline + 派生 + entry）抽 `_fetch_single` + `ThreadPoolExecutor(max_workers=5)`。shape 不变（下游不破）。

## 2. 背景

- `activity.fetch_activity`（当日路径 `:176-266`）：批次 50 `tencent_quote(batch)` 批量 + per code（`quote_from_tencent` + entry + `astock.kline` + `_compute_kline_derived` + missing）串行。
- `_fetch_activity_from_kline`（历史日 `:83-173`）：批量 `tencent_quote(codes)` + per code（`quote_from_tencent` + `astock.kline` + 找 date bar + 派生 + entry）串行。
- mootdx kline 走 `data/sources/mootdx_src.py:32`（`Quotes.factory` 每次新连接，非 em_get 不限流 IP，并行安全）。
- 共享：`_f` / `_is_historical_date` / `_compute_kline_derived` 不动。

## 3. 需求清单

- [ ] **R1**：当日路径抽 `_fetch_single_realtime(c, raw, as_of) -> tuple[str, dict]`（per code：quote_from_tencent + entry + kline + _compute_kline_derived + missing，mirror fund_flow._fetch_single 线程安全无共享）。
- [ ] **R2**：历史日路径抽 `_fetch_single_historical(c, today_quote, target) -> tuple[str, dict]`（per code：quote_from_tencent + kline + 找 bar + 派生 + entry）。
- [ ] **R3**：两路径批量 `tencent_quote` 保留（快，不改），per code 改 `ThreadPoolExecutor(max_workers=min(5, len))` + futures 收集，shape 不变。
- [ ] **R4**：codes 空 → 返 `{}`。
- [ ] **R5**：gate 绿（现有 `test_s085_pre_market_activity` / `test_s004_funnel_perf` activity 测不破——shape 不变）+ 加并行测（多股 shape 同）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/sources/activity.py` | 抽 2 `_fetch_single` + 两路径 per-code 并行化（R1/R2/R3/R4） |
| `backend/tests/test_s008_t13e_misc.py` 或 `test_s085_pre_market_activity.py` | 加并行测（R5） |

## 5. 设计

mirror `fund_flow.fetch_fund_flow`（`fund_flow.py:86-99`）+ `_fetch_single`（`:12-83`）范式：
- `_fetch_single_*` 线程安全（entry dict 局部，无共享；kline/派生 per call）
- 批量 `tencent_quote` 保留（前置，快，per batch 一次）
- `ThreadPoolExecutor(max_workers=min(5, len(codes)))`——mootdx 不限流可高，取 5 同 fund_flow 一致 + 防过载
- codes 空 → 早返 `{}`
- shape 不变（下游 candidate_funnel/funnel 依赖 entry shape）

**为何批量 tencent 保留不并行**：tencent_quote(batch) 本就是批量一次取多股（快），并行化它无意义（非 per-stock 网络）。瓶颈在 per code kline（mootdx 每次 TCP 连接），那部分并行。

## 6. 验收

- [ ] A1：`fetch_activity(["600519","000001","002415"], date)` 返 3 key shape 同原串行。
- [ ] A2：现有 activity 测全绿（shape 不变）。
- [ ] A3：`codes=[]` → `{}`。
- [ ] A4：gate 绿。

## 7. 合规自查

- [x] 纯工程（采集并行化），无研判输出。N/A。
- [x] 判断可复现：shape 不变，可复现。无财务计算。
- [x] 私有数据隔离：activity 是公开行情，无私有数据。
- [x] 东财 em_get：activity kline 走 mootdx（非 em_get），tencent_quote 走 tencent（非 em_get）——不涉东财防封。并行 max_workers=5 同 fund_flow。

## 8. 测试

追加：`fetch_activity` 多股（3）mock astock.tencent_quote/kline → 返 3 key shape 同；`codes=[]`→`{}`。现有 `test_s085_pre_market_activity` 不改（shape 不变）。

## 9. 风险

- R-fail1（线程安全）：`_fetch_single_*` entry 局部 + kline per call 独立连接 → 线程安全（mootdx 80x 实测并行无错）。
- R-fail2（shape 破）：futures 收集保序 + entry shape 不变。不破。
- 回滚：纯重构（串行→并行 + `_fetch_single` 抽取），shape 不变，revert 即回滚。
