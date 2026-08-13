# Spec: S051 — 基因筛选体验批

> 状态：已实现（2026-08-12，commits `5f166e2`→`b7bd4eb`→`ff1e6a2`）— D1-D5 全落地，T1-T12 全勾，pytest + tsc + vitest 全绿，:8900 冒烟通过。本 spec 事后补写（原只有 plan/task + HANDOFF），spec 正文从 plan.md 反推归纳。
> 作者：Claude  日期：2026-08-11（plan）/ 2026-08-12（实现）/ 2026-08-13（spec 补录）
> 关联：`../S029-gene-screener-wireup/spec.md`（GeneScreener 接通）、`../S047-基因分权重回测校准/spec.md`（权重校准，qualify/high 阈值口径源）、`../S053-炸板后溢价因子修复/spec.md`（零样本根因之一）

## 1. 问题 / 目标

基因筛选页（`GeneScreener.tsx`）在默认参数下 93% 的交易日返回空列表：持久化参数 `limitup_params.json` 为 qualify=65/high=80，而近 150 日全局最高分 70.63，≥80 共 0 行、≥65 仅 10/150 天。同时打板策略页摘要卡写死「SCORE ≥ 60」「SCORE ≥ 75」与任何口径都不一致；战法胜率面板三条战法 60 日零样本显示裸「—」无说明。

目标：复位阈值 50/60（与 DB 标志口径一致）、加 sanity 警告防再误调、基因筛选页加分段视图（合格/全部/自定义）、策略卡文案动态化、零样本战法诚实注记。

## 2. 背景

- `backend/data/limitup_params.json` 现为 qualify=65/high=80（误调高）；DB `gene_scores` 的 qualify/high 标志按 50/60 算，复位 50/60 无需重算。
- `GET /api/limitup/screener` 返回全量 gene_scores（按 total_score 降序）+ qualified/high_gene 子列表——空列表纯是前端客户端按 minScore/maxScore 硬筛造成，后端不用动。
- 零样本根因：炸板后溢价因子近 60 日全 0/NULL（S053 查因中）；N字反击条件结构矛盾（频次>30 ∧ zt_count_250d≤10 互斥）。

## 3. 需求清单

- [x] R1 阈值复位 50/60（走 `POST /api/limitup/screener/params`，同步模块级变量+落盘，勿手改 JSON）
- [x] R2 阈值保存 sanity 警告：保存前查 gene_scores 近 30 日 MAX(total_score)，阈值越界返 warning（不阻断保存）
- [x] R3 基因筛选页分段视图 [合格 | 全部 | 自定义分数段]：合格按后端 `qualify` 标志过滤，全部全量带分（不合格置灰+标记），自定义保留 min/max
- [x] R4 打板策略页摘要卡文案动态化：读 `GET /api/limitup/screener/params`，删写死 60/75
- [x] R5 战法胜率面板零样本诚实注记：STRATEGY_REGISTRY 三条目加 `note`，`/api/strategy/backtest` 透出，WinRateComparePanel 零样本行显示 note

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/limitup_params.json` | R1：qualify 65→50、high 80→60（经端点写入） |
| `backend/routers/limitup/screener.py` | R2：save_limitup_screener_params 加 sanity 警告逻辑 |
| `frontend/src/pages/limitup/GeneScreener.tsx` | R3：viewMode 分段 + doSearch 拉全量按模式过滤 |
| `frontend/src/components/GeneFilterForm.tsx` | R3：分段控件 + min/max 仅 custom 模式生效 |
| `frontend/src/components/GeneResultTable.tsx` | R3：不合格行视觉降级 + 空态文案区分 |
| `frontend/src/pages/LimitUpStrategy.tsx` | R4：摘要卡文案读 params 端点 |
| `backend/limitup_strategy.py` | R5：STRATEGY_REGISTRY 三条目加 note 字段 |
| `backend/routers/strategy.py` | R5：strategy_backtest 响应透出 note |
| `frontend/src/components/ui/WinRateComparePanel.tsx` | R5：零样本行显示 note |

## 5. 设计方案

- **阈值复位走端点不走手改**：`POST /api/limitup/screener/params` 同时更新 ls 模块级变量 + 持久化 JSON，手改文件会导致运行中进程模块值不同步。
- **分段取代硬筛**：原前端按 minScore/maxScore 客户端硬筛是空列表根因；改合格模式按后端 `qualify` 标志过滤（后端已算好），全部模式全量展示，custom 模式才走分数区间。
- **零样本注记是临时诚实标注**：S053 修复后 note 可能修订，代码注释注明。
- **不做**：炸板后溢价数据管道修复（S053）、N字反击重定义（backlog）、快照回填（S052）。

## 6. 验收标准

- [x] A1 `GET /api/limitup/screener/params` 返回 50/60；今日 qualify 计数不变（标志本就 50/60 口径）
- [x] A2 阈值越界（high=80）返 warning；正常保存（high=55）无 warning
- [x] A3 基因筛选页三模式渲染：qualified 只出 qualify=true 行 / all 出全量且不合格行有标记 / custom 按分数区间
- [x] A4 打板策略卡片文案随 params 动态变化（50/60）
- [x] A5 战法面板零样本行显示 note（三条）
- [x] A6 pytest + tsc + vitest 全绿
- [x] A7 :8900 冒烟通过

## 7. 合规与工程底线自查（逐条确认）

- [x] 页面保持「客观数据，非推荐」语义，不出现方向结论词；note 是诚实标注非推荐
- [x] 零新外部调用（不得新增 em_get/网络请求）——本批纯前端+参数复位
- [x] 不涉及用户私有数据
- [x] 阈值复位基于 DB 已有标志口径（50/60），非臆造

## 8. 测试计划

- 后端：`pytest tests/test_limitup.py`（sanity 警告单测）
- 前端：`npx vitest run`（三模式渲染 + warning 回显 + note 显示 + 动态文案）
- 全量：`pytest -m "not live"` + `tsc --noEmit`
- 冒烟：:8900 基因筛选页（合格/全部/自定义）+ 打板策略卡片 + 战法面板

## 9. 风险与回滚

- 阈值复位 50/60 降低了合格线，可能让边缘标的进入视野——但这是 DB 标志本就用的口径，只是前端展示对齐
- note 文案临时性，S053 修复后需修订
- 回滚：params 端点写回 65/80；前端分段逻辑 git revert
