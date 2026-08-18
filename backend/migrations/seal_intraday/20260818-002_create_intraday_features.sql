-- S070 R3：intraday 因子持久化（trajectory + 派生结果）
-- 设计：trajectory（R1，盘中实时可算）与派生（R7，盘后/日终算）分表，因计算时机不同
--   - intraday_features：R1 trajectory（盘中每轮可更新，UPSERT）
--   - seal_derived_features：R7 派生（日终一次性算，INSERT OR REPLACE）

-- R1：封单 trajectory 因子表（date/code 主键，盘中可多次 UPSERT）
CREATE TABLE IF NOT EXISTS intraday_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                   -- 交易日 YYYY-MM-DD
    code TEXT NOT NULL,
    name TEXT,
    -- 封单 trajectory（从 seal_intraday_snapshots 时序派生）
    seal_delta REAL,                       -- 日内封单 delta（末值 - 首值）
    seal_max REAL,                         -- 日内封单峰值
    seal_min REAL,                         -- 日内封单谷值
    seal_slope REAL,                       -- 封单斜率（线性回归 slope）
    snapshot_count INTEGER,                -- 快照数（数据完整性参考）
    computed_at TEXT NOT NULL,             -- ISO8601 计算时间戳
    data_status TEXT DEFAULT 'ok',         -- ok/missing/degraded
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code)
);
CREATE INDEX IF NOT EXISTS idx_intraday_features_date ON intraday_features(date);
CREATE INDEX IF NOT EXISTS idx_intraday_features_code ON intraday_features(code);

-- R7：战法因子派生表（date/code 主键，日终一次性算）
CREATE TABLE IF NOT EXISTS seal_derived_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    last_lock_time TEXT,                   -- 最后封死时刻（ISO8601，open_count 最后一次=0 的 ts）
    broken_duration_min REAL,             -- 炸板累计时长（分钟，60s 粒度近似）
    max_drop_pct REAL,                     -- 炸板后回撤幅度（(涨停价-min(low_price))/涨停价*100）
    limit_price REAL,                      -- 涨停价（反推：price/(1+limit_pct/100)）
    granularity_note TEXT DEFAULT '60s粒度近似',  -- 粒度限制标注（A7）
    computed_at TEXT NOT NULL,
    data_status TEXT DEFAULT 'ok',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, code)
);
CREATE INDEX IF NOT EXISTS idx_seal_derived_date ON seal_derived_features(date);
CREATE INDEX IF NOT EXISTS idx_seal_derived_code ON seal_derived_features(code);
