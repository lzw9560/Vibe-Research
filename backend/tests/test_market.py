# -*- coding: utf-8 -*-
"""market.py 纯函数单测。"""

import unittest
from market import _num, _cached


class TestNum(unittest.TestCase):
    """数字转换工具测试。"""

    def test_int_string(self):
        self.assertEqual(_num("123"), 123)

    def test_float_string(self):
        self.assertEqual(_num("123.45"), 123)

    def test_int_value(self):
        self.assertEqual(_num(123), 123)

    def test_float_value(self):
        self.assertEqual(_num(123.45), 123)

    def test_none_returns_zero(self):
        self.assertEqual(_num(None), 0)

    def test_invalid_string_returns_zero(self):
        self.assertEqual(_num("abc"), 0)

    def test_empty_string_returns_zero(self):
        self.assertEqual(_num(""), 0)


class TestCached(unittest.TestCase):
    """TTL 缓存测试。"""

    def test_cache_hit(self):
        call_count = 0
        def fn():
            nonlocal call_count
            call_count += 1
            return "value"

        result1 = _cached("key", fn, valid=bool)
        result2 = _cached("key", fn, valid=bool)
        self.assertEqual(result1, "value")
        self.assertEqual(result2, "value")
        self.assertEqual(call_count, 1)  # 只调用一次

    def test_cache_miss(self):
        call_count = 0
        def fn():
            nonlocal call_count
            call_count += 1
            return f"value-{call_count}"

        result1 = _cached("key1", fn, valid=bool)
        result2 = _cached("key2", fn, valid=bool)
        self.assertEqual(result1, "value-1")
        self.assertEqual(result2, "value-2")
        self.assertEqual(call_count, 2)  # 调用两次

    def test_invalid_not_cached(self):
        import market as m
        m._CACHE.clear()  # 清理缓存
        call_count = 0
        def fn():
            nonlocal call_count
            call_count += 1
            return None

        result1 = m._cached("key-invalid", fn, valid=bool)
        result2 = m._cached("key-invalid", fn, valid=bool)
        self.assertIsNone(result1)
        self.assertIsNone(result2)
        self.assertEqual(call_count, 2)  # 无效结果不缓存，调用两次


if __name__ == "__main__":
    unittest.main()
