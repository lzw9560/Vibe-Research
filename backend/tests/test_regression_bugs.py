# -*- coding: utf-8 -*-
"""S016 R7/R9：回归专项测试——汇总 4 个历史 bug 的回归索引 + scheduled_tasks imports 冒烟。

设计原则（DRY）：不重复已有 test_s008_bugs.py / test_s015_cache_response_key.py 的测试，
只做"回归索引"——断言这些测试文件存在且可导入，防回归测试被误删。
S011 回归项：scheduled_tasks 导入不抛 + _executors 含全部注册 task_type。
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRegressionSuiteExists(unittest.TestCase):
    """R9：断言 4 个历史 bug 的回归测试文件存在且可导入（防回归索引被误删）。"""

    def test_s008_kline_nonzero_regression_exists(self):
        """S008: risk_models 用 kline 非 get_kline + volatility/max_drawdown/liquidity 非零。"""
        mod = importlib.import_module("tests.test_s008_bugs")
        self.assertTrue(hasattr(mod, "test_risk_models_uses_kline_not_get_kline"))
        self.assertTrue(hasattr(mod, "test_risk_models_volatility_nonzero"))

    def test_s008_seat_engine_isolated_regression_exists(self):
        """S008: seat_engine 默认值不共享（实例隔离）。"""
        mod = importlib.import_module("tests.test_s008_bugs")
        self.assertTrue(hasattr(mod, "test_seat_engine_defaults_not_shared"))

    def test_s015_cache_key_regression_exists(self):
        """S015: cache_response key 按 code 区分（positional + kwarg + TTL 命中）。"""
        mod = importlib.import_module("tests.test_s015_cache_response_key")
        self.assertTrue(hasattr(mod, "test_cache_key_differs_by_kwarg_code"))
        self.assertTrue(hasattr(mod, "test_cache_hit_within_ttl"))


class TestScheduledTasksImports(unittest.TestCase):
    """S011 回归：scheduled_tasks 模块导入不抛 + _executors 含全部注册 task_type。"""

    def test_scheduled_tasks_imports_clean(self):
        """import scheduled_tasks 不抛异常（防 import 时序/循环导入回归）。"""
        import scheduled_tasks as st
        self.assertIsNotNone(st.TaskExecutor)

    def test_all_task_types_registered(self):
        """_executors 含全部预期的 task_type（防误删注册）。"""
        import scheduled_tasks as st
        executor = st.TaskExecutor()
        expected = {
            "daily_data_refresh",
            "daily_review_notify",
            "limitup_precompute",
            "portfolio_refresh",
            "market_data_sync",
            "cleanup_old_runs",
            "daily_backtest_run",
            "sti_post_market",
            "seal_intraday_collect",
            "candidate_funnel_precompute",
            "s066_validation_checkpoint",
            "forward_test_daily",
        }
        actual = set(executor._executors.keys())
        self.assertEqual(actual, expected, f"缺失: {expected - actual}")

    def test_seed_tasks_function_exists(self):
        """_ensure_seed_tasks 可调用（防 seed 逻辑被破坏）。"""
        import scheduled_tasks as st
        self.assertTrue(callable(st._ensure_seed_tasks))


if __name__ == "__main__":
    unittest.main()
