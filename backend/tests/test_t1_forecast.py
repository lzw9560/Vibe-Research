# -*- coding: utf-8 -*-
"""S232 T+1 涨停预测 watchlist 生成器——TDD 测试。

设计原则（AAA pattern）：
- _vol_ratio_5 基础逻辑 + 前置不足 + 零量
- generate_t1_watchlist 结构 + 筛选（turn>20+vr5>2）+ 排除涨停股 + 排除 ST
- edge_status = weak-signal-EV-negative + honest_caveat 含 EV/观察池
- 二次确认字段初始 None
- render_watchlist_report 含诚实标注
"""
import json
import sqlite3
from pathlib import Path

import pytest

from tools.t1_forecast import (
    EDGE_STATUS,
    HONEST_CAVEAT,
    TURN_THRESHOLD,
    VR5_THRESHOLD,
    _vol_ratio_5,
    backfill_t1_hit,
    generate_t1_watchlist,
    render_hit_report,
    render_watchlist_report,
)


class TestVolRatio5:
    """_vol_ratio_5 基础逻辑。"""

    def test_basic_ratio_one(self):
        """5 日均量 = T 日量 → vr5 = 1.0。"""
        # Arrange
        bars = [{"volume": 100}] * 6
        # Act
        vr5 = _vol_ratio_5(bars, 5)
        # Assert
        assert vr5 == 1.0

    def test_insufficient_history_returns_none(self):
        """前置不足 5 日 → None（不臆造）。"""
        bars = [{"volume": 100}] * 3
        assert _vol_ratio_5(bars, 2) is None

    def test_zero_prev_volume_returns_none(self):
        """前置含 0 量 → None（除零保护）。"""
        bars = [
            {"volume": 100}, {"volume": 0}, {"volume": 0},
            {"volume": 0}, {"volume": 0}, {"volume": 100},
        ]
        assert _vol_ratio_5(bars, 5) is None

    def test_none_tbar_volume_returns_none(self):
        """T 日 volume None → None。"""
        bars = [{"volume": 100}] * 5 + [{"volume": None}]
        assert _vol_ratio_5(bars, 5) is None


def _build_test_dbs(tmp_path: Path, stocks: list[dict], zt_codes_t: set[str] | None = None,
                    target_date: str = "2026-09-29") -> tuple[Path, Path]:
    """造测试 DB：baostock_kline_cache.db + zt_history.db。"""
    zt_db = tmp_path / "zt_history.db"
    conn = sqlite3.connect(str(zt_db))
    conn.execute("CREATE TABLE zt_history (date TEXT, code TEXT)")
    for code in (zt_codes_t or set()):
        conn.execute("INSERT INTO zt_history VALUES (?, ?)", (target_date, code))
    conn.commit()
    conn.close()

    kline_db = tmp_path / "baostock_kline_cache.db"
    conn = sqlite3.connect(str(kline_db))
    conn.execute("CREATE TABLE kline (code TEXT, bars_json TEXT)")
    for s in stocks:
        conn.execute("INSERT INTO kline VALUES (?, ?)", (s["code"], json.dumps(s["bars"])))
    conn.commit()
    conn.close()
    return kline_db, zt_db


def _make_bar(date: str, volume: int, turn: float, close: float = 10.0,
              pctChg: float = 1.0, isST: str = "0", high: float | None = None,
              low: float | None = None) -> dict:
    """造单日 bar（isST 为字符串 "0"/"1"——真实 baostock 格式，防 CRITICAL truthiness bug 回归）。"""
    return {
        "date": date, "volume": volume, "turn": turn, "close": close,
        "high": high or close, "low": low or close, "pctChg": pctChg,
        "isST": isST, "amount": volume * close,
    }


