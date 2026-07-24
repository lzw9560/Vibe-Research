CREATE TABLE IF NOT EXISTS fuse_pardon_records (
    id TEXT PRIMARY KEY,
    strategy_code TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    enabled_by TEXT NOT NULL,
    enabled_ip TEXT,
    approved_by TEXT NOT NULL,
    max_position_pct REAL NOT NULL DEFAULT 0.35,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    reason TEXT,
    is_active BOOLEAN DEFAULT 1,
    revoked_at TEXT,
    revoked_by TEXT,
    outcome_json TEXT,
    created_at_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pardon_strategy_code ON fuse_pardon_records(strategy_code);
CREATE INDEX IF NOT EXISTS idx_pardon_is_active ON fuse_pardon_records(is_active);
CREATE INDEX IF NOT EXISTS idx_pardon_expires_at ON fuse_pardon_records(expires_at);
