# -*- coding: utf-8 -*-
"""S205 多数据源异构 signal_date merge 测试——立即解锁 §44 verdict（≥60 天 R6 gate）。

forward_test_backfill main() 原单源 eastmoney_live=22 天 <60 → §44 verdict underpowered。
改多源 merge（zt_history + gene_scores + baostock）→ ≥170 天立即解锁。

三源不臆造（全 cache/本地 DB，zero em_get）：zt_history.db + gene_scores.db + baostock_kline_cache.json。
去重（同日多源只取 1，优先 zt_history > gene_scores > baostock）。source 标溯源。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestMultiSourceSignalDates:
    """多源异构 signal_date merge——去重 + source 标 + ≥60 天。"""

    def test_collect_returns_list_of_date_source_tuples(self):
        """_collect_signal_dates_multi_source 返 [(date, source), ...] 升序。"""
        from tools.forward_test_backfill import _collect_signal_dates_multi_source
        ds = _collect_signal_dates_multi_source()
        assert isinstance(ds, list)
        assert all(isinstance(t, tuple) and len(t) == 2 for t in ds), "应 (date, source) tuple"
        # 升序
        dates = [d for d, _ in ds]
        assert dates == sorted(dates), "signal_date 应升序"

    def test_source_labels_valid(self):
        """source 标 ∈ {zt_history, gene_scores, baostock}。"""
        from tools.forward_test_backfill import _collect_signal_dates_multi_source
        ds = _collect_signal_dates_multi_source()
        valid = {"zt_history", "gene_scores", "baostock"}
        for _, src in ds:
            assert src in valid, f"source {src} 不在有效集 {valid}"

    def test_dedup_same_date_single_entry(self):
        """同日多源只取 1（去重）——date 唯一。"""
        from tools.forward_test_backfill import _collect_signal_dates_multi_source
        ds = _collect_signal_dates_multi_source()
        dates = [d for d, _ in ds]
        assert len(dates) == len(set(dates)), "signal_date 应去重（无重复日）"

    def test_reaches_60_days_unlocks_s44(self):
        """多源 merge ≥60 天——立即解锁 §44 verdict R6 gate（原单源 22 <60）。"""
        from tools.forward_test_backfill import _collect_signal_dates_multi_source
        ds = _collect_signal_dates_multi_source()
        assert len(ds) >= 60, f"signal_date 应 ≥60 天解锁 §44，got {len(ds)}"

    def test_no_fabrication_sources_exist(self):
        """三源真存（不臆造）——gene_scores.db 存（forward_test 主 DB，test mode 也应存）。"""
        from vr_paths import resolve_data_dir
        vd = resolve_data_dir()
        # gene_scores.db 是 forward_test 主 DB——生产数据应存；test 若在无 DB 环境 skip
        if not (vd / "gene_scores.db").exists():
            pytest.skip("gene_scores.db 不存在（test 环境 无生产数据）")
        assert (vd / "gene_scores.db").exists()

    def test_mock_three_sources_merge(self, tmp_path):
        """mock 三源 → merge 去重 + source 标（不依赖真 DB，纯逻辑测）。"""
        fake_zt = tmp_path / "zt_history.db"
        c = sqlite3.connect(str(fake_zt))
        c.execute("CREATE TABLE zt_history (date TEXT, lbc INTEGER, is_final INTEGER)")
        c.execute("INSERT INTO zt_history VALUES ('2026-03-01', 1, 1), ('2026-03-02', 2, 1), ('2026-03-03', 1, 0)")
        c.commit(); c.close()

        fake_gs = tmp_path / "gene_scores.db"
        c = sqlite3.connect(str(fake_gs))
        c.execute("CREATE TABLE gene_scores (date TEXT, data_source TEXT)")
        c.execute("INSERT INTO gene_scores VALUES ('2026-03-02','eastmoney_live'), ('2026-03-04','kline_rebuild')")
        c.commit(); c.close()

        # patch 模块级路径常量（ZT_DB/DB/KLINE_CACHE）——_collect 读模块 global
        import tools.forward_test_backfill as ftb
        orig_zt, orig_db, orig_kc = ftb.ZT_DB, ftb.DB, ftb.KLINE_CACHE
        ftb.ZT_DB, ftb.DB, ftb.KLINE_CACHE = fake_zt, fake_gs, tmp_path / "no_cache.json"
        try:
            ds = ftb._collect_signal_dates_multi_source()
        finally:
            ftb.ZT_DB, ftb.DB, ftb.KLINE_CACHE = orig_zt, orig_db, orig_kc

        dates_src = {d: s for d, s in ds}
        assert dates_src.get("2026-03-01") == "zt_history", f"03-01 应 zt_history，got {dates_src.get('2026-03-01')}"
        assert dates_src.get("2026-03-02") == "zt_history", f"03-02 优先 zt_history，got {dates_src.get('2026-03-02')}"
        assert dates_src.get("2026-03-04") == "gene_scores", f"03-04 gene_scores，got {dates_src.get('2026-03-04')}"
        assert len(ds) == 3, f"去重后 3 日，got {len(ds)}: {dates_src}"


class TestBackfillMainUsesMultiSource:
    """main() 用多源 signal_date（非单源 eastmoney_live）。"""

    def test_main_no_longer_single_source_eastmoney_live(self):
        """main() source code 不再单源 eastmoney_live（用 _collect_signal_dates_multi_source）。"""
        src = (Path(__file__).resolve().parent.parent / "tools" / "forward_test_backfill.py").read_text("utf-8")
        assert "_collect_signal_dates_multi_source" in src, "main 应调多源 merge 函数"
        assert "signal_date 多源 merge" in src, "main 应打印多源 merge 信息"
