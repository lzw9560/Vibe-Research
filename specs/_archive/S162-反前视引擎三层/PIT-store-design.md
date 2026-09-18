# PIT Store 打重桩 设计 + 实现待办

> 状态：设计文档（S162 R4 配套，打重桩 非轻打桩）
> 决策来源：用户 2026-09-06 "要长远稳定，为什么没消费者，可以先打桩吗" → "打重桩，具体实现记录待办，做好规划和文档设计"
> 关联：S162 v2 R4（PIT UN-deferred built NOW）/ S161 v2 R4（Recorder data_snapshot_id）/ north-star "讲得起长期验证" / data-source-capabilities（前复权 mutation）

## 0. 决策

用户定：长远稳定优先于 YAGNI。即使 PIT store 现在"没消费者"，也**打重桩**（建完整 PIT store，非轻快照）——因为 north-star "讲得起长期验证"要求 bulletproof 复现：任意历史 verdict 能从 pinned as_of 数据重算，前复权 mutation 锁定，跨源 as_of 对齐 future-proof。轻打桩（只存原始快照）不够——重桩含 queryable as_of join + 完整复现链。

v2.1 翻转 S162 R4：PIT FeatureStore **UN-deferred，built NOW heavy foundation**（v2 原 defer 是 grill yagni #20，用户 override——长远稳定 > YAGNI for 复现基建）。

## 1. 目标

- **bulletproof 复现**：任意历史 verdict 可从 pinned as_of 数据重算（非靠"运气没公司行为"）。
- **前复权 mutation 锁定**：baostock adjustflag='2' retroactively 可变——PIT 在 ingest 时 snapshot as_of，同 as_of 永不 re-fetch。
- **跨源 as_of 对齐**：baostock kline + em_zt_topic_pool + ths + baseline.json 按 as_of 时间戳对齐，future-proof（未来多源 join）。
- **非侵入**：ingest hook 装饰现有 em_get/ths_get/baostock fetch，不改 caller 代码。
- **零新依赖**：SQLite + as_of column（匹配项目 JSON+SQLite 全栈），非 parquet/duckdb（未装）。

## 2. 设计

### 2.1 as_of snapshot at ingest
每次取数（baostock kline / em_zt_topic_pool / ths_limit_up_pool / first_board_premium_baseline.json 生成）顺手按 as_of 时间戳存原始快照。as_of = 取数时刻（精确到秒）+ 数据 date（YYYYMMDD）。非侵入——装饰器/wrapper 在 fetch 返回后 hook 存快照。

### 2.2 SQLite schema
```
CREATE TABLE snapshots (
  snapshot_id INTEGER PRIMARY KEY,        -- 自增
  as_of TEXT NOT NULL,                    -- 取数时刻 ISO（精确秒）
  data_date TEXT,                         -- 数据日期 YYYYMMDD（kline/baseline 的 date）
  source TEXT NOT NULL,                   -- 'baostock_kline' / 'em_zt_topic_pool' / 'ths_limit_up_pool' / 'first_board_premium_baseline'
  query_spec TEXT NOT NULL,               -- JSON: {code, endpoint, date_range, adjustflag, ...} 输入查询
  content_hash TEXT NOT NULL,             -- raw content sha256（完整性校验）
  raw_blob BLOB,                          -- 原始数据（kline rows / pool list / baseline json）—— 完整非仅 hash
  fetched_at TEXT NOT NULL,               -- = as_of，冗余便于 query
  generator_commit TEXT                   -- 生成代码 commit（first_board_premium_baseline.py 用）
);
CREATE INDEX idx_as_of ON snapshots(as_of);
CREATE INDEX idx_source_date ON snapshots(source, data_date);
-- append-only: 无 UPDATE/DELETE（写一次，历史不可变）
```

### 2.3 query API
- `query_as_of(source, data_date, as_of=None) -> raw` —— 返回 ≤ as_of 的最近 snapshot 的 raw（point-in-time 查询）。as_of=None → 最新。
- `latest_snapshot_id(source, data_date) -> int` —— 给 S161 Recorder 作 data_snapshot_id。
- `recompute_input(snapshot_id) -> raw` —— 复现取数：从 pinned snapshot 取 raw（不 re-fetch）。

### 2.4 ingest hook（非侵入）
装饰 `em_get` / `ths_get` / baostock fetch wrapper：fetch 返回后，hook 存 snapshot（source/query_spec/raw/content_hash）。caller 代码不改（hook 透明）。只在"启用 PIT"时挂 hook（env `VR_PIT_STORE=1`），默认关（不拖慢非复现 fetch）。

