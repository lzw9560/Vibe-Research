# -*- coding: utf-8 -*-
"""S089 E2：并发压测——ThreadPool(20) 并发写+读 seal_intraday 分表。

验证 WAL + busy_timeout 加固在软并发下不出现 ``database is locked``：

- 写入：20 线程各写 5 条快照（不同 code，同 date），共 100 行
- 读取：同时 20 线程各查一次 ``get_snapshots_by_code``
- 验证：无 ``sqlite3.OperationalError: database is locked``
- 验证：写入的 100 条全部能读到

测试隔离：tmp_path + monkeypatch 把 ``db_partition_router`` 路由常量/函数
重定向到独立临时目录（同 test_s089_partition_router 的 isolated_router_dir 模式）。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

import db_partition_router as router


@pytest.fixture
def isolated_concurrency_env(tmp_path, monkeypatch):
    """并发压测环境：路由层重定向到独立 tmp_path + collector 路由绑定刷新。

    collector 从 router ``from db_partition_router import resolve_partition,
    ensure_partition``——同函数对象，patch router.seal_intraday_db_path 后
    走 router 全局命名空间自动生效（无需额外 patch collector 绑定）。
    """
    data_dir = str(tmp_path / "seal_concurrency")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setattr(router, "PRIVATE_DATA_DIR", data_dir)
    monkeypatch.setattr(router, "SEAL_INTRADAY_DIR", data_dir)

    def _fake_db_path(year: str) -> str:
        return os.path.join(data_dir, f"seal_intraday_{year}.db")

    monkeypatch.setattr(router, "seal_intraday_db_path", _fake_db_path)
    return data_dir


def _make_snapshot(code: str, date: str, ts_suffix: str) -> dict:
    """构造一条快照行（字段对齐 seal_intraday_snapshots 分表）。"""
    return {
        "ts": f"{date}T10:{ts_suffix}:00",
        "date": date,
        "code": code,
        "name": f"测试股{code}",
        "pool": "zt",
        "price": 10.0,
        "seal_amount": 1e8,
        "open_count": 0,
        "first_seal_time": 93500,
        "consec_boards": 1,
        "sector": "测试",
        "float_market_cap": 1e10,
        "index_5min_change": 0.0,
        "low_price": 9.5,
        "limit_pct": 10.0,
    }


class TestConcurrency:
    def test_20_threads_write_and_read_no_lock(
        self, isolated_concurrency_env,
    ):
        """ThreadPool(20) 并发写+读，验证无 ``database is locked``，100 行全读回。

        设计：
        - 20 写线程各写 5 条（code 不同，date 同），100 行落同一月分表
        - 20 读线程同时各查一次 get_snapshots_by_code（读老 code，验证不报锁错）
        - 写完后主线程再读全部 100 条，验证完整性
        """
        from risk.seal_intraday_collector import save_snapshots, get_snapshots_by_code

        date = "2026-08-20"  # 同一日期 → 同一分表 seal_intraday_snapshots_202608
        # 100 个不同 code（code + 线程号 + 行号，保证唯一）
        codes = [f"{i:06d}" for i in range(100)]

        write_errors: list[Exception] = []
        read_errors: list[Exception] = []
        read_results: dict[str, list] = {}

        def _writer(thread_idx: int) -> int:
            """写线程：写 5 条（code = thread_idx*5 .. thread_idx*5+4）。"""
            try:
                start = thread_idx * 5
                my_codes = codes[start:start + 5]
                rows = []
                for j, code in enumerate(my_codes):
                    rows.append(_make_snapshot(code, date, f"{25 + j:02d}"))
                n = save_snapshots(rows)
                return n
            except Exception as e:
                write_errors.append(e)
                return 0

        def _reader(thread_idx: int) -> None:
            """读线程：查一个老 code（00 + thread_idx）的时序，验证不报锁错。

            读的 code 在写之前已建分表（save_snapshots 内部 ensure_partition），
            但具体 code 可能还没写入 → 返空也合规（验证的是"不报锁错"，非数据）。
            """
            try:
                code = f"{thread_idx:06d}"
                rows = get_snapshots_by_code(code, date)
                read_results[code] = rows
            except Exception as e:
                read_errors.append(e)

        # 先 ensure 一次分表（避免首个写线程建表时其他线程并发读 no-such-table）
        router.ensure_partition(date)

        # 并发跑 20 写 + 20 读（同一 pool，混跑）
        with ThreadPoolExecutor(max_workers=20) as pool:
            write_futs = [pool.submit(_writer, i) for i in range(20)]
            read_futs = [pool.submit(_reader, i) for i in range(20)]

            written_total = 0
            for f in as_completed(write_futs):
                written_total += f.result()
            for f in as_completed(read_futs):
                f.result()  # 触发异常重抛（如有）

        # 验证：无 database is locked
        assert not write_errors, f"写线程报错：{write_errors}"
        assert not read_errors, f"读线程报错：{read_errors}"

        # 验证：写入行数 = 100
        assert written_total == 100, f"期望写入 100 行，实际 {written_total}"

        # 验证：100 条全部能读到（写完后主线程逐个查）
        found = 0
        for code in codes:
            rows = get_snapshots_by_code(code, date)
            if rows:
                found += 1
                assert rows[0]["low_price"] == 9.5  # 字段值正确
                assert rows[0]["limit_pct"] == 10.0
        assert found == 100, f"100 条写入只读回 {found} 条"

    def test_mixed_dates_partitioned_concurrent_write(self, isolated_concurrency_env):
        """跨月分表并发写——不同线程写不同月分表，验证分库分表隔离无锁。

        3 个月分表（202608/202609/202610）各 10 线程并发写，验证分表写入不互相
        阻塞（不同分表 = 不同连接，WAL 模式下互不干扰）。
        """
        from risk.seal_intraday_collector import save_snapshots, get_snapshots_by_code

        dates = ["2026-08-20", "2026-09-15", "2026-10-10"]
        codes_per_date = {d: [f"{i:06d}" for i in range(10)] for d in dates}
        errors: list[Exception] = []

        def _writer(date: str, code: str) -> int:
            try:
                row = _make_snapshot(code, date, "30")
                return save_snapshots([row])
            except Exception as e:
                errors.append(e)
                return 0

        # 先 ensure 3 个月分表
        for d in dates:
            router.ensure_partition(d)

        # 30 个写任务（3 月 × 10 code）并发跑
        with ThreadPoolExecutor(max_workers=20) as pool:
            futs = []
            for d in dates:
                for code in codes_per_date[d]:
                    futs.append(pool.submit(_writer, d, code))
            total = sum(f.result() for f in as_completed(futs))

        assert not errors, f"并发写报错：{errors}"
        assert total == 30, f"期望 30 行，实际 {total}"

        # 验证：每月分表各 10 条
        for d in dates:
            for code in codes_per_date[d]:
                rows = get_snapshots_by_code(code, d)
                assert len(rows) == 1, f"{d} {code} 应有 1 行，实 {len(rows)}"

    def test_busy_timeout_set_on_partition_db(self, isolated_concurrency_env):
        """分库连接 PRAGMA busy_timeout=5000 已落地（WAL + busy_timeout 加固验收 A2）。"""
        from risk.seal_intraday_collector import save_snapshots

        date = "2026-08-20"
        save_snapshots([_make_snapshot("000001", date, "30")])

        # resolve_partition → db_path
        db_path, table = router.resolve_partition(date)
        conn = sqlite3.connect(db_path)
        try:
            jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
            # save_snapshots 用 get_healthy_conn 建 WAL；VACUUM/查可能切回 default
            # 但首次写后应落 wal。至少 journal_mode 不为 delete（WAL 持久化）。
            assert jm in ("wal",), f"journal_mode 应为 wal，实际 {jm}"
        finally:
            conn.close()

        # 通过 get_healthy_conn 打开验证 busy_timeout=5000
        from db_health import get_healthy_conn
        conn = get_healthy_conn(db_path)
        try:
            bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert bt == 5000, f"busy_timeout 应为 5000，实际 {bt}"
        finally:
            conn.close()
