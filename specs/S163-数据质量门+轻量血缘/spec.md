# Spec: S163 — 数据质量门 + 轻量血缘（砍 lake/ETL 无消费者）

> 状态：草案（S160 component 3，priority 3，design-agnostic）
> 关联：S160 / grill-foundation-holes-2026-09-06（#3 reuse rot harness 硬编码 + synthesis 臆造前科）
> 分级：small-medium —— issue 层单轮 review

## 0. 问题

grill #3（9 harness 脚本硬编码 Vibe-Research-S151 绝对路径）+ §44 synthesis agent 臆造前科"已跑 matrix 实际没跑"（lineage 对此只覆盖 provenance trail + 可复现脚手架：存在性检查捕 missing-artifact + as_of 支撑 recompute-verify；sophisticated 臆造仍靠人/verifier 读原始输出，不外推）+ grill+数据 lens（lake/ETL 无消费者 YAGNI）。数据质量不可信 = verdict 不可信（违 north-star"讲得起长期验证"）。

## 1. 目标

建轻量数据质量门（源边界 schema 校验 + 缺失/异常/stale 拒绝进 §44）+ 轻量血缘（脚本→artifact+commit hash+as_of 可追溯）。**砍 lake/ETL/血缘重**（无消费者 YAGNI）。lineage 定位 = provenance trail + 可复现脚手架（artifact 存在性检查捕 lazy-agent missing-artifact + as_of 支撑 recompute-verify）；对抗 sophisticated agent 臆造仍靠人/verifier 读原始输出，不外推。治 harness 硬编码根因。是"讲得起长期验证"前提（数据质量可信）。

## 2. 需求清单

- **R1 源边界 schema 校验**：每个数据源（baostock/ths_limit_up_pool/akshare/sina/hithink）返回校验（shape + content + 缺失率 + 异常值 + freshness）。bad data 拒绝进 §44 verifier（不污染 verdict）。
- **R2 轻量血缘**：每次 artifact 产出记录（script + commit hash + as_of/data-snapshot-id [PIT bundle-id] + inputs hash + output hash + timestamp）。**as_of ≠ content hash**——hash 是指纹非可复算状态；as_of/快照 id 指向可重算的 frozen 输入 bundle（复算需原始输入非仅指纹）。SQLite 或 JSONL 落 `.vibe-research/lineage/`，**write-once/append-only**（不覆盖不删）。可追溯 + 可复算验证（frozen_commit 上 pin as_of 输入 → 重算 output → hash 匹配）。
- **R3 harness ROOT 参数化（grill #3）**：9 脚本硬编码绝对路径 `ROOT = Path('/Users/lizhiwei/project/code/stock/Vibe-Research-S151')` → 参数化。**`tools/` 前缀不改 `backend/tools/`**（`tools/` 是正确的 cwd-relative 约定：backend/ 无 `__init__.py`，从 backend/ cwd 启 uvicorn；`evaluation.py` source_script 已用 `tools/` 前缀）。两选项**不互换**，二选一：① `vr_paths.resolve_data_dir()`（已含 `.vibe-research`，改 `ROOT/'.vibe-research'/X` → `DATA_DIR/X`，**去掉** `.vibe-research` 段）② `Path(__file__).resolve().parents[2]`（repo 根，保留 `ROOT/'.vibe-research'/X`）。不硬编码 Vibe-Research-S151（主 checkout 跑不了）。
- **R4 砍 lake/ETL/血缘重（YAGNI）**：无消费者不建。等 ≥1 validated 线路需 data lake 再建。

## 3. 受影响文件

- 新建 `backend/data_quality/schema_validator.py`（5 源校验）。
- 新建 `backend/data_quality/lineage.py`（血缘记录，write-once/append-only 落 `.vibe-research/lineage/`）。
- 改 `tools/` 9 脚本 ROOT 参数化（grill #3）。

## 4. 验收标准

- [ ] R1 schema 校验（5 源）拒绝 bad data 进 §44。
- [ ] R2 血缘记录（script+commit+as_of+io hash）可追溯 + write-once/append-only。
- [ ] R3 9 脚本 ROOT 参数化（不硬编码，主 checkout 跑得通）。
- [ ] pytest 单测 + recompute-verify（frozen_commit 上 pin as_of 输入 → 重算 output → hash 匹配；script→artifact 追溯）。

## 5. 合规与工程底线自查

- [x] 不臆造：schema 校验实算，血缘可追溯 + 可复算验证。lineage = provenance trail + 可复现脚手架（存在性检查捕 lazy-agent missing-artifact + as_of 支撑 recompute-verify）；对抗 sophisticated agent 臆造仍靠人/verifier 读原始输出，不外推。
- [x] 私有数据隔离：血缘写 .vibe-research 不进 git。
- [x] em_get 防封：校验层不直连源（读 cache 或 S162 PIT bundle）。
- [x] YAGNI：砍 lake/ETL 无消费者。

## 6. 分级

small-medium。issue 层单轮 review。design-agnostic（任何线路需 clean data + 质量门）。
