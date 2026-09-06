# Spec: S165 — UI 契约先行（DimensionValidationCard + 实验记录，contract-first 驱动 infra shapes）

> 状态：草案 v2（S160 component 5，priority 1，UI 先行 [[ui-first-implementation-order]]）
> 关联：S160 / S161 v2 / S151 / S159 §5A / ui-first-implementation-order
> 分级：small-medium（UI 组件 + mock + 类型契约）—— issue 层单轮 review
> v2 修订：spec-grill 修 status enum 缺第 5 值 not_validated / ci_low·updated_commit REGISTRY 无源（臆造引用 S153 v1 类）/ evaluation_lifts.db 锚 phantom / 三窗口 IC/lift 与 S159 §5A 不符 / gap 非 REGISTRY 维是 §3 event verdict。

## 0. 问题

UI 先行指令（[[ui-first-implementation-order]]）+ grill #5（三层 notional）+ §44 verdicts 需诚实呈现（S151 honest terminal 已有 evaluation_summary，但缺验证卡 + 实验记录 UI）。UI 不是 re-scope 后被动呈现，是 re-scope 的**形状驱动者**（contract-first：UI 数据形状反过来锚定 S161 v2 Verdict + Recorder schema）。

## 1. 目标

建 UI 契约先行——DimensionValidationCard（验证卡）+ 实验记录页，**mock 先跑**（不依赖后端实现），数据形状锚定 S161 v2 Verdict + Recorder schema。UI 先行非被动呈现。

## 2. 需求清单

- **R1 DimensionValidationCard 组件**：字段匹配 **S161 v2 Verdict dataclass**（双向锁）：
  - `dimension_id` / `label` / `selection_lift`（v2 rename lift→selection_lift）/ `ci_low` / `ci_high`（S161 新增，S151 REGISTRY 无 → mock null + "待 v2 verifier 跑出"灰底，**不臆造**）/ `n` / `n_effective`（v2 加，day_paired effective n）/ `days_robust` / `status` (robust_edge|underpowered|falsified|**not_validated**|exploratory —— v2 加第 5 值 not_validated 覆盖 [1,2)-lift+sufficient n/days 如 platform_breakout/low_absorption) / `edge_type` (selection|event|population) / `tradeable` (bool) / `event_metrics` (mean_return/net_mean/win_rate/t_stat/n_event/base_rate, nullable) / `event_status` (event_robust|event_thin_positive|event_falsified|event_not_tested, nullable) / `weight_multiplier` / `source_script` / `note` / `dsr_method` (cross_trial_variance|lenient_single_estimate|N/A) / `pbo` (null+N/A single-strategy vs 待建 区分) / `frozen_commit` / `updated_commit` / `updated_at`（v2 加，回溯后覆盖，mock null + "待回溯 task 填充"灰底）。
  - **三窗口对比表**（隔夜 gap / D+1 日内 / path 的 **mean+中位+胜率+base_rate**，S159 §5A 口径，**不算 IC/lift** —— v2 修，IC 属 post-sanity verifier 步非 window-sanity 表）。
  - **overfit 统计占位**（PBO/CSCV/DSR/Haircut/MinTRL 显式标"待建"灰底，S161 wire 后填实；**PBO 单策略 run 标 "N/A (single-strategy)" 区别 "待建 (not-yet-wired)"**）。
  - **mock field source map**（v2 加，治 S153 v1 臆造引用）：ci_low/ci_high → S161 Verdict（null+"待 v2"灰底非臆造）；updated_commit/updated_at → null+"待回溯 task 填充"灰底（无源，S161 v2 已加字段待回溯填）；pbo → null+"N/A single-strategy"（gap）或 "待建"；REGISTRY-populated 字段仅：dimension_id/label/lift/n/days_robust/status/weight_multiplier/source_script/note/frozen_commit。

- **R2 实验记录页**：list `recorder_id` + `data_snapshot_id`（v2 加，as_of PIT bundle-id）+ 输入快照 hash + params + n_trials + trials_matrix 存在性 + `dsr_method` + verdict + timestamp。匹配 S161 v2 Recorder schema。一条 ID 复现（点 recorder_id 重算/查看，两复现判据：verdict-reproducibility 恒成功 + data-revalidation as_of hash 比）。

