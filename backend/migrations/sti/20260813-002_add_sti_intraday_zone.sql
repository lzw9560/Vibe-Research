-- S063 补：sti_intraday 增 zone 列（色带 green/yellow/red）。
-- 原 001 迁移漏了 zone 列——采样器在 ring buffer 算 zone 但 save_intraday 没持久化，
-- 导致 DB 读出的 snapshot 缺 zone，前端色带显示失效。
ALTER TABLE sti_intraday ADD COLUMN zone TEXT;
