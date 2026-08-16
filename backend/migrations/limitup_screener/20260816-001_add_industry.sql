-- S066 Q16（grill 2026-08-16）：板块数据来源实测修正——gene_scores 原无 industry 列
-- （原 §5.3 SQL 引用不存在的 industry_code）。加 industry 列供 (date, industry) 聚合板块涨停数；
-- code_industry 静态映射表（clist f100 一次性回填，§5.3 实现路径 step 1）。
-- 与 20260809-001 同模式：v1 CREATE 不含此列，由本迁移 ALTER ADD（避免 duplicate column；
-- fresh DB 按序跑 v1→…→本迁移亦得 industry 列）。
ALTER TABLE gene_scores ADD COLUMN industry TEXT DEFAULT '';
CREATE TABLE IF NOT EXISTS code_industry (
    code TEXT PRIMARY KEY,
    name TEXT,
    industry TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_gene_scores_industry ON gene_scores(industry);