- **R3 mock 先跑**：fixture mock data（沿用 S151 DIMENSION_LIFT_REGISTRY 现有 12 维数据，标 mock）。**status 映射诚实**（v2 修，治 grill contract lens 证 S151↔S161 enum 不 1:1）：
  - S151 "validated" → S161 "robust_edge"（但 days_robust<60 → "underpowered" 待 live 60 天复验）
  - S151 "未validated"（1≤lift<2 弱信号）→ S161 **"not_validated"**（非 underpowered——breakout n=43691 不欠样本，是 lift 弱非 n 小；v2 加第 5 值正是为此）
  - S151 "劣于随机"（lift<1）→ S161 "falsified"
  - S151 "探索性" → S161 "exploratory"
  - platform_breakout(lift1.0791,n946,days130) + low_absorption(lift1.0015,n92308,days145) → "not_validated"（[1,2)-lift+sufficient n/days，v2 第 5 值覆盖）
  - **gap 非 REGISTRY 12 维之一**（v2 修，治 mock 子代理歧义#5）：gap 是 S161 §3 的 **event verdict**（edge_type=event），独立呈现非 REGISTRY 行；card 的 gap-marking 逻辑触发于 §3 event verdict 注入，非 REGISTRY dim。

- **R4 contract-first 锚定**：`verifier-contract.ts` 类型（Verdict + RecorderRecord）→ **S161 v2 Verdict dataclass + Recorder schema**（**drop "evaluation_lifts.db schema" 锚**——phantom：S161 Recorder 是 verifier_recorder/ 非 evaluation_lifts.db；S151 evaluation_lifts.db schema 未定义 + 回溯 task 未跑；S165 实现已只锚 S161）。改 S161 Verdict 字段须同步改 UI 契约（双向锁，5 值 enum + edge_type + event_metrics + dsr_method）。

- **R5 诚实标注**：`status` 颜色（robust_edge=绿 / underpowered=黄"待 live 60 天复验" / falsified=红 / not_validated=灰"弱信号非欠样本" / exploratory=灰）+ `honest_label "选股层无 validated 维度, edge 待盘中验证"`（S151 既有）。**edge_type 作主 scoping 标签旁 status**（v2 加，治外推：selection-falsified 永不被读成"gap 无 edge"，带 note "selection falsified; population event edge may exist"）。gap event verdict 标 "hypothesis 非 verified"。

- **R6 三层 reframe 呈现（grill #5）**：selection 层标"展示终态" / direction 层标"deferred 未建" / infra 层标"built"。无假层间 pipeline 契约 UI。regime gate 标 timing 层（移出 selection）。

## 3. 受影响文件

- 新建 `frontend/src/components/DimensionValidationCard.tsx`。
- 新建 `frontend/src/pages/VerifierRecords.tsx`（实验记录页）。
- 新建 `frontend/src/lib/verifier-contract.ts`（Verdict + RecorderRecord 类型，锚定 S161 v2 schema）。
- 新建 `frontend/src/lib/__fixtures__/dimension-validation.mock.ts`（mock data，沿用 S151 REGISTRY + status 诚实映射 + gap event verdict 独立）。
- 改 `frontend/src/pages/limitup/SelectionPipeline.tsx`（或漏斗页）接入 DimensionValidationCard（S151 evaluation_summary 既有，扩字段接 Verdict v2）。

## 4. 验收标准

- [ ] R1 DimensionValidationCard mock 跑（vitest 单测 + playwright e2e）。
- [ ] R2 实验记录页 mock 跑。
- [ ] R3 mock data 来自 S151 REGISTRY 现有 + status 诚实映射（5 值 enum，gap 非 REGISTRY 维是 §3 event verdict）。
- [ ] R4 verifier-contract.ts 类型匹配 S161 v2 Verdict + Recorder schema（contract-first，双向锁，**drop evaluation_lifts.db 锚**）。
- [ ] R5 诚实标注（status 5 色含 not_validated + honest_label + edge_type 主标签 + gap hypothesis 标）。
- [ ] R6 三层 reframe 呈现。
- [ ] tsc 0 + vitest 绿 + playwright e2e 绿。

## 5. 合规与工程底线自查

- [x] 不臆造：mock data 来自 S151 DIMENSION_LIFT_REGISTRY 现有 + 显式标 mock + **field source map**（ci_low/updated_commit/pbo null 标"待"非臆造）。
- [x] 私有数据隔离：UI 不存私有数据，读后端 API（VerifierRecords 通过 /api/verifier/records）。
- [x] §44 诚实标注：status 5 值准确（not_validated 覆盖弱信号非欠样本；underpowered 标待复验；falsified 须 days≥60）。
- [x] verdict 外推禁令：UI 不外推"无 edge"，标"该窗口无 edge ≠ 无 edge"（S159 disclaim 呈现）；edge_type 主标签防 selection-falsified 被读成"gap 无 edge"。
- [x] UI 先行：契约先于后端落地（contract-first，mock 先跑）。

## 6. 分级

small-medium（UI 组件 + mock + 类型契约）。issue 层单轮 review。UI 先行（[[ui-first-implementation-order]]：UI 契约提前到 core，实现用户可见层先 UI 再接后端）。与 S161 v2 双向锁（Verdict schema 同步，5 值 enum + edge_type + event_metrics + dsr_method）。
