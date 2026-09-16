# -*- coding: utf-8 -*-
"""S205 fetch_zt_pool zt_history fallback 测试。

历史日 fetch_zt_pool fallback zt_history snapshot（em_get 实时涨停池历史无）。
zt_history code/name 转成 em_get c/n 格式（score_candidates pool_map 读 c）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def _make_zt_db(tmp_path: Path, date: str = "2026-08-27") -> Path:
    """建 tmp zt_history.db 含 1 行 snapshot。"""
    zt_db = tmp_path / "zt_history.db"
    conn = sqlite3.connect(str(zt_db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS zt_history ("
        "date TEXT, code TEXT, name TEXT, lbc INTEGER, zbc INTEGER, fbt REAL, "
        "fund REAL, zje REAL, p REAL, ltsz REAL, fundamt REAL, hybk TEXT, "
        "snapshot_at TEXT, is_final INTEGER, source TEXT)"
    )
    conn.execute(
        "INSERT INTO zt_history (date,code,name,lbc,zbc,fbt,fund,zje,p,ltsz,fundamt,hybk,snapshot_at,is_final,source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (date, "600519", "茅台", 1, 1, 1.0, 1000.0, 1.0, 1800.0, 10000.0, 1e8,
         "白酒", date, 1, "test"),
    )
    conn.commit()
    conn.close()
    return zt_db


class TestFetchZtPoolZtHistoryFallback:
    def test_historical_date_returns_zt_history_snapshot(self, tmp_path, monkeypatch):
        """历史日 fetch_zt_pool fallback zt_history snapshot（em_get 实时历史无）。"""
        _make_zt_db(tmp_path, "2026-08-27")
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: tmp_path)
        from strategies.first_board.universe import fetch_zt_pool
        pool = fetch_zt_pool("2026-08-27")
        assert len(pool) >= 1
        assert pool[0]["c"] == "600519"  # zt_history code → em_get c 格式
        assert pool[0]["n"] == "茅台"   # zt_history name → em_get n 格式
        assert "lbc" in pool[0]
        assert "p" in pool[0]

    def test_zt_history_code_name_to_c_n_format(self, tmp_path, monkeypatch):
        """zt_history code/name 转成 em_get c/n 格式（score_candidates pool_map 读 c）。"""
        _make_zt_db(tmp_path, "2026-08-27")
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: tmp_path)
        from strategies.first_board.universe import fetch_zt_pool
        pool = fetch_zt_pool("2026-08-27")
        assert all("c" in p for p in pool)
        assert all("n" in p for p in pool)
        assert not any("code" in p for p in pool)  # zt_history code 不残留

    def test_zt_history_none_falls_back_to_em_get(self, tmp_path, monkeypatch):
        """zt_history 无该日 → fallback em_get 实时（mock em_get 返 []）。"""
        _make_zt_db(tmp_path, "2026-08-27")  # 只有 08-27
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: tmp_path)
        # mock em_get 返空（历史日 em_get 无）
        import strategies.first_board.universe as uni
        monkeypatch.setattr(uni, "em_zt_topic_pool", lambda *a, **k: [])
        from strategies.first_board.universe import fetch_zt_pool
        pool = fetch_zt_pool("2026-06-15")  # zt_history 无 06-15
        assert pool == []  # em_get fallback 返空

    def test_no_zt_history_db_falls_back_to_em_get(self, tmp_path, monkeypatch):
        """无 zt_history.db → fallback em_get（当日实时）。"""
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: tmp_path)
        import strategies.first_board.universe as uni
        monkeypatch.setattr(uni, "em_zt_topic_pool", lambda *a, **k: [{"c": "000001", "n": "test"}])
        from strategies.first_board.universe import fetch_zt_pool
        pool = fetch_zt_pool("20260916")
        assert pool == [{"c": "000001", "n": "test"}]
