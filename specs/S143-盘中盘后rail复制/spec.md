# Spec: S143 — 盘中/盘后 rail 复制（CandidateStateRail 跨语境一致性）

> 状态：已实现(2026-09-02)（tsc PASS + vitest 437/437 + s063 e2e AC12 绿；IntradayMonitor 全零 bug 修）
> 作者：lzw9560  日期：2026-09-02
> 关联：S140（脊柱试点，定义 CandidateStateRail）/ S063（IntradayMonitor）/ S054（PostMarketReview）
>
> 本文件命名为 `spec.md`，放在 `specs/S143-盘中盘后rail复制/` 子目录下。

## 1. 问题 / 目标

S140 把 7 态状态机挖成 `CandidateStateRail`，但只在选股（SelectionStageView）挂了。盘中（IntradayMonitor）仍就地用 `<StateMachineDashboard />`——且**未传 date**（S140 §2 已记活 bug：`useWorkflowStates` enabled:!!date → 全零）。复盘（PostMarketReview）无 rail。

本 spec：盘中换用 `CandidateStateRail`（顺手修全零 bug，date=triplet.today）；复盘挂 `CandidateStateRail`（date=triplet.review）。达成跨语境 rail 一致性（S140 R6 收窄时推到本 spec 的部分）。

## 2. 背景

- **F** `IntradayMonitor.tsx:108` 渲染 `<StateMachineDashboard />` 无 date → `useWorkflowStates`（`workflow.ts:27` enabled:!!date）不发 query → 7 态全显 0。`triplet.today` 在 `IntradayMonitor:74` 本就有。
- **F** `PostMarketReview` 由 Workflow review tab 渲染，接 `date={triplet.review}`（`Workflow.tsx:319`）。
- `CandidateStateRail`（S140）= 包 StateMachineDashboard + date 空→null 防全零空挂。

## 3. 需求清单

- [ ] R1 `IntradayMonitor.tsx:108` 把 `<StateMachineDashboard />` 换成 `<CandidateStateRail date={triplet.today} />`（修全零 bug + 复用 rail）。
- [ ] R2 `PostMarketReview.tsx` 挂 `<CandidateStateRail date={date} />`（date=triplet.review，跨语境一致）。
- [ ] R3 IntradayMonitor 全零 bug 修后：rail 非空 date + 计数>0（不再全零）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/pages/workflow/IntradayMonitor.tsx` | R1：换 StateMachineDashboard → CandidateStateRail(date=triplet.today)，删 StateMachineDashboard import |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | R2：挂 CandidateStateRail(date={date}) |

## 5. 设计方案

- 盘中：IntradayMonitor 已有 triplet（:74），直接传 `date={triplet.today}`。换组件即修 bug——CandidateStateRail 的 date 空→null 门控 + StateMachineDashboard 内 enabled:!!date 双保险。
- 复盘：PostMarketReview 接 `date` prop（=triplet.review），挂 rail 显示复盘日的 7 态分布。
- 不动 stage-view 抽取（盘中/复盘的 3 轴归位留后续 spec——本 spec 只做 rail 一致性 + bug 修）。

## 6. 验收标准

- [ ] A1 IntradayMonitor 渲染 CandidateStateRail（非 StateMachineDashboard），date=triplet.today 非空
- [ ] A2 IntradayMonitor rail 计数>0（全零 bug 修，不再 0）
- [ ] A3 PostMarketReview 渲染 CandidateStateRail，date=triplet.review
- [ ] A4 tsc + vitest + e2e（s063 AC12 盘中四层 + IntradayMonitor rail）绿

## 7. 合规与工程底线自查

- [x] 无新方向性输出：rail 呈现 7 态客观计数（已有），不触 §1.1。
- [x] 判断可复现：date 传对（triplet.today/review），不臆造。
- [x] 无私有数据/东财端点变更。

## 8. 测试计划

- vitest：IntradayMonitor 现有测试加「rail 收非空 date」断言；PostMarketReview 同。
- e2e：s063 AC12（盘中四层）仍绿 + rail 可见。

## 9. 风险与回滚

- **IntradayMonitor 测试 mock**：现有 IntradayMonitor.test 可能 mock 了 StateMachineDashboard；换 CandidateStateRail 后 mock 路径变，须同步（tsc/vitest 兜底）。
- 回滚：还原两文件 import + 渲染。
