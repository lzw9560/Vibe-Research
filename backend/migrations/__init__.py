"""轻量级数据库迁移系统 —— 适用于多 SQLite 数据库场景。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class MigrationManager:
    """数据库迁移管理器。"""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._ensure_migrations_table()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_migrations_table(self) -> None:
        """确保 migrations 表存在。"""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def get_applied_versions(self) -> set[str]:
        """获取已应用的迁移版本。"""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT version FROM migrations ORDER BY id")
            return {row["version"] for row in cursor.fetchall()}
        finally:
            conn.close()

    def apply_migration(self, version: str, name: str, sql: str) -> None:
        """应用单个迁移。"""
        conn = self._get_connection()
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO migrations (version, name) VALUES (?, ?)",
                (version, name)
            )
            conn.commit()
        finally:
            conn.close()

    def upgrade(self, migrations: list[dict[str, Any]]) -> None:
        """执行待处理的迁移。"""
        applied = self.get_applied_versions()
        for migration in migrations:
            version = migration["version"]
            if version in applied:
                continue
            self.apply_migration(
                version=version,
                name=migration["name"],
                sql=migration["sql"]
            )
