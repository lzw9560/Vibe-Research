# Spec: S139 — sector_phase 候选卡纯 LABEL 接线（s066 task 039 闭合）

> 状态：草案(2026-09-01)
> 作者：lzw9560  日期：2026-09-01
> 级别：small（DiagnosisCard 加字段 + build_diagnosis_card 接线 + 测试）
> 关联：s066 task 039（`specs/archive/m3-strategy/S066-.../tasks.md:69` + `spec.md:377`：§5.4 Q2 修饰方向被驳→降级纯 LABEL）

## 1. 问题 / 目标

s066 step3 task 039 残留：`sector_phase`（板块周期阶段：启动/发酵/高潮/退潮）标候选卡**纯 LABEL 接线**未做。s066 spec §5.4 Q2 验证（`sector_phase_regression.py` 25 天）修饰方向被驳——退潮 62.7% > 启动 55.7%，与 §5.4 修饰方向相反 → 修饰**不接策略分**，降级纯 LABEL（用户自判，不改策略分/排序）。策略分接线等 60 天回归（同 §116，~2026-09-20）。

目标：DiagnosisCard 加 `sector_phase` 字段 + build_diagnosis_card 调 `analyze_sector_phase(trade_date, pool_item.hybk)` 标注。纯 display，不改策略分/排序/capped。无 hybk/失败 → None 降级不臆造。

## 2. 背景

- `analyze_sector_phase(date, industry)`（`strategies/sector_cycle.py:87`）返 `SectorPhase`（phase/stay_days/phase_note/count_today/count_avg_3d/momentum）。无缓存，每次 5+ sqlite DB 查（本地 ms 级，88 股 ~1-2s，非悬崖）。
- `DiagnosisCard`（`models.py:142`）有 `pool_item`（涨停池 dict，含 `hybk` 行业，:162）。
- `build_diagnosis_card`（`diagnosis.py:239`）有 `trade_date` + `pool_item` 参数。返回 :308 DiagnosisCard。
- s066 §5.4 Q2 决议：修饰不接策略分（方向被驳），60 天后回归再议。

## 3. 需求清单

- [ ] **R1**：`DiagnosisCard` 加 `sector_phase: Optional[dict] = None`（纯 LABEL，shape `{industry, phase, stay_days, phase_note, count_today, count_avg_3d, momentum}`）。
- [ ] **R2**：`build_diagnosis_card` 调 `analyze_sector_phase(trade_date, pool_item.get("hybk"))`，结果 dump dict 标 `sector_phase`。无 trade_date/无 pool_item/无 hybk/sector_cycle 失败 → None 降级不臆造。
- [ ] **R3**：纯 display——`sector_phase` 不参与 capped/胜率/结算/排序（仅选股池呈现）。
- [ ] **R4**：gate 绿 + 加测（有 hybk→标注 / 无 pool_item→None / 失败→None）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/models.py` | DiagnosisCard 加 `sector_phase` 字段（R1） |
| `backend/candidate_funnel/diagnosis.py` | build_diagnosis_card 接 analyze_sector_phase + 返回加 sector_phase（R2） |
| `backend/tests/test_s008_t13e_misc.py` 或新 | 加 sector_phase 接线测（R4） |

## 5. 设计

纯 LABEL 范式（mirror seat_detail opt-in，但 sector_phase 无 opt-in——bulk/单股都标，sector_cycle 本地 DB 快）：
- `sector_phase: Optional[dict]`——非 pydantic 模型（避免跨模块 import 耦合，同 gene_score/pool_item dict 范式）
- `build_diagnosis_card` 内 try/except 包 analyze_sector_phase（失败 None 降级）
- 无 hybk（非涨停股 pool_item=None 或无 hybk）→ sector_phase=None（正确，sector_phase 仅对有行业标注的涨停候选有意义）
- 不参与 capped/胜率/结算（纯呈现）

## 6. 验收

- [ ] A1：build_diagnosis_card(trade_date=X, pool_item={hybk:"电力"}) → sector_phase 含 phase/stay_days。
- [ ] A2：pool_item=None → sector_phase=None。
- [ ] A3：sector_cycle 失败（mock raise）→ sector_phase=None（不臆造）。
- [ ] A4：gate 绿。

## 7. 合规自查

- [x] 纯 display 标注，无研判/买卖时机输出。§5.4 Q2 决议纯 LABEL（不接策略分）。
- [x] 判断可复现：sector_phase 由 analyze_sector_phase（DB 查询）确定性推导。无财务计算。
- [x] 私有数据隔离：sector_cycle 查 gene_scores（公开涨停数据），无私有数据。
- [x] 东财 em_get：sector_cycle 走本地 sqlite（非 em_get），不涉防封。

## 8. 测试

追加：build_diagnosis_card mock analyze_sector_phase → sector_phase 标注（A1）；pool_item=None → None（A2）；mock raise → None（A3）。

## 9. 风险

- R-fail1（性能）：sector_cycle 无缓存，88 股 × 5 DB 查 ~1-2s（本地 sqlite ms 级，非悬崖）。若实测慢，加 (date,industry) 缓存 follow-up。
- R-fail2（shape 破）：sector_phase 默认 None，加法不破既有消费者。
- 回滚：纯加法（1 字段 + 接线 + 测），revert 即回滚。
