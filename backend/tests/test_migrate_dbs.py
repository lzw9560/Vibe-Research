# -*- coding: utf-8 -*-
"""S037: migrate_dbs.py 单测——构造 tmp 旧库, 迁移, 验证行数 + .bak + 幂等."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "migrate_dbs.py"


def _load_migrate_module(tmp_path):
    """Load migrate_dbs.py with _REPO_ROOT patched to tmp_path."""
    spec = importlib.util.spec_from_file_location("migrate_dbs_test", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._REPO_ROOT = tmp_path
    return mod


def _make_test_db(path: Path, tables: dict):
    """Create a test SQLite db with given tables and row counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    for table, rows in tables.items():
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        for i in range(rows):
            conn.execute(f"INSERT INTO {table} (id) VALUES ({i})")
    conn.commit()
    conn.close()


def test_migrate_basic(tmp_path):
    """Migrate one db: old -> new, row counts match, old renamed .bak."""
    mod = _load_migrate_module(tmp_path)
    old_dir = tmp_path / "backend" / "limitup_screener"
    _make_test_db(old_dir / "vibe_research.db", {"gene_scores": 5, "migrations": 2})

    spec = {
        "name": "gene_scores",
        "old": "backend/limitup_screener/vibe_research.db",
        "new": ".vibe-research/gene_scores.db",
        "tables": ["gene_scores", "migrations"],
    }
    report = mod.migrate_db(spec)

    assert report["status"] == "migrated"
    assert report["old_counts"]["gene_scores"] == 5
    assert report["new_counts"]["gene_scores"] == 5
    assert (tmp_path / ".vibe-research" / "gene_scores.db").exists()
    assert not (old_dir / "vibe_research.db").exists()
    assert (old_dir / "vibe_research.db.bak").exists()


def test_migrate_idempotent(tmp_path):
    """Second run: skip because row counts match."""
    mod = _load_migrate_module(tmp_path)
    old_dir = tmp_path / "backend" / "limitup_screener"
    _make_test_db(old_dir / "vibe_research.db", {"gene_scores": 3, "migrations": 1})

    spec = {
        "name": "gene_scores",
        "old": "backend/limitup_screener/vibe_research.db",
        "new": ".vibe-research/gene_scores.db",
        "tables": ["gene_scores", "migrations"],
    }
    report1 = mod.migrate_db(spec)
    assert report1["status"] == "migrated"

    bak = old_dir / "vibe_research.db.bak"
    bak.rename(old_dir / "vibe_research.db")

    report2 = mod.migrate_db(spec)
    assert report2["status"] == "skip: already migrated (row counts match)"


def test_migrate_skip_missing_old(tmp_path):
    """Old db not found -> skip."""
    mod = _load_migrate_module(tmp_path)
    spec = {
        "name": "gene_scores",
        "old": "backend/limitup_screener/vibe_research.db",
        "new": ".vibe-research/gene_scores.db",
        "tables": ["gene_scores", "migrations"],
    }
    report = mod.migrate_db(spec)
    assert report["status"] == "skip: old db not found"


def test_migrate_overwrite_empty_new(tmp_path):
    """New db exists but all data tables empty -> overwrite (app bootstrapped empty)."""
    mod = _load_migrate_module(tmp_path)
    old_dir = tmp_path / "backend" / "data"
    _make_test_db(old_dir / "winrate.db", {"winrate_records": 10, "migrations": 2})

    new_dir = tmp_path / ".vibe-research"
    _make_test_db(new_dir / "winrate.db", {"winrate_records": 0, "migrations": 2})

    spec = {
        "name": "winrate",
        "old": "backend/data/winrate.db",
        "new": ".vibe-research/winrate.db",
        "tables": ["winrate_records", "migrations"],
    }
    report = mod.migrate_db(spec)
    assert report["status"] == "migrated"
    assert report["new_counts"]["winrate_records"] == 10
    assert (old_dir / "winrate.db.bak").exists()


def test_migrate_dry_run(tmp_path):
    """Dry run: no actual file changes."""
    mod = _load_migrate_module(tmp_path)
    old_dir = tmp_path / "backend" / "limitup_screener"
    _make_test_db(old_dir / "vibe_research.db", {"gene_scores": 7, "migrations": 1})

    spec = {
        "name": "gene_scores",
        "old": "backend/limitup_screener/vibe_research.db",
        "new": ".vibe-research/gene_scores.db",
        "tables": ["gene_scores", "migrations"],
    }
    report = mod.migrate_db(spec, dry=True)
    assert report["status"] == "dry-run: would migrate"
    assert not (tmp_path / ".vibe-research" / "gene_scores.db").exists()
    assert (old_dir / "vibe_research.db").exists()
