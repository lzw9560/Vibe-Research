# -*- coding: utf-8 -*-
"""backtest_lite.py 纯函数单测。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

from backtest_lite import _next_trading_day


class TestNextTradingDay(unittest.TestCase):
    """交易日历跳过逻辑测试。"""

    def test_skip_weekend(self):
        # 周五 → 下周一
        self.assertEqual(_next_trading_day("2025-06-13"), "2025-06-16")

    def test_skip_holiday(self):
        # 使用 mock 模拟节假日文件
        fake_cal = {"holidays": ["2025-06-16"]}

        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(fake_cal))):
            with patch("pathlib.Path.exists", return_value=True):
                # 2025-06-13 周五，下一个交易日是 2025-06-17 周二（跳过周末 + 节假日）
                self.assertEqual(_next_trading_day("2025-06-13"), "2025-06-17")


if __name__ == "__main__":
    unittest.main()
