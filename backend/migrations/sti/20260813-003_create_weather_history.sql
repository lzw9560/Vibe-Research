-- S065：weather_history 持久化表。
-- 每日盘后落 weather_state 快照 + 五因子明细，为 WR-Workflow W1 证据层提供可回放的真地基。
-- 幂等（IF NOT EXISTS），同 sti_intraday 迁移范式。
CREATE TABLE IF NOT EXISTS weather_history (
    date                TEXT NOT NULL PRIMARY KEY,
    weather_state       TEXT,          -- 晴天/阴天/极端反弹/暴风雨/未知
    composite_score     REAL,          -- 五因子加权综合分
    sti_score           REAL,
    risk_score          REAL,
    sector_continuity   REAL,
    capital_momentum    REAL,
    public_sentiment    REAL,
    phase               TEXT,          -- STI phase（启动/分歧/...）
    confidence          TEXT,          -- 高/中/低
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_weather_history_date ON weather_history(date DESC);
