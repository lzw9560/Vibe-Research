-- PIT (point-in-time) 快照存储：append-only 不可变快照表。
-- 设计：specs/S162-反前视引擎三层/PIT-store-design.md §2.2
-- 用途：bulletproof 复现——任意历史 verdict 从 pinned as_of 数据重算；
--       前复权 mutation 锁定（baostock adjustflag='2' retroactively 可变 →
--       ingest 时 snapshot as_of，同 (source, data_date, as_of) 永不 re-fetch）。
-- append-only：无 UPDATE/DELETE（写一次历史不可变）——由 store.py 不提供
-- mutation 方法 + 不开放 UPDATE/DELETE 接口保证；schema 层不做 TRIGGER 以免
-- 阻碍 MigrationManager 的 schema 演进。
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增
  as_of TEXT NOT NULL,                            -- 取数时刻 ISO（精确秒）
  data_date TEXT,                                 -- 数据日期 YYYYMMDD（kline/baseline 的 date）
  source TEXT NOT NULL,                          -- 'baostock_kline' / 'em_zt_topic_pool' / 'ths_limit_up_pool' / 'first_board_premium_baseline'
  query_spec TEXT NOT NULL,                       -- JSON: {code, endpoint, date_range, adjustflag, ...} 输入查询
  content_hash TEXT NOT NULL,                     -- raw content sha256（完整性校验）
  raw_blob BLOB,                                  -- 原始数据（kline rows / pool list / baseline json）—— 完整非仅 hash
  fetched_at TEXT NOT NULL,                       -- = as_of，冗余便于 query
  generator_commit TEXT                           -- 生成代码 commit（first_board_premium_baseline.py 用）
);
CREATE INDEX IF NOT EXISTS idx_as_of ON snapshots(as_of);
CREATE INDEX IF NOT EXISTS idx_source_date ON snapshots(source, data_date);
