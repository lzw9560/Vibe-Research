CREATE TABLE IF NOT EXISTS winrate_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    strategy_used TEXT,
    entry_date TEXT NOT NULL,
    entry_price REAL,
    exit_date TEXT NOT NULL,
    exit_price REAL,
    return_pct REAL,
    is_win INTEGER,
    gene_score REAL,
    sti_label TEXT,
    sector TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_winrate_entry_date ON winrate_records(entry_date);
CREATE INDEX IF NOT EXISTS idx_winrate_strategy ON winrate_records(strategy_used);
CREATE INDEX IF NOT EXISTS idx_winrate_sector ON winrate_records(sector);
CREATE INDEX IF NOT EXISTS idx_winrate_exit_date ON winrate_records(exit_date);
CREATE INDEX IF NOT EXISTS idx_winrate_stock_code ON winrate_records(stock_code);
