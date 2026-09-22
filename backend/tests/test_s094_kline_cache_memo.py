# -*- coding: utf-8 -*-
"""S094: _get_kline_cache 接口 smoke（旧 mtime 逻辑已删，SQLite store 替代）。

**背景**（2026-09-22 内存优化）：_get_kline_cache 原"模块级 _KLINE_CACHE + mtime 检测"
全量 load 482MB JSON → 2.19GB 常驻。改 SQLite store（engine.kline_cache_store）后，
_get_kline_cache deprecated 调 load_all（从 SQLite 全量读，2.19GB 峰值一次性 local，
非常驻）。旧 mtime 失效逻辑已删（SQLite 是源，refresh upsert 增量更新，无需 mtime）。

SQLite store 逻辑见 test_kline_cache_store.py。本测试只验 _get_kline_cache 接口仍 work。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_get_kline_cache_returns_dict(monkeypatch, tmp_path):
    """_get_kline_cache deprecated 接口仍返 dict（从 SQLite load_all）。

    隔离 VR_DATA_DIR=tmp_path（无 SQLite 无 JSON → load_all 返空 dict）。
    """
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    from engine import kline_cache_store
    kline_cache_store.invalidate()  # 清 conn + 迁移 flag
    from strategies.first_board.data_extract import _get_kline_cache
    result = _get_kline_cache()
    assert isinstance(result, dict)
    kline_cache_store.invalidate()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
