CREATE INDEX IF NOT EXISTS idx_winrate_sector_entry_date
    ON winrate_records (sector, entry_date DESC);

CREATE INDEX IF NOT EXISTS idx_winrate_strategy_entry_date
    ON winrate_records (strategy_used, entry_date DESC);
