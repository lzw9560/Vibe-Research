-- v1 已建 idx_sti_date/idx_sti_phase；此 v2 原 idx_sti ON ts 引用桩列 ts（v1 还原后 ts 不存在）→ 改 date 兜底（IF NOT EXISTS 无副作用）。
CREATE INDEX IF NOT EXISTS idx_sti_date ON sti_timeline(date DESC);
