CREATE TABLE IF NOT EXISTS gene_scores (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    total_score REAL,
    factor_premium_rate REAL,
    factor_red_rate REAL,
    factor_seal_rate REAL,
    factor_rebound_rate REAL,
    factor_freq_score REAL,
    wilson_adjusted REAL,
    qualify INTEGER,
    high_gene INTEGER,
    zt_count_250d INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, code)
);

CREATE INDEX IF NOT EXISTS idx_gene_scores_date ON gene_scores(date);
CREATE INDEX IF NOT EXISTS idx_gene_scores_code ON gene_scores(code);
CREATE INDEX IF NOT EXISTS idx_gene_scores_total_score ON gene_scores(total_score);
