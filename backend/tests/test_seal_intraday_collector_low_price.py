# -*- coding: utf-8 -*-
"""S070 B4：collect_once 扩 low_price + limit_pct 采集测试（R6）。

覆盖：
- tencent_quote mock 返 low → low_price 正确落库（AC5）
- tencent_quote 返空 dict → low_price=None 不臆造
- tencent_quote 失败 → low_price=None，data_status 不降级（涨停池主数据成功）
- limit_pct 从 zdp 正确落库
- tencent_quote 一次批量请求（不逐只）
"""
import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_seal_db(tmp_path, monkeypatch):
    """临时 SEAL_INTRADAY_DB_PATH + 触发迁移（含 S070 R6.1 + R3）。"""
    db_path = tmp_path / "seal_intraday.db"
    monkeypatch.setattr("risk.seal_intraday_collector._DB_PATH", str(db_path))
    monkeypatch.setattr("risk.seal_intraday_collector.SEAL_INTRADAY_DB_PATH", str(db_path))
    from risk.seal_intraday_collector import run_migrations
    run_migrations()
    return str(db_path)


def _force_trading_time(monkeypatch):
    """强制 collect_once 进入交易时段分支。"""
    import risk.seal_intraday_collector as sic
    monkeypatch.setattr(sic, "is_intraday_trading_time", lambda now=None: True)


class TestLowPriceCollect:
    def test_low_price_written_from_tencent_quote(self, isolated_seal_db, monkeypatch):
        """R6: tencent_quote 返回 low → low_price 落库。"""
        _force_trading_time(monkeypatch)
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: [
            {"c": "000001", "n": "平安银行", "p": 12.5, "fund": 1e8, "zbc": 0,
             "fbt": 93500, "lbc": 1, "hybk": "银行", "zdp": 10.0},
        ])
        monkeypatch.setattr("astock.tencent_quote", lambda codes: {
            "000001": {"low": 12.2, "high": 13.5},
        })

        from risk.seal_intraday_collector import collect_once, get_snapshots_by_code
        result = collect_once()
        assert result["written"] == 1

        rows = get_snapshots_by_code("000001")
        assert rows[0]["low_price"] == 12.2
        assert rows[0]["limit_pct"] == 10.0

    def test_low_price_none_when_tencent_returns_empty(self, isolated_seal_db, monkeypatch):
        """R6: tencent_quote 返空 dict → low_price=None 不臆造。"""
        _force_trading_time(monkeypatch)
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: [
            {"c": "000001", "n": "平安银行", "p": 12.5, "fund": 1e8, "zbc": 0,
             "fbt": 93500, "lbc": 1, "hybk": "银行", "zdp": 10.0},
        ])
        monkeypatch.setattr("astock.tencent_quote", lambda codes: {})

        from risk.seal_intraday_collector import collect_once, get_snapshots_by_code
        result = collect_once()
        assert result["written"] == 1
        assert result["data_status"] == "ok"  # 涨停池主数据成功，不降级

        rows = get_snapshots_by_code("000001")
        assert rows[0]["low_price"] is None  # 不臆造
        assert rows[0]["limit_pct"] == 10.0  # limit_pct 来自涨停池，不受 tencent 影响

    def test_low_price_none_when_tencent_fails(self, isolated_seal_db, monkeypatch):
        """R6: tencent_quote 失败 → low_price=None，data_status 不降级。"""
        _force_trading_time(monkeypatch)
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: [
            {"c": "000001", "n": "平安银行", "p": 12.5, "fund": 1e8, "zbc": 0,
             "fbt": 93500, "lbc": 1, "hybk": "银行", "zdp": 10.0},
        ])

        def _fail(codes):
            raise RuntimeError("tencent network error")
        monkeypatch.setattr("astock.tencent_quote", _fail)

        from risk.seal_intraday_collector import collect_once, get_snapshots_by_code
        result = collect_once()
        assert result["written"] == 1
        assert result["data_status"] == "ok"  # 涨停池成功，tencent 失败不拖垮整体

        rows = get_snapshots_by_code("000001")
        assert rows[0]["low_price"] is None  # 失败不臆造
        assert rows[0]["limit_pct"] == 10.0

    def test_tencent_quote_called_once_batch(self, isolated_seal_db, monkeypatch):
        """R6: tencent_quote 一次批量请求全池 codes（不逐只）。"""
        _force_trading_time(monkeypatch)
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: [
            {"c": "000001", "n": "平安银行", "p": 12.5, "fund": 1e8, "zbc": 0,
             "fbt": 93500, "lbc": 1, "hybk": "银行", "zdp": 10.0},
            {"c": "600519", "n": "贵州茅台", "p": 1800, "fund": 5e8, "zbc": 1,
             "fbt": 100000, "lbc": 2, "hybk": "白酒", "zdp": 10.0},
            {"c": "000002", "n": "万科A", "p": 10.0, "fund": 3e8, "zbc": 0,
             "fbt": 94000, "lbc": 1, "hybk": "地产", "zdp": 10.0},
        ])
        call_count = [0]
        captured_codes = [None]

        def _track(codes):
            call_count[0] += 1
            captured_codes[0] = list(codes)
            return {"000001": {"low": 12.2}, "600519": {"low": 1780.0}, "000002": {"low": 9.8}}
        monkeypatch.setattr("astock.tencent_quote", _track)

        from risk.seal_intraday_collector import collect_once
        collect_once()
        assert call_count[0] == 1  # 只调一次（批量）
        assert set(captured_codes[0]) == {"000001", "600519", "000002"}  # 全池 codes

    def test_limit_pct_from_zdp(self, isolated_seal_db, monkeypatch):
        """R6: limit_pct 从涨停池 zdp 字段正确落库。"""
        _force_trading_time(monkeypatch)
        monkeypatch.setattr("astock.em_zt_topic_pool", lambda *a, **k: [
            {"c": "300750", "n": "宁德时代", "p": 250.0, "fund": 2e8, "zbc": 0,
             "fbt": 93000, "lbc": 3, "hybk": "电池", "zdp": 20.0},  # 创业板涨停 20%
        ])
        monkeypatch.setattr("astock.tencent_quote", lambda codes: {})

        from risk.seal_intraday_collector import collect_once, get_snapshots_by_code
        collect_once()
        rows = get_snapshots_by_code("300750")
        assert rows[0]["limit_pct"] == 20.0
