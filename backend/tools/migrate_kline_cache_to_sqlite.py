# -*- coding: utf-8 -*-
"""一次性迁移脚本：baostock_kline_cache.json (482MB) → baostock_kline_cache.db (SQLite)。

**背景**：全量 json.loads 482MB → 2.19GB Python dict 常驻（6 处模块级 cache 叠加
最坏 8.8GB）。改 SQLite per-code 查（~0 常驻，~2ms/查）。本脚本手动迁移，避免
生产首次 get_bars 触发 2.19GB 峰值。

**用法**::

    cd backend && .venv/bin/python -m tools.migrate_kline_cache_to_sqlite

迁移幂等——SQLite 已有数据跳过（除非 --force）。迁移完可删 JSON（或保留备份）。

工程底线：不臆造——JSON 不在/损坏返 0 不崩。私有数据目录（.vibe-research/）不进 git。
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from engine.kline_cache_store import _db_path, _json_path, _get_conn, _ensure_migrated
from vr_paths import resolve_data_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_logger = logging.getLogger("migrate_kline_cache")


def main(force: bool = False) -> int:
    jp = _json_path()
    dbp = _db_path()
    if not jp.exists():
        _logger.warning("JSON 不在 %s，无需迁移（首次部署 SQLite 即源）", jp)
        return 0
    # 已迁移检测
    conn = _get_conn()
    n = conn.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
    if n > 0 and not force:
        _logger.info("SQLite 已有 %d stocks（--force 强制重导），跳过", n)
        return 0
    if force:
        _logger.info("--force：清表重导...")
        conn.execute("DELETE FROM kline")

    _logger.info("迁移 %s → %s（482MB → ~2GB 峰值，~30s）...", jp.name, dbp.name)
    t0 = time.time()
    data = json.loads(jp.read_bytes())
    _logger.info("JSON 解析完成：%d stocks，%.1fs，开始批量 INSERT", len(data), time.time() - t0)

    # 批量 INSERT（executemany 单事务）
    conn.executemany(
        "INSERT OR REPLACE INTO kline (code, bars_json) VALUES (?, ?)",
        ((code, json.dumps(bars, ensure_ascii=False)) for code, bars in data.items()),
    )
    _logger.info("INSERT 完成，%.1fs 总耗时", time.time() - t0)

    # 验证
    n_after = conn.execute("SELECT COUNT(*) FROM kline").fetchone()[0]
    # 抽检 1 个 code
    sample_code = next(iter(data))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (sample_code,)).fetchone()
    bars_check = json.loads(row[0]) if row else []
    _logger.info("验证：SQLite %d stocks，抽检 %s = %d bars（JSON %d bars，%s）",
                 n_after, sample_code, len(bars_check), len(data[sample_code]),
                 "✓ 一致" if len(bars_check) == len(data[sample_code]) else "✗ 不一致")

    db_size = dbp.stat().st_size / 1e6
    json_size = jp.stat().st_size / 1e6
    _logger.info("done: JSON %.0fMB → SQLite %.0fMB，stocks=%d", json_size, db_size, n_after)
    return 0


if __name__ == "__main__":
    force = "--force" in sys.argv
    raise SystemExit(main(force))
