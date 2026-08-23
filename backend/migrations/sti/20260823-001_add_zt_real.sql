-- T18（S094 S4）：sti_timeline 加 zt_real 列（真实涨停数，akshare legu 源） --
-- market._sentiment 每次都能取到 zt_real（_num(d.get("真实涨停"))，market.py:76），
-- 但 STIEngine.compute 只读 up/down/active，把 zt_real 丢了（根本没落库）。
-- 本迁移新增 zt_real 顶层列（不进 STI_WEIGHTS 加权维度），由 compute 落库、
-- _market_emotion_from_ctx 直读（raw 计数，不 /100）。
-- 幂等由 MigrationManager 的 version 去重保证；ALTER 对已存在列会报错，故仅在新库/未应用时执行。
ALTER TABLE sti_timeline ADD COLUMN zt_real REAL;
-- 历史行 NULL（raw 值需 _sentiment 最新日才有；akshare legu 无法查历史，不在迁移里回填）