### 2.5 consumer 接口
- **S161 Recorder**：`data_snapshot_id = pit.latest_snapshot_id(source, data_date)`，落进 Recorder 记录（已字段 S161 v2 R1）。
- **S162 engine**：回测读 `pit.query_as_of(source, data_date, as_of=verdict_as_of)` 替代 live kline_cache（复现性）。
- **未来 cross-source as_of join**：多源按时点对齐（future consumer，接口已留）。

### 2.6 两复现判据 wired
- **(a) verdict-reproducibility**：从 S161 Recorder 存的完整 return series 重算 verdict（确定性，恒成功）。
- **(b) data-revalidation**：从 PIT pinned as_of snapshot 重导 series + content_hash 比；不匹配 → 诚实标"前复权重算（corporate action 后），原 verdict 基于 as_of，需 re-baseline"非假绿。

### 2.7 防封 + 存储
- snapshot at ingest **不额外 fetch**——走原 em_get/ths_get/baostock 防封路径，hook 只存返回值。
- 存 `.vibe-research/pit_store/pit_store.db`（SQLite，不进 git，.vibe-research 已 gitignore）。

## 3. 实现待办（concrete，ordered）

1. `backend/pit_store/__init__.py` + `store.py` —— SnapshotStore（SQLite, append-only, schema §2.2, `put/get/query_as_of/latest_snapshot_id/recompute_input`）。纯函数，不可变（append-only）。
2. `backend/pit_store/ingest_hook.py` —— 装饰 em_get/ths_get/baostock fetch wrapper（非侵入，env `VR_PIT_STORE=1` 启用）。
3. `backend/pit_store/query.py` —— query_as_of + recompute_input API（§2.3）。
4. S161 Recorder 接 `data_snapshot_id = pit.latest_snapshot_id(...)`（S161 v2 R1 已字段，wire 落地）。
5. S162 engine 读 `pit.query_as_of(...)` 替代 live kline_cache（复现性，S162 impl 时）。
6. 前复权 mutation 锁定：baostock adjustflag='2' fetch 后 hook 存 snapshot，同 (source, data_date, as_of) 永不 re-fetch（query 走 snapshot）。
7. 两复现判据 wired（S161 R4 §a/§b，pit_store 作 §b 的 recompute 源）。
8. migration：新建 pit_store SQLite schema（vr_paths.resolve_data_dir() / 'pit_store' / 'pit_store.db'，run_migrations 接线）。
9. pytest 单测：snapshot put/get、query_as_of point-in-time、recompute_input hash match、append-only 不可变、ingest hook 非侵入。
10. `.vibe-research/pit_store/` gitignore 确认（.vibe-research 已 gitignore，子目录继承）。
11. 文档：本设计文档更新（实现后标 done + 实际签名）。

## 4. 与 S161 Recorder / S162 engine 关系

- **S161 Recorder**（priority 1，先建）：Recorder 落 `data_snapshot_id`（指向 pit snapshot）+ 完整 return series + frozen_commit + verdict。pit_store 是 Recorder 的 data 态源。
- **S162 engine**（priority 2）：回测读 `pit.query_as_of` 替代 live kline_cache。pit_store 是 engine 复现性的基础。
- **建序**：pit_store（本设计）可与 S161 R3/R4 并行（Recorder 接 data_snapshot_id 时 wire），S162 impl 时消费 query_as_of。

## 5. 分级 + 时机

medium（SQLite + ingest hook + query API + Recorder wire + tests）。issue 层单轮 review。**打重桩 优先级**：S161 R3 merge harness 后 / S162 engine 前（或与 S161 R4 Recorder 并行——Recorder wire data_snapshot_id 时正好接 pit_store）。非 feature 分支（design-agnostic，不碰生产选股）。

## 6. 关联

- S161 v2 R1（Verdict data_snapshot_id 字段）/ R4（Recorder 两复现判据）
- S162 v2 R4（PIT UN-deferred built NOW，本设计文档配套）
- [[rigorous-methodology-timely-retrospective-no-hallucination]]（north-star 讲得起长期验证）
- [[data-source-capabilities]]（前复权 mutation / baostock adjustflag='2'）
- [[foundation-rebuild-v2-progress-checkpoint]]（roadmap）