class TestGenerateT1Watchlist:
    """generate_t1_watchlist 筛选 + 结构 + 诚实标注。"""

    def test_structure_and_thresholds(self, tmp_path, monkeypatch):
        """turn>20+vr5>2 未涨停股入 watchlist；turn<20 不入。"""
        # Arrange
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        # stock A: turn=25 vr5=3.0 未涨停 → 入
        bars_a = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 300, 25, close=11, pctChg=5)]
        # stock B: turn=10 → 不入（turn 不够）
        bars_b = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 150, 10)]
        kline_db, zt_db = _build_test_dbs(tmp_path, [
            {"code": "sh600002", "bars": bars_a},
            {"code": "sh600003", "bars": bars_b},
        ])
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        # Act
        wl = generate_t1_watchlist("2026-09-29")

        # Assert
        assert wl["date"] == "2026-09-29"
        assert wl["signal"] == "turn>20% & vr5>2"
        assert wl["signal_lift"] == 5.28
        assert wl["count"] == 1
        assert wl["stocks"][0]["code"] == "sh600002"
        assert wl["stocks"][0]["turn"] == 25
        assert wl["stocks"][0]["vr5"] == 3.0
        assert wl["edge_status"] == EDGE_STATUS

    def test_excludes_zt_codes(self, tmp_path, monkeypatch):
        """T 日涨停股排除（天生避 survivorship + entry 溢价）。"""
        # Arrange
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        bars_a = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 300, 25, close=11, pctChg=5)]
        kline_db, zt_db = _build_test_dbs(tmp_path, [
            {"code": "sh600002", "bars": bars_a},
        ], zt_codes_t={"sh600002"})  # T 日涨停
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        # Act
        wl = generate_t1_watchlist("2026-09-29")

        # Assert
        assert wl["count"] == 0  # 涨停股被排除

    def test_excludes_st(self, tmp_path, monkeypatch):
        """ST 股排除（涨停 5% 口径不同）。"""
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        bars_st = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 300, 25, isST="1")]
        kline_db, zt_db = _build_test_dbs(tmp_path, [{"code": "sh600004", "bars": bars_st}])
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        wl = generate_t1_watchlist("2026-09-29")
        assert wl["count"] == 0

    def test_isST_string_zero_not_filtered(self, tmp_path, monkeypatch):
        """isST="0"（字符串）不应被误过滤——baostock 真实格式防 CRITICAL truthiness bug 回归。

        baostock 存 isST 为字符串 "0"/"1"，`if tbar.get("isST"):` 把 "0" 当 truthy
        会误过滤所有非 ST 股（reviewer 发现的 CRITICAL bug 回归测试）。
        """
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        bars = [_make_bar(d, 100, 5, isST="0") for d in prev_days] + [
            _make_bar("2026-09-29", 300, 25, isST="0", close=11, pctChg=5)
        ]
        kline_db, zt_db = _build_test_dbs(tmp_path, [{"code": "sh600002", "bars": bars}])
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        wl = generate_t1_watchlist("2026-09-29")
        assert wl["count"] == 1, "isST='0'（字符串）不应被误过滤——CRITICAL bug 回归"

    def test_vr5_below_threshold_excluded(self, tmp_path, monkeypatch):
        """vr5<2 不入（量比不够）。"""
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        # turn>20 但 vr5=1.5（T 日 volume=150, 前置 5 日均 100 → 1.5）
        bars_low_vr5 = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 150, 25)]
        kline_db, zt_db = _build_test_dbs(tmp_path, [{"code": "sh600005", "bars": bars_low_vr5}])
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        wl = generate_t1_watchlist("2026-09-29")
        assert wl["count"] == 0

    def test_edge_status_and_caveat(self, tmp_path, monkeypatch):
        """edge_status = weak-signal-EV-negative + honest_caveat 含 EV/观察池。"""
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        bars_a = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 300, 25, close=11, pctChg=5)]
        kline_db, zt_db = _build_test_dbs(tmp_path, [{"code": "sh600002", "bars": bars_a}])
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        wl = generate_t1_watchlist("2026-09-29")
        assert wl["edge_status"] == "weak-signal-EV-negative"
        assert "EV" in wl["honest_caveat"]
        assert "观察池" in wl["honest_caveat"]
        assert "5.28" in wl["honest_caveat"]

    def test_confirmation_fields_initial_none(self, tmp_path, monkeypatch):
        """二次确认字段（t1_zt/t1_auction/t1_seal_time/confirmed）初始 None。"""
        prev_days = [f"2026-09-{20+i}" for i in range(5)]
        bars_a = [_make_bar(d, 100, 5) for d in prev_days] + [_make_bar("2026-09-29", 300, 25, close=11, pctChg=5)]
        kline_db, zt_db = _build_test_dbs(tmp_path, [{"code": "sh600002", "bars": bars_a}])
        monkeypatch.setattr("tools.t1_forecast._kline_db_path", lambda: kline_db)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        wl = generate_t1_watchlist("2026-09-29")
        s = wl["stocks"][0]
        assert s["t1_zt"] is None
        assert s["t1_auction"] is None
        assert s["t1_seal_time"] is None
        assert s["confirmed"] is None


