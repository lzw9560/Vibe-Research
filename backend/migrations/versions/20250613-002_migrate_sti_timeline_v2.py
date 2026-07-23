"""V2 迁移 STI schema：移除 break_rate，重命名 momentum → change_from_yesterday，新增 data_updated。"""

VERSION = "20250613-002"
NAME = "migrate_sti_timeline_v2"

SQL = """
-- 检查是否需要迁移
PRAGMA table_info(sti_timeline);
"""

# 实际迁移逻辑在 MigrationManager 中处理
# 这里只记录版本，具体 SQL 在代码中动态生成
