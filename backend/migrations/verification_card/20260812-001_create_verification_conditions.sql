-- S060 v1：明日验证条件对账卡持久化表。
-- 盘后生成条件（pending）→ T+1 盘后对账（met_up/met_down/within/data_missing）。
CREATE TABLE IF NOT EXISTS verification_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                  -- 生成日 YYYY-MM-DD
    metric TEXT NOT NULL,               -- 指标名（zt_count/break_rate/max_boards/sector_zt_count/yzt_premium）
    subject TEXT,                        -- 主体（主线板块名/空）
    baseline REAL,                       -- 今日基准值
    threshold_up REAL,                   -- 上行阈值
    threshold_down REAL,                 -- 下行阈值
    actual REAL,                         -- T+1 实际值（对账后填）
    status TEXT DEFAULT 'pending',      -- pending/met_up/met_down/within/data_missing
    note TEXT,                           -- 附加说明（口径/降级标注）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_verification_date ON verification_conditions(date);
CREATE INDEX IF NOT EXISTS idx_verification_status ON verification_conditions(status);
