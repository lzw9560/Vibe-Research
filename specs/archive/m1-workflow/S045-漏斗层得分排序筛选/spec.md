# Spec: S045 — 漏斗层得分显示 + 得分排序 + 多选筛选

> 状态：已实现（2026-08-10）——R1-R6 完成：后端 R1/R2/R3 passed 补 gene_score + R3 matched_triggers；前端 FunnelLayerCard 得分显示 + 降序排序（可切回原序）+ 战法/R3 触发类型多选筛选（"或"逻辑）。验证：后端 7 新测试 + candidate_funnel 145 过 + 前端 6 新测试 + 全前端 219 过 + tsc green
> 级别：**medium**（候选池漏斗后端 passed 补分数 + 公共 FunnelLayerCard 前端交互增强；无新 DB/新端点）
> 关联：`backend/candidate_funnel/funnel.py`（R1/R2/R3 passed）、`frontend/src/components/ui/FunnelLayerCard.tsx`（公共层卡）、`frontend/src/lib/candidates.ts`（PassedItem）、`../S044-候选池漏斗数据源补全/spec.md`

## 1. 问题 / 目标
漏斗各层（候选池 R1/R2/R3、因子 LS-1/2/3）通过候选当前只显示 name+code：**无得分、无排序、无筛选**。用户要：①每层得分明确显示；②每层按得分排序；③加筛选功能，筛选条件可多选。

## 2. 需求清单
- [ ] R1 后端：候选池 R1/R2/R3 `passed` 每项补 `gene_score`（源自 `fetch_genes` 的 gene_score；R2/R3 候选均源自 genes，可得）。
- [ ] R2 后端：R3 `passed` 每项补 `matched_triggers: list[str]`（竞价异动 / 公告催化 / 概念联动，由 `_filter_r3` 的 has_auction/announcements/concepts 派生）。
- [ ] R3 前端 `FunnelLayerCard`：passed 每行显示得分（`gene_score ?? confidence_value ?? suggested_pct`，按层语义）。
- [ ] R4 前端：passed 按得分**降序排序**（默认开，可切换回原序）。
- [ ] R5 前端：**多选筛选**——该层候选有 `best_strategy/matched_strategy` → 按战法多选 chips；有 `matched_triggers`（R3）→ 按触发类型多选 chips；两者皆无的层（R1/R2）不显示筛选（仅得分+排序）。筛选为"或"逻辑（选中任一即保留）。
- [ ] R6 `lib/candidates.ts` PassedItem 补 `matched_triggers?: string[]`。

## 3. 受影响文件
| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/funnel.py` | R1/R2/R3 passed 补 gene_score；R3 补 matched_triggers |
| `frontend/src/lib/candidates.ts` | PassedItem 加 matched_triggers |
| `frontend/src/components/ui/FunnelLayerCard.tsx` | 得分显示 + 排序切换 + 多选筛选 |
| `backend/candidate_funnel/tests/test_funnel_passed_scores.py`（新） | R1/R2/R3 gene_score + R3 matched_triggers |
| `frontend/src/components/ui/FunnelLayerCard.test.tsx` | 排序 + 多选筛选 |

## 4. 验收标准
- [ ] A1 R1/R2/R3 passed 每项含 gene_score（无则 null，不臆造）
- [ ] A2 R3 passed 含 matched_triggers（竞价异动/公告催化/概念联动 的子集）
- [ ] A3 前端每行显示得分；默认降序；可切回原序
- [ ] A4 多选筛选（战法/触发类型）按"或"逻辑过滤显示
- [ ] A5 `pytest -m "not live"` 全过；`tsc --noEmit` green
- [ ] A6 合规：得分/触发类型为客观数据展示，无方向性结论；不臆造（缺数据 null）

## 5. 合规与工程底线自查
- 得分来自真实 gene_scores/因子，缺数据标 null 不臆造 ✓
- 仅客观展示（得分/排序/筛选），不输出买卖指令 ✓
- 无新东财端点、不碰私有数据 ✓
