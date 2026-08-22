-- S094 席位画像宽表：合并 seat_engine（链路 A）与 hot_money_seats（链路 B）两套 JSON 持久化。
-- PK = seat_name。A 字段非空（seat_engine 冷启动写入），B 字段可空（hot_money_seats 周更写入）。
-- 旧文件：backend/seat_profiles.json（A）与 .vibe-research/hot_money_seats.json（B）均已废弃。
CREATE TABLE IF NOT EXISTS seat_profiles (
    seat_name TEXT PRIMARY KEY,
    -- 链路 A 字段（seat_engine）
    total_appearances INTEGER DEFAULT 0,
    total_buy_amt REAL DEFAULT 0.0,
    total_sell_amt REAL DEFAULT 0.0,
    net_amt REAL DEFAULT 0.0,
    avg_buy_amt REAL DEFAULT 0.0,
    avg_sell_amt REAL DEFAULT 0.0,
    stock_cooldown INTEGER DEFAULT 0,
    last_seen TEXT,
    seat_type TEXT,
    -- 链路 B 字段（hot_money_seats）
    next_day_sell_rate REAL,
    appearance_count INTEGER,
    confidence TEXT,
    source TEXT,
    note TEXT,
    -- 通用
    updated_at TEXT
);
