-- S055 v1：盘中封单时序快照表。
-- 交易时段每 60s 轮询 em_zt_topic_pool 写入，单日规模 ≤ 涨停池 150 只 × 240 分钟 ≈ 3.6 万行。
-- 索引：(date, code) 主查询 + (code, ts) 单股时序 + ts 范围扫描。
CREATE TABLE IF NOT EXISTS seal_intraday_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                   -- ISO8601 时间戳
    date TEXT NOT NULL,                -- 交易日 YYYY-MM-DD
    code TEXT NOT NULL,
    name TEXT,
    pool TEXT,                          -- 池类型：zt/yzt/zb
    price REAL,
    seal_amount REAL,                    -- 封单额（元）
    open_count REAL,                     -- 开板次数（zbc）
    first_seal_time REAL,               -- 首次封板时间（fbt）
    consec_boards REAL,                 -- 连板数（lbc）
    sector TEXT,                         -- 行业（hybk）
    float_market_cap REAL,              -- 流通市值（元，tencent_quote 补充）
    index_5min_change REAL,             -- 大盘 5 分钟跌幅（C4 输入）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_seal_intraday_date_code ON seal_intraday_snapshots(date, code);
CREATE INDEX IF NOT EXISTS idx_seal_intraday_code_ts ON seal_intraday_snapshots(code, ts);
CREATE INDEX IF NOT EXISTS idx_seal_intraday_ts ON seal_intraday_snapshots(ts);

-- S055 v2：炸板预警历史记录表（规则触发/解除 + 去重冷却）
CREATE TABLE IF NOT EXISTS bomb_alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                   -- 触发时间戳
    date TEXT NOT NULL,                 -- 交易日
    code TEXT NOT NULL,
    name TEXT,
    rule_id TEXT NOT NULL,              -- C1/C2/C3/C4/C5/C6
    alert_level TEXT NOT NULL,          -- yellow/red
    condition_text TEXT,                -- 触发条件描述
    input_snapshot TEXT,                -- 输入值快照 JSON（依据链）
    data_status TEXT DEFAULT 'ok',     -- ok/missing/degraded
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_bomb_alert_date_code ON bomb_alert_history(date, code);
CREATE INDEX IF NOT EXISTS idx_bomb_alert_ts ON bomb_alert_history(ts);
