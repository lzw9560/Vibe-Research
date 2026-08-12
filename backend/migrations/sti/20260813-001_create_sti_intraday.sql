-- S063 T1：盘中情绪采样表。
-- 存储盘中按黄金窗口采样的 4 维度数据 + 综合分数 + 趋势 + T-1 基线 + T+1 预判/校准。
-- 自动清理 >60 交易日（由 data.py prune_intraday 负责）。
CREATE TABLE IF NOT EXISTS sti_intraday (
    date        TEXT NOT NULL,
    time        TEXT NOT NULL,
    zt_count    REAL,
    seal_rate   REAL,
    break_rate  REAL,
    ad_ratio    REAL,
    score       REAL,
    trend       TEXT,
    t1_baseline REAL,
    projected_t1_score    REAL,
    projected_t1_weather  TEXT,
    actual_score          REAL,
    PRIMARY KEY (date, time)
);
CREATE INDEX IF NOT EXISTS idx_sti_intraday_date ON sti_intraday(date DESC);
