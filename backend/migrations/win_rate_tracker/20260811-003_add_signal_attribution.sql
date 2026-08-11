-- S050 W0 行为闭环：winrate_records 加信号归因 5 列（全可空，向前兼容）
-- signal_source: funnel_candidate | strategy_hit | feeling | NULL(legacy)
-- signal_ref: 来源引用（funnel:final / 战法码 / 空）
-- edge_family: momentum_premium | mean_reversion | ''（后端推断）
-- target_holding_period: T+1 | 20-60d | ''（后端推断）
-- attention_mode: A | B | C（用户自填，缺省 A）

ALTER TABLE winrate_records ADD COLUMN signal_source TEXT;
ALTER TABLE winrate_records ADD COLUMN signal_ref TEXT;
ALTER TABLE winrate_records ADD COLUMN edge_family TEXT;
ALTER TABLE winrate_records ADD COLUMN target_holding_period TEXT;
ALTER TABLE winrate_records ADD COLUMN attention_mode TEXT;
