CREATE INDEX IF NOT EXISTS idx_gene_scores_date_total_score
    ON gene_scores (date, total_score DESC);
