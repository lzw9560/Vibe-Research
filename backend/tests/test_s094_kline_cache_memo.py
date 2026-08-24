# -*- coding: utf-8 -*-
"""S094 audit: _get_kline_cache memo + mtime 失效测试（T21 perf memo + audit mtime fix）。

覆盖 gap：get_non_limitup_funnel 端点复用 _get_kline_cache 的路径零测试覆盖；
既有非涨停测试直接注入 cache，memo 行为 + mtime 失效（refresh 脚本重写盘后重载）无守卫。
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGetKlineCacheMemo(unittest.TestCase):
    """T21 _get_kline_cache 模块级 memo + S094 audit mtime 失效。"""

    def setUp(self):
        from strategies import first_board_filter as fbf
        from vr_paths import resolve_data_dir
        self._fbf = fbf
        # reset memo（防跨测串；memo 是模块级全局）
        fbf._KLINE_CACHE = None
        fbf._KLINE_CACHE_MTIME = 0.0
        # 删 leftover cache 文件（防跨测/跨 session 串，保每测干净）
        p = resolve_data_dir() / "baostock_kline_cache.json"
        if p.exists():
            p.unlink()

    def tearDown(self):
        self._fbf._KLINE_CACHE = None
        self._fbf._KLINE_CACHE_MTIME = 0.0

    def _write_cache(self, data: dict) -> None:
        from vr_paths import resolve_data_dir
        p = resolve_data_dir() / "baostock_kline_cache.json"
        p.write_text(json.dumps(data), encoding="utf-8")

    def test_missing_file_returns_empty(self):
        self.assertEqual(self._fbf._get_kline_cache(), {})

    def test_first_read_caches(self):
        self._write_cache({"000001": [{"close": 10.0}]})
        c = self._fbf._get_kline_cache()
        self.assertEqual(c, {"000001": [{"close": 10.0}]})
        self.assertIsNotNone(self._fbf._KLINE_CACHE)

    def test_memo_fresh_same_mtime_no_reread(self):
        self._write_cache({"000001": [{"close": 10.0}]})
        c1 = self._fbf._get_kline_cache()
        # 同 mtime（未改文件）→ 返同一 memo 对象（不重读）
        c2 = self._fbf._get_kline_cache()
        self.assertIs(c1, c2)

    def test_mtime_invalidation_reloads(self):
        """audit fix: refresh 脚本重写盘（mtime 变）→ 下次调用重载，防进程内 memo 吐 stale bars。"""
        self._write_cache({"000001": [{"close": 10.0}]})
        c1 = self._fbf._get_kline_cache()
        self.assertEqual(c1, {"000001": [{"close": 10.0}]})
        # 覆写文件（mtime 变）→ 下次调用重载
        time.sleep(0.05)  # 防 fs mtime 分辨率不足
        self._write_cache({"000002": [{"close": 20.0}]})
        c2 = self._fbf._get_kline_cache()
        self.assertEqual(c2, {"000002": [{"close": 20.0}]})  # 重载新数据，非 stale memo


if __name__ == "__main__":
    unittest.main()
