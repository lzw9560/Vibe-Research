-- 基础表：情绪温度指数时间线。对齐 limitup_sti/data.py migrate_schema 的 sti_timeline_new 全列。
-- 原 v1 是 (ts TEXT) 桩——fresh DB 建出缺列残表，save_result/health 皆坏；还原为完整 schema。
-- IF NOT EXISTS：prod 既有表（经 migrate_schema 重建）不受影响；全新 DB 得正确 schema。
CREATE TABLE IF NOT EXISTS sti_timeline (
    date TEXT NOT NULL UNIQUE,
    score REAL,
    phase TEXT,
    dimension_limit_up_count REAL,
    dimension_limit_down_count REAL,
    dimension_seal_rate REAL,
    dimension_advance_decline_ratio REAL,
    dimension_promotion_rate REAL,
    dimension_prev_zt_performance REAL,
    dimension_max_boards REAL,
    market_factor REAL,
    confidence TEXT,
    source_ok BOOLEAN DEFAULT 1,
    change_from_yesterday REAL,
    data_updated TEXT,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sti_date ON sti_timeline(date DESC);
CREATE INDEX IF NOT EXISTS idx_sti_phase ON sti_timeline(phase);
