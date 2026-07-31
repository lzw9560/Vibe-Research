# S014 Recovery & TODO（2026-07-31 事故记录）

> 本文件记录 2026-07-31 并行 git 操作删 526 tracked 文件事故 + S014 推进待办。
> 由 grill-me review 产出。非 spec 正本，是事故/待办台账。

## 1. 事故经过

- **触发**：并行会话（正在改 CLAUDE.md §0.1 Feature 分支工作流）跑了一个破坏性 git 操作（checkout/reset/clean 类），把工作树里 **526 个 tracked 文件**删除。HEAD `7d11fd2` 完好。
- **reflog 证据**：今天有 2 次 `reset: moving to HEAD~1`（`2c91243`、`d00245e` 被重置掉），S010 commit 被重做为 `7d11fd2`。
- **恢复**：`git ls-files -d -z | xargs -0 git restore --`（只恢复删除，保留那 1 个幸存 ` M` = CLAUDE.md §0.1）。` D` 526→0。
- **S014 Phase 0 重建**：我对 7 个 tracked 文件的未提交编辑随删除丢失（DataTable sortable / index.css 令牌 / PreMarketBriefing+SectorDivergence pctColor 迁移 / S010 spec / S017 spec+plan 合规对齐）。从对话上下文逐字重建 → build ✓ / vitest 15/15 ✓ → 提交 `1935cc2` on develop。

## 2. Error（不可从 git 恢复的损失）

- **别的会话未 staged 的修改丢失**：被删的 526 tracked 文件里，凡是「未进 index 的 ` M` 修改」（如 backend 各文件的在途改动）——删除后 `git restore` 只能恢复到 HEAD/ staged 版本，**那部分修改不可从 git 恢复**。只有 staged 进 index 的工作在 restore 后存活（worldmonitor.py/newsradar.py/alt.py/4 个 test/S020 spec 共 9 staged 文件在 index 里完好）。
- **受影响会话需各自从对话上下文重建**丢失的未暂存改动——我（S014 会话）的上下文里没有别会话的 backend 改动内容，帮不了。
- **S014 plan.md 漏提交**：`1935cc2` 只含 spec.md+tasks.md，plan.md 仍是 `??`——待 base 提交补上。

## 3. §0.1 偏离（待修正）

- §0.1 Feature 分支工作流要求：spec 文档进 develop、实现代码走 `feature/S014-前端UI重设计` 分支。
- 我按用户「一个 commit」指示 + 受损树上 branch checkout 风险高，**把 S014 impl 直接提交到 develop**（`1935cc2`）。
- **待办**：`git branch feature/S014-前端UI重设计` → `git reset --hard 1069bdc`（develop 回退，移除 S014 impl）→ 保留 feature 分支的 S014 impl。需在 squash 清理后做。

## 4. 待办（按优先级）

| # | 待办 | 归属 | 前置 |
|---|---|---|---|
| 1 | base 提交：S014 plan.md + CLAUDE.md §0.1 + 本 RECOVERY.md（路径限定，不卷别人 staged） | 本会话 | 别的会话结束 |
| 2 | 清理 S010 reset 重复历史（`7d11fd2` vs 被重置的 `2c91243`/`d00245e`） | 本会话 | **确认别的会话没从 develop 近期提交分叉 feature 分支**（硬阻） |
| 3 | S014 impl 从 develop 迁到 `feature/S014-前端UI重设计`（§0.1 合规） | 本会话 | #2 后 |
| 4 | S014 Phase 1：T8 DailyReview 首页骨架（12→~8 state）+ T9 下沉 | 升用户审批（品味调用） | #1 |
| 5 | 别的会话：从各自对话上下文重建丢失的未暂存 backend 改动 | 各会话 | — |
| 6 | Phase 1 起浏览器 MCP 截图比对 gate 生效（DataTable/FilterBar 接入页） | 本会话 | #4 |

## 5. 已落地（截至 `1935cc2`）

- §7 合规对齐弱合规 2026-07-30：S014 + sync S006/S017/S010/S007
- T4 State.tsx / T5 DataTable sortable / T6 FilterBar / T7 pctColor 迁移 2 处（含修 PreMarketBriefing 美股绿涨→A股红涨 bug）/ T17 index.css 令牌
- gate：build ✓ / vitest 3 files 15 tests ✓
- 分阶段重排 + 依赖图修正（page 拆分依赖 T5/T6/T7 非 T4）+ T25 连续 gate + 审批 checklist 化

## 6. 清上下文前检查清单

清上下文（`/compact` 或 `/clear`）前必须：
- [ ] #1 base 提交完成
- [ ] #2 squash 完成（或显式决定不做）
- [ ] 本 RECOVERY.md 已入 git
- [ ] s014-checkpoint / s014-recovery memory 已更新
- [ ] 用户显式说「清上下文」