class TestRenderWatchlistReport:
    """render_watchlist_report 人话报告 + 诚实标注。"""

    def test_report_contains_caveat_and_disclaimer(self):
        """报告含诚实标注 + 风险提醒。"""
        wl = {
            "date": "2026-09-29",
            "signal": "turn>20% & vr5>2",
            "signal_lift": 5.28,
            "signal_lift_ci": "[4.38, 6.35]x",
            "base_rate": 0.00822,
            "hit_rate": 0.0434,
            "edge_status": EDGE_STATUS,
            "honest_caveat": HONEST_CAVEAT,
            "count": 1,
            "stocks": [{"code": "sh600002", "turn": 25, "vr5": 3.0, "pctChg": 5, "close": 11}],
        }
        report = render_watchlist_report(wl)
        assert "2026-09-29" in report
        assert "5.28" in report
        assert "观察池" in report
        assert "历史统计特征" in report
        assert "sh600002" in report

    def test_report_empty_watchlist(self):
        """无信号股时报告含提示。"""
        wl = {
            "date": "2026-09-29", "signal": "turn>20% & vr5>2",
            "signal_lift": 5.28, "signal_lift_ci": "[4.38, 6.35]x",
            "base_rate": 0.00822, "hit_rate": 0.0434,
            "edge_status": EDGE_STATUS, "honest_caveat": HONEST_CAVEAT,
            "count": 0, "stocks": [],
        }
        report = render_watchlist_report(wl)
        assert "无信号股" in report
        assert "历史统计特征" in report


class TestBackfillT1Hit:
    """backfill_t1_hit T+1 hit 回填 + 命中率统计（累积二次确认数据）。"""

    def test_updates_t1_zt_and_counts_hit(self, tmp_path, monkeypatch):
        """回填 t1_zt + 统计命中率（hit/miss 正确标记）。"""
        # Arrange: T 日 watchlist + zt_history[T+1]
        forecast_dir = tmp_path / "t1_forecast"
        forecast_dir.mkdir()
        watchlist = {
            "date": "2026-09-17",
            "signal": "turn>20% & vr5>2",
            "count": 2,
            "edge_status": EDGE_STATUS,
            "stocks": [
                {"code": "sh600002", "turn": 25, "vr5": 3, "t1_zt": None},
                {"code": "sh600003", "turn": 22, "vr5": 2.5, "t1_zt": None},
            ],
        }
        wl_path = forecast_dir / "2026-09-17_watchlist.json"
        wl_path.write_text(json.dumps(watchlist), encoding="utf-8")

        zt_db = tmp_path / "zt_history.db"
        conn = sqlite3.connect(str(zt_db))
        conn.execute("CREATE TABLE zt_history (date TEXT, code TEXT)")
        conn.execute("INSERT INTO zt_history VALUES ('2026-09-18', 'sh600002')")  # hit
        conn.commit()
        conn.close()

        monkeypatch.setattr("tools.t1_forecast._forecast_dir", lambda: forecast_dir)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        # Act
        result = backfill_t1_hit("2026-09-17", "2026-09-18")

        # Assert
        assert result["status"] == "ok"
        assert result["t_date"] == "2026-09-17"
        assert result["t1_date"] == "2026-09-18"
        assert result["total"] == 2
        assert result["hit_count"] == 1
        assert result["hit_rate"] == 0.5
        assert result["expected_rate"] == 0.0434

        # 验证写回的 t1_zt 字段
        with open(wl_path, "r", encoding="utf-8") as f:
            updated = json.load(f)
        assert updated["stocks"][0]["t1_zt"] is True
        assert updated["stocks"][1]["t1_zt"] is False

    def test_no_watchlist_returns_status(self, tmp_path, monkeypatch):
        """T 日 watchlist 不存在 → status=no_watchlist。"""
        forecast_dir = tmp_path / "t1_forecast"
        forecast_dir.mkdir()
        zt_db = tmp_path / "zt_history.db"
        conn = sqlite3.connect(str(zt_db))
        conn.execute("CREATE TABLE zt_history (date TEXT, code TEXT)")
        conn.commit()
        conn.close()

        monkeypatch.setattr("tools.t1_forecast._forecast_dir", lambda: forecast_dir)
        monkeypatch.setattr("tools.t1_forecast._zt_db_path", lambda: zt_db)

        result = backfill_t1_hit("2026-09-17", "2026-09-18")
        assert result["status"] == "no_watchlist"

    def test_render_hit_report_contains_rate(self):
        """报告含命中率 + 预期偏差 + 诚实标注。"""
        hit = {
            "status": "ok",
            "t_date": "2026-09-17",
            "t1_date": "2026-09-18",
            "total": 10,
            "hit_count": 1,
            "hit_rate": 0.10,
            "expected_rate": 0.0434,
            "deviation_pct": 130.4,
        }
        report = render_hit_report(hit)
        assert "2026-09-17" in report
        assert "10.00%" in report
        assert "4.34%" in report
        assert "130.4" in report  # 偏差
        assert "高于预期" in report  # >30% 标警
        assert "历史统计特征" in report
