# Spec: S165 — UI 契约先行（DimensionValidationCard + 实验记录，contract-first 驱动 infra shapes）

> 状态：草案（S160 component 5，priority 1，UI 先行 [[ui-first-implementation-order]]）
> 关联：S160 / S161 / S151 / ui-first-implementation-order
> 分级：small-medium（UI 组件 + mock + 类型契约）—— issue 层单轮 review

## 0. 问题

UI 先行指令（[[ui-first-implementation-order]]）+ grill #5（三层 notional）+ §44 verdicts 需诚实呈现（S151 honest terminal 已有 evaluation_summary，但缺验证卡 + 实验记录 UI）。UI 不是 re-scope 后被动呈现，是 re-scope 的**形状驱动者**（contract-first：UI 数据形状反过来锚定 S161 verifier 输出契约 + evaluation_lifts.db schema + Recorder schema）。

## 1. 目标

建 UI 契约先行——DimensionValidationCard（验证卡）+ 实验记录页，**mock 先跑**（不依赖后端实现），数据形状反过来锚定 S161 Verdict + Recorder schema + evaluation_lifts.db。UI 先行非被动呈现。

## 2. 需求清单

- **R1 DimensionValidationCard 组件**：字段 = `dimension_id` / `label` / `lift` / `ci_low` / `ci_high` / `n` / `days_robust` / `status` (robust_edge|underpowered|falsified|exploratory) / `weight_multiplier` / `source_script` / `note` + **三窗口对比表**（隔夜 gap / D+1 日内 / path 的 mean+中位+胜率+base rate+IC/lift，S159 R1 前置窗口 sanity 呈现）+ **overfit 统计占位**（PBO/CSCV/DSR/Haircut/MinTRL 显式标"待建"灰底，S161 wire 后填实）+ `frozen_commit` / `updated_commit` / `updated_at`。匹配 S161 `Verdict` dataclass。
- **R2 实验记录页**：list `recorder_id` + 输入快照 hash + params + n_trials + verdict + timestamp。匹配 S161 Recorder schema。一条 ID 复现（点 recorder_id 重算/查看）。
- **R3 mock 先跑**：fixture mock data（沿用 S151 DIMENSION_LIFT_REGISTRY 现有 12 维数据，标 mock），不依赖后端 verifier 实现。UI 契约先于后端落地。
- **R4 contract-first 锚定**：`verifier-contract.ts` 类型（Verdict + RecorderRecord）→ S161 Verdict dataclass + Recorder schema + evaluation_lifts.db schema。后端实现这些 schema（UI 驱动，非反之）。改 S161 Verdict 字段须同步改 UI 契约（双向锁）。
- **R5 诚实标注**：`status="falsified"` 红底 / `"underpowered"` 黄底"待 live 60 天复验" / `"exploratory"` 灰底 / `"robust_edge"` 绿底（须 ≥2x lift + DSR>0 + Bonferroni 全过 + days_robust≥60）。`honest_label "选股层无 validated 维度, edge 待盘中验证"`（S151 既有）。gap 维度标 "hypothesis 非 verified"。
- **R6 三层 reframe 呈现（grill #5）**：selection 层标"展示终态" / direction 层标"deferred 未建" / infra 层标"built"。无假层间 pipeline 契约 UI（诚实呈现 notional）。regime gate 标 timing 层（移出 selection）。

## 3. 受影响文件

- 新建 `frontend/src/components/DimensionValidationCard.tsx`。
- 新建 `frontend/src/pages/VerifierRecords.tsx`（实验记录页）。
- 新建 `frontend/src/lib/verifier-contract.ts`（Verdict + RecorderRecord 类型，锚定 S161 schema）。
- 新建 `frontend/src/lib/__fixtures__/dimension-validation.mock.ts`（mock data，沿用 S151 REGISTRY）。
- 改 `frontend/src/pages/limitup/SelectionPipeline.tsx`（或漏斗页）接入 DimensionValidationCard（S151 evaluation_summary 既有，扩字段接 Verdict）。

## 4. 验收标准

- [ ] R1 DimensionValidationCard mock 跑（vitest 单测 + playwright e2e）。
- [ ] R2 实验记录页 mock 跑。
- [ ] R3 mock data 来自 S151 REGISTRY 现有 + 标 mock。
- [ ] R4 verifier-contract.ts 类型匹配 S161 Verdict + Recorder schema（contract-first，双向锁）。
- [ ] R5 诚实标注（status 颜色 + honest_label + gap hypothesis 标）。
- [ ] R6 三层 reframe 呈现（展示终态/deferred/built 标签）。
- [ ] tsc 0 + vitest 绿 + playwright e2e 绿。

## 5. 合规与工程底线自查

- [x] 不臆造：mock data 来自 S151 DIMENSION_LIFT_REGISTRY 现有 + 显式标 mock，不臆造 verdict。
- [x] 私有数据隔离：UI 不存私有数据，读后端 API（VerifierRecords 通过 /api/verifier/records）。
- [x] §44 诚实标注：status 准确反映 verdict（不夸大 robust，underpowered 标待复验）。
- [x] verdict 外推禁令：UI 不外推"无 edge"，标"该窗口无 edge ≠ 无 edge"（S159 disclaim 呈现）。
- [x] UI 先行：契约先于后端落地（contract-first，mock 先跑）。

## 6. 分级

small-medium（UI 组件 + mock + 类型契约）。issue 层单轮 review。UI 先行（[[ui-first-implementation-order]]：UI 契约提前到 core，实现用户可见层先 UI 再接后端）。与 S161 双向锁（Verdict schema 同步）。
