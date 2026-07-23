CREATE INDEX IF NOT EXISTS idx_sti_score_date
    ON sti_timeline (score, date DESC);
