"""V1 初始 schema：STI 时间线表。"""

VERSION = "20250613-001"
NAME = "create_sti_timeline"

SQL = """
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
"""
