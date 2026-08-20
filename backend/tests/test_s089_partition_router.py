# -*- coding: utf-8 -*-
"""S089 B5：路由层单元测试。

覆盖：
- ``resolve_partition`` —— date → 正确 (db_path, table_name)
- ``ensure_partition`` —— 幂等建表建索引（两次调用不报错，表 + 3 索引存在）
- ``get_latest_partition`` —— 当年最新月表路由（建几个月表后返回最新）

测试隔离：每个测试用 ``tmp_path`` + monkeypatch 把 ``db_partition_router``
引用的 ``PRIVATE_DATA_DIR`` / ``SEAL_INTRADAY_DIR`` / ``seal_intraday_db_path``
重定向到独立临时目录，避免跨测试共享 conftest 全局 ``VR_DATA_DIR`` 造成的
状态污染。
"""

import os
import sqlite3

import pytest

import db_partition_router as router


@pytest.fixture
def isolated_router_dir(tmp_path, monkeypatch):
    """把路由层引用的数据目录重定向到独立 tmp_path，避免跨测试污染。

    router 在 import 时已 ``from config import PRIVATE_DATA_DIR, ...``，故需
    patch router 模块上的这些绑定（而非 config 模块）。
    """
    data_dir = str(tmp_path / "seal_intraday_data")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setattr(router, "PRIVATE_DATA_DIR", data_dir)
    monkeypatch.setattr(router, "SEAL_INTRADAY_DIR", data_dir)

    def _fake_db_path(year: str) -> str:
        return os.path.join(data_dir, f"seal_intraday_{year}.db")

    monkeypatch.setattr(router, "seal_intraday_db_path", _fake_db_path)
    return data_dir


# ------------------------------------------------------------------------------
# resolve_partition
# ------------------------------------------------------------------------------


class TestResolvePartition:
    def test_2026_08_20(self, isolated_router_dir):
        """'2026-08-20' → 正确路径 + 表名。"""
        db_path, table = router.resolve_partition("2026-08-20")
        assert db_path == os.path.join(isolated_router_dir, "seal_intraday_2026.db")
        assert table == "seal_intraday_snapshots_202608"
        assert "seal_intraday_2026.db" in db_path
        assert os.path.dirname(db_path) == isolated_router_dir

    def test_跨年分库(self, isolated_router_dir):
        """2026 与 2027 应路由到不同分库。"""
        db_2026, table_2026 = router.resolve_partition("2026-12-31")
        db_2027, table_2027 = router.resolve_partition("2027-01-04")
        assert db_2026 != db_2027
        assert "2026" in db_2026
        assert "2027" in db_2027
        # 同目录不同年库文件
        assert os.path.dirname(db_2026) == os.path.dirname(db_2027) == isolated_router_dir
        # 同年不同月 → 同库不同表
        assert table_2026 == "seal_intraday_snapshots_202612"
        assert table_2027 == "seal_intraday_snapshots_202701"

    def test_纯映射不开库(self, isolated_router_dir):
        """resolve 不打开 DB / 不建文件。"""
        db_path, _ = router.resolve_partition("2026-08-20")
        assert not os.path.exists(db_path)


# ------------------------------------------------------------------------------
# ensure_partition
# ------------------------------------------------------------------------------


class TestEnsurePartition:
    def test_idempotent(self, isolated_router_dir):
        """调两次不报错，表 + 3 索引存在。"""
        db_path, table = router.ensure_partition("2026-08-20")
        assert os.path.exists(db_path)
        # 二次调用不报错
        db_path2, table2 = router.ensure_partition("2026-08-20")
        assert db_path == db_path2
        assert table == table2

        # 验证表 + 3 索引存在
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            assert table in tables

            indexes = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                (table,)
            ).fetchall()}
            # idx_YYYYMM_date_code / idx_YYYYMM_code_ts / idx_YYYYMM_ts
            assert "idx_202608_date_code" in indexes
            assert "idx_202608_code_ts" in indexes
            assert "idx_202608_ts" in indexes
        finally:
            conn.close()

    def test_s070_low_price_limit_pct_columns(self, isolated_router_dir):
        """分表 DDL 含 low_price + limit_pct 字段（兼容 S070 R6.1）。"""
        db_path, table = router.ensure_partition("2026-08-20")
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            # S070 R6.1 已落地的两列
            assert "low_price" in cols
            assert "limit_pct" in cols
            # S055 基础字段也在
            assert {"ts", "date", "code", "name", "price", "seal_amount"} <= cols
        finally:
            conn.close()

    def test_可写入(self, isolated_router_dir):
        """建表后可直接 INSERT 行。"""
        db_path, table = router.ensure_partition("2026-08-20")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                f"INSERT INTO {table} (ts, date, code, name) VALUES (?, ?, ?, ?)",
                ("2026-08-20T10:00:00", "2026-08-20", "000001", "平安银行"),
            )
            conn.commit()
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert cnt == 1
        finally:
            conn.close()

    def test_跨月独立表(self, isolated_router_dir):
        """不同月建独立表（不混入同表）。"""
        db_path_08, table_08 = router.ensure_partition("2026-08-20")
        db_path_09, table_09 = router.ensure_partition("2026-09-05")
        assert db_path_08 == db_path_09  # 同年同库
        assert table_08 != table_09
        conn = sqlite3.connect(db_path_08)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            assert table_08 in tables
            assert table_09 in tables
        finally:
            conn.close()


# ------------------------------------------------------------------------------
# get_latest_partition
# ------------------------------------------------------------------------------


class TestGetLatestPartition:
    def test_无表返_None(self, isolated_router_dir):
        """当年库无分表时返回 None（不臆造）。"""
        import datetime as _dt
        year = str(_dt.date.today().year)
        db_path = router.seal_intraday_db_path(year)
        # 全新隔离目录下当年库不存在 → None
        assert not os.path.exists(db_path)
        result = router.get_latest_partition()
        assert result is None

    def test_返回最新月表(self, isolated_router_dir):
        """建几个月分表后返回最新月表。"""
        import datetime as _dt
        year = str(_dt.date.today().year)
        router.ensure_partition(f"{year}-03-15")  # YYYYMM = {year}03
        router.ensure_partition(f"{year}-01-05")  # YYYYMM = {year}01
        router.ensure_partition(f"{year}-06-20")  # YYYYMM = {year}06

        result = router.get_latest_partition()
        assert result is not None
        db_path, table = result
        assert db_path == router.seal_intraday_db_path(year)
        # 最大月应为 06
        assert table == f"seal_intraday_snapshots_{year}06"

    def test_返回值可直接查(self, isolated_router_dir):
        """返回的 (db_path, table) 可直接用于 SELECT MAX(date)。"""
        import datetime as _dt
        year = str(_dt.date.today().year)
        # 建一个表并写入两行
        db_path, table = router.ensure_partition(f"{year}-08-20")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                f"INSERT INTO {table} (ts, date, code) VALUES "
                f"('{year}-08-20T09:30:00','{year}-08-20','000001'),"
                f"('{year}-08-20T10:00:00','{year}-08-20','000002')"
            )
            conn.commit()
        finally:
            conn.close()

        result = router.get_latest_partition()
        assert result is not None
        db_path2, table2 = result
        conn = sqlite3.connect(db_path2)
        try:
            max_date = conn.execute(f"SELECT MAX(date) FROM {table2}").fetchone()[0]
            assert max_date == f"{year}-08-20"
        finally:
            conn.close()
