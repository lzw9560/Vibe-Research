-- S063 T4 补齐：sti_timeline 加 raw_break_rate 列，盘前 T-1 炸板率不再显示 --
-- market._emotion 每次都能算出 break_rate = zb_count/(zt_count+zb_count)，
-- 但盘前路径走 DB 读 T-1 行；旧迁移（20250613-002）主动移除了 dimension_break_rate 列，
-- 导致 _market_emotion_from_ctx 恒 out["break_rate"] = None → 简报显示 "--"。
-- 本迁移新增 raw_break_rate 顶层列（不进 STI_WEIGHTS 加权维度），由 compute 落库、_market_emotion_from_ctx 直读。
-- 幂等由 MigrationManager 的 version 去重保证；ALTER 对已存在列会报错，故仅在新库/未应用时执行。
ALTER TABLE sti_timeline ADD COLUMN raw_break_rate REAL;
-- 历史回填留空（raw 值需从 market._emotion 重算，不在迁移里做）
