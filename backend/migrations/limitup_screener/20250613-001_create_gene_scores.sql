-- 基础表：涨停基因得分。v1 建完整列（date..zt_count_250d + updated_at + PK(date,code)）。
-- data_source / missing_factors 由 20260809-001（v4）ALTER ADD，此处不含（避免 duplicate column）。
-- IF NOT EXISTS：prod 既有完整表不受影响；全新 DB（测试/新部署）得正确 schema（修复"no such column: date"）。
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
