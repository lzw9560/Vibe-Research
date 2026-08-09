-- S040 v2: 加 data_source + missing_factors 列，区分 eastmoney_live / kline_rebuild 数据源
ALTER TABLE gene_scores ADD COLUMN data_source TEXT DEFAULT 'eastmoney_live';
ALTER TABLE gene_scores ADD COLUMN missing_factors TEXT DEFAULT '';
