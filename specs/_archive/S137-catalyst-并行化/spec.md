# Spec: S137 — catalyst 采集并行化（mirror fund_flow 范式）

> 状态：草案(2026-09-01)
> 作者：lzw9560  日期：2026-09-01
> 级别：small（1 source 文件 + 测试，mirror fund_flow 范式）
> 关联：C2 打点（c2-cold-cache-timing-2026-09-01，catalyst 16s 单次是 R3 瓶颈）/ fund_flow.fetch_fund_flow（max_workers=5 范式）/ S004 R3

## 1. 问题 / 目标

C2 打点定位 R3 `catalyst.fetch_catalyst` **16.04s 单次**，占 run_funnel 46.8s 的 34%。源：`for c in codes` 串行循环（`catalyst.py:39`），88 股 × 3 网络/股（announcements / concept_blocks / fetch_sector_flow）= 264 次串行。同项目 R2 `fund_flow.fetch_fund_flow` 已并行化（max_workers=5），catalyst 仍串行——**范式不一致**。

目标：mirror fund_flow 范式，抽 `_fetch_single` + `ThreadPoolExecutor(max_workers=5)` 并行化。16s → ~3.2s（88/5 × 3 网络 × ~60ms）。shape 不变（下游不破）。

## 2. 背景

- `fund_flow.fetch_fund_flow`（`fund_flow.py:86-99`）：`ThreadPoolExecutor(max_workers=min(5,len))` + `_fetch_single` 抽取，线程安全无共享。docstring 自陈"原 36 只串行 186s → 并行后 ~37s"。
- `catalyst.fetch_catalyst`（`catalyst.py:32-67`）：串行 `for c in codes` + per-code 3 网络，无并行。
- C2 打点：catalyst 16.04s（1 次，串行），fund_flow._fetch_single 25.82s wall（80 次，5 并发后整体 fetch_fund_flow 5.85s）——证明并行范式对同类 per-code 多网络取数有效。

## 3. 需求清单

- [ ] **R1**：抽 `_fetch_single(c, as_of) -> tuple[str, dict]`（per-code 3 网络 + missing 标注，mirror fund_flow._fetch_single 线程安全无共享）。
- [ ] **R2**：`fetch_catalyst` 改 `ThreadPoolExecutor(max_workers=min(5, len(codes)))` + futures 收集，shape 不变（`{code: entry}`）。
- [ ] **R3**：codes 空 → 返 `{}`（不启 executor）。
- [ ] **R4**：gate 绿（现有 `test_s008_t13e_misc::test_catalyst_via_model` / `test_s131` catalyst 测不破——shape 不变）+ 加并行测（多股 shape 同串行）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/sources/catalyst.py` | 抽 `_fetch_single` + `fetch_catalyst` 并行化（R1/R2/R3） |
| `backend/tests/test_s008_t13e_misc.py` | 追加并行测（R4） |

## 5. 设计方案

mirror `fund_flow.fetch_fund_flow`（`fund_flow.py:86-99`）+ `_fetch_single`（`:12-83`）范式：
- `_fetch_single` 线程安全（entry dict 局部，无共享状态；3 网络 try/except 标 missing 不阻断）
- `ThreadPoolExecutor(max_workers=min(5, len(codes)))`——codes<5 时降 workers，单股 max_workers=1 不破现有测
- codes 空 → 早返 `{}`（不启 executor）
- shape 不变（下游 `candidate_funnel/funnel` 依赖 `{code: {announcements, concepts, sector_flow, missing}}`）

## 6. 验收标准

- [ ] A1：`fetch_catalyst(["600519","000001","002415"], date)` 返 3 key，每 key shape 同原串行版（含 announcements/concepts/sector_flow/missing）。
- [ ] A2：现有 `test_catalyst_via_model` / `test_s131` catalyst 测全绿（shape 不变）。
- [ ] A3：`codes=[]` → 返 `{}`。
- [ ] A4：gate 绿。

## 7. 合规与工程底线自查

- [x] **研判/推荐/买卖时机**：纯工程（数据源采集并行化），无研判输出。N/A。
- [x] **判断可复现**：并行不改取数逻辑，shape 不变，可复现。无财务计算，无需 financial_rigor。
- [x] **用户私有数据隔离**：catalyst 是公开公告/板块/资金流，无私有数据。
- [x] **东财 em_get**：catalyst 调 `astock.announcements/concept_blocks`（走 em_get 限流，S131 `raise_on_failure` 诚实标 missing 已有）；并行 max_workers=5 同 fund_flow 已验证，不增防封风险。

**工程底线备注**：§1.2 三条全过。并行不臆造（失败标 missing）；无私有数据；防封（max_workers=5 同 fund_flow 已验证不增限流风险）。

## 8. 测试计划

追加 `test_s008_t13e_misc.py`：
1. `test_catalyst_parallel_multi_codes`：3 股 mock astock.announcements/concept_blocks/fetch_sector_flow → 返 3 key shape 同（A1）。
2. `test_catalyst_empty_codes`：`codes=[]` → `{}`（A3）。

现有 `test_catalyst_via_model` / `test_s131` 不改（shape 不变，单股 max_workers=1）。

## 9. 风险与回滚

- **R-fail1（线程安全）**：`_fetch_single` entry 局部 dict 无共享 → 线程安全（mirror fund_flow 已验证）。
- **R-fail2（shape 破）**：futures 顺序收集，`out[c]=entry` 保序；shape 不变。不破。
- **回滚**：纯重构（串行→并行 + `_fetch_single` 抽取），shape 不变，revert 即回滚。
