# Spec: S163 — 数据质量门 + 轻量血缘（砍 lake/ETL 无消费者）

> 状态：草案（S160 component 3，priority 3，design-agnostic）
> 关联：S160 / grill-foundation-holes-2026-09-06（#3 reuse rot harness 硬编码 + synthesis 臆造前科）
> 分级：small-medium —— issue 层单轮 review

## 0. 问题

grill #3（9 harness 脚本硬编码 Vibe-Research-S151 路径 + §44 synthesis agent 臆造前科"已跑 matrix 实际没跑"）+ grill+数据 lens（lake/ETL 无消费者 YAGNI）。数据质量不可信 = verdict 不可信（违 north-star"讲得起长期验证"）。

## 1. 目标

建轻量数据质量门（源边界 schema 校验 + 缺失/异常/stale 拒绝进 §44）+ 轻量血缘（脚本→artifact+commit hash 可追溯）。**砍 lake/ETL/血缘重**（无消费者 YAGNI）。治 §44 synthesis 臆造 + harness 硬编码根因。是"讲得起长期验证"前提（数据质量可信）。

## 2. 需求清单

- **R1 源边界 schema 校验**：每个数据源（baostock/ths_limit_up_pool/akshare/sina/hithink）返回校验（shape + content + 缺失率 + 异常值 + freshness）。bad data 拒绝进 §44 verifier（不污染 verdict）。
- **R2 轻量血缘**：每次 artifact 产出记录（script + commit hash + inputs hash + output hash + timestamp）。SQLite 或 JSONL 落 `.vibe-research/lineage/`。可追溯（哪个脚本产出哪个 verdict 数据，治 synthesis 臆造）。
- **R3 harness ROOT 参数化（grill #3）**：9 脚本改 `Path(__file__).resolve().parents[2]` 或 `VR_DATA_DIR`，不硬编码 Vibe-Research-S151（主 checkout 跑不了）。
- **R4 砍 lake/ETL/血缘重（YAGNI）**：无消费者不建。等 ≥1 validated 线路需 data lake 再建。

## 3. 受影响文件

- 新建 `backend/data_quality/schema_validator.py`（5 源校验）。
- 新建 `backend/data_quality/lineage.py`（血缘记录）。
- 改 `tools/` 9 脚本 ROOT 参数化（grill #3）。

## 4. 验收标准

- [ ] R1 schema 校验（5 源）拒绝 bad data 进 §44。
- [ ] R2 血缘记录（script+commit+io hash）可追溯。
- [ ] R3 9 脚本 ROOT 参数化（不硬编码，主 checkout 跑得通）。
- [ ] pytest 单测 + 血缘复现（script→artifact 追溯）。

## 5. 合规与工程底线自查

- [x] 不臆造：schema 校验实算，血缘可追溯（治 synthesis 臆造前科）。
- [x] 私有数据隔离：血缘写 .vibe-research 不进 git。
- [x] em_get 防封：校验层不直连源（读 cache 或 S162 PIT bundle）。
- [x] YAGNI：砍 lake/ETL 无消费者。

## 6. 分级

small-medium。issue 层单轮 review。design-agnostic（任何线路需 clean data + 质量门）。
