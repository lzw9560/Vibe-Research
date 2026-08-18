-- S070 R6.1：seal_intraday_snapshots 加 low_price（分时最低价）+ limit_pct（涨停涨幅%）
-- low_price：tencent_quote 的 low 字段（vals[34]），60s 粒度快照时的区间低点
-- limit_pct：em_zt_topic_pool 的 zdp 字段（涨幅%），用于 R7 反推涨停价
--   limit_price = price / (1 + limit_pct/100)
--   （首封时刻 price≈涨停价，但用 limit_pct 反推更稳，避免 price 采样精度问题）
-- 缺失时 NULL，不臆造（与 S055 既有 data_status=degraded 范式一致）
ALTER TABLE seal_intraday_snapshots ADD COLUMN low_price REAL;
ALTER TABLE seal_intraday_snapshots ADD COLUMN limit_pct REAL;
