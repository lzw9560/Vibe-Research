# S208 — post-首板 relay + 板块补涨 candidate scanner（T10 auto-source）

> 状态：spec（2026-09-16，SDD workflow `w0ube2uvg` + 专家 panel `w1iu01jnl` 综合，专家 reframe）
> 关联：S204 T10、early_admission.py、tracking_pool_repo.py、[[s207-non-manifesting-grill-verdict]]（证否教训）

## 1. 问题
T10 `_execute_early_admission_scan` 的 auto-source 接 funnel cache 是错源（funnel final_candidates 是 post-涨停 lbc 2-3 → 0 admits）。须建 scanner 查正确离线源（zt_history + sector_cycle + gene_scores，零 em_get）产 early_admission candidate shape。

## 2. 专家 reframe（2026-09-16，w1iu01jnl）
原"pre-涨停 scanner"框 3 信号里 2 个死/证否：
- **high_gene >=80 死信号**（max total_score 50.46，0 picks ever）+ gene_score selection edge 已证否（gap_window 0.942x）→ **DROP**
- **relay_seed (lbc==1) standalone 重测 lianban_lift 已 null**（0.986x）→ 若留只复合 + reframe post-首板
- sector_startup（非涨停在 ≥2 涨停板块）真 pre-涨停，未测，sound——v2（须 code_industry 全会员）
- **真 edge 问题在 T10 executor entry/exit 规则**（止盈止损从波动股提 trade edge），非 scanner 信号——本 scanner 是 **PLUMBING**（修错源 + 喂 manual trigger），edge 验证 defer + executor 规则设计并行。

## 3. 目标
建 `backend/pre_limitup_scanner.py`：`scan_pre_limitup(run_date, previous_trade_day) -> list[dict]`，从 zt_history T-1（lbc==1 首板）+ sector_cycle（板块 zt count）聚候选，**drop high_gene**，zero em_get。喂 `_execute_early_admission_scan` 替代 funnel 错源。

## 4. 需求
- R1: `scan_pre_limitup(run_date, previous_trade_day=None) -> list[dict]`，每 dict 5 keys `{code, sector_rank:None, zt_count_today:int, lbc:1, high_gene:0}`（high_gene 恒 0 dropped）。
- R2: 候选源：zt_history T-1 `WHERE lbc==1 AND is_final=1`（首板，post-首板 pre-二板）；sector zt_count via `sector_cycle._get_zt_count_by_date_industry(T-1, hybk)`。
- R3: **drop high_gene**（死阈值 >=80 vs max 50.46 + 证否 0.942x，不扫 cutoff 反 data dredging）。
- R4: pit guard T-1 only（不取 T 日盘中）。
- R5: zero em_get（zt_history.db + gene_scores.db 离线）。
- R6: lbc>=2 连板排除（非 pre-二板）。

## 5. 受影响文件
- `backend/pre_limitup_scanner.py`（新建，~80 LOC）
- `backend/scheduler/executors/__init__.py`（`_execute_early_admission_scan` 改用 scanner，drop funnel 错源 + high_gene adapter）
- `backend/tests/test_pre_limitup_scanner.py`（新建，TDD）

## 6. 验收
- scan_pre_limitup 返回 lbc==1 首板候选（非 lbc>=2 连板）
- high_gene 恒 0（dropped）
- pit guard：只取 T-1，不取 T 日
- zero em_get（离线源）
- 替代 funnel 错源后，manual trigger 产非 0 admits（zt_history T-1 有 lbc==1 时）

## 7. defer（v2 + 并行）
- sector_startup 真 pre-涨停（非涨停在活跃板块）须 code_industry 全会员——v2
- §44 edge 验证——须 backfill ≥120 天
- **executor entry/exit 规则设计**（真 edge 问题，quant-researcher）——并行 task
