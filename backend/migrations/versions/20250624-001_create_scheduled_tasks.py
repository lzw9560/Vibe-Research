"""V3 创建定时任务表：scheduled_tasks + scheduled_task_runs。"""

VERSION = "20250624-001"
NAME = "create_scheduled_tasks"

SQL = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    task_type TEXT NOT NULL,
    cron_expr TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    notify_on_success INTEGER DEFAULT 0,
    notify_on_failure INTEGER DEFAULT 1,
    last_run_at TEXT,
    last_run_status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduled_task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    result TEXT DEFAULT '{}',
    error TEXT,
    FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_enabled ON scheduled_tasks(enabled);
CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task_id ON scheduled_task_runs(task_id, started_at DESC);
"""
