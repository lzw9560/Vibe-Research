# -*- coding: utf-8 -*-
"""S123 R5：storm-daemon news provenance 单测。

闭合 crack：storm-daemon-news-items-no-provenance——fetch_snapshot 的 news_items 无
provenance（对比 global_indices 已有 fetch_ok/is_degraded，S116），致 _collect_news_factor
无法区分"T-1 快照 news 采集失败"与"无 T-1 快照"——两者都走 fallback_current，把今日新闻
当昨日新闻用（违 A7/§1.2 可复现）。

R5.1：fetch_snapshot 加 news_fetch_ok/news_is_degraded（mirror global_indices:55-56）。
R5.2：_collect_news_factor 读 snap["news_fetch_ok"]——快照存在但 False→degraded（非 fallback_current）。

conftest 已设 VR_STORM_DAEMON=0，import storm_daemon 不会启动后台线程。
"""
from __future__ import annotations

import json


def _make_radar(titles: list[str]) -> dict:
    """构造 fetch_radar/get_radar 返回结构：industries 嵌套 items（顶层无 items 键）。"""
    items = [{"title": t, "summary": ""} for t in titles]
    return {
        "generated_at": "2026-08-20 09:00",
        "recent_days": 7,
        "industries": [
            {"key": "test", "name": "测试", "accent": "#fff", "total": len(items), "items": items}
        ],
        "stats": {"industries": 1, "total_sources": 1, "failed_sources": 0},
    }


# ============================================================================
# R5.1：fetch_snapshot news 采集失败 → news_fetch_ok=False / news_is_degraded=True 落盘
# ============================================================================

def test_fetch_snapshot_records_news_fetch_ok_failure(tmp_path, monkeypatch):
    """R5.1：newsradar.fetch_radar 抛异常→news_fetch_ok=False/news_is_degraded=True 落盘持久化。

    Arrange: 重定向 _SNAP_DIR→tmp_path；global 采成功（隔离 news 失败）；newsradar.fetch_radar 抛异常。
    Act:     调 fetch_snapshot（同步，daemon 线程无关）。
    Assert:  news provenance 落盘（mirror global_indices:55-56）+ 读回持久化；
             global provenance 独立不受 news 失败影响。
    原 news 无 provenance 致 T-1 快照 news 失败 vs 无快照不可区分，现闭合该区分。
    """
    from strategies import storm_daemon
    import market
    import newsradar

    monkeypatch.setattr(storm_daemon, "_SNAP_DIR", tmp_path)
    monkeypatch.setattr(market, "get_global_indices",
                        lambda: [{"name": "道琼斯", "change_pct": -1.0}])

    def _newsradar_down() -> dict:
        raise RuntimeError("newsradar down")

    monkeypatch.setattr(newsradar, "fetch_radar", _newsradar_down)

    # Act
    snap = storm_daemon.fetch_snapshot()

    # Assert：news provenance 落盘（mirror global_indices:55-56）
    assert snap["news_fetch_ok"] is False
    assert snap["news_is_degraded"] is True
    assert snap["news_items"] == []
    # global provenance 独立（news 失败不污染 global——两源 provenance 各自落盘）
    assert snap["fetch_ok"] is True
    assert snap["is_degraded"] is False
    # 落盘持久化——读回验证（daemon 异步写盘，predictor 读 T-1 时据此判 degraded）
    path = tmp_path / f"{snap['date']}.json"
    snaps = json.loads(path.read_text(encoding="utf-8"))
    persisted = snaps[-1]
    assert persisted["news_fetch_ok"] is False
    assert persisted["news_is_degraded"] is True
    assert persisted["news_items"] == []


# ============================================================================
# R5.2：_collect_news_factor T-1 快照 news_fetch_ok=False → degraded（非 fallback_current）
# ============================================================================

def test_news_factor_degraded_when_snapshot_news_fetch_failed(monkeypatch):
    """R5.2：T-1 快照存在但 news_fetch_ok=False（快照 news 采集失败）→ data_status=degraded，
    区分"无快照→fallback_current"。

    Arrange: T-1 快照 news_fetch_ok=False（news_items 空）；fallback 当前 newsradar 有 items。
    Act:     调 _collect_news_factor。
    Assert:  data_status=degraded（非 fallback_current）——闭合 crack 核心；
             degraded 源 fallback 当前仍保留 degraded 标（不伪装 ok），对齐 global_indices 范式；
             items 来自 fallback（score 据当前新闻算），证明 degraded≠不取数，而是诚实标 provenance。
    """
    from strategies import storm_predictor, storm_daemon
    import newsradar

    # T-1 快照：news 采集失败（news_fetch_ok=False，对齐 R5.1 落盘字段）
    monkeypatch.setattr(storm_daemon, "get_t1_global_snapshot", lambda d: {
        "news_items": [], "news_fetch_ok": False, "news_is_degraded": True,
    })
    # fallback 当前 newsradar 有 items（证明 degraded 源仍取当前，但标 degraded 非 fallback_current）
    monkeypatch.setattr(newsradar, "get_radar",
                        lambda force=False: _make_radar(["暴跌", "退市"]))

    # Act
    f = storm_predictor._collect_news_factor("2026-08-20")

    # Assert：degraded（非 fallback_current——闭合"T-1 失败 vs 无快照"不可区分 crack）
    assert f.data_status == "degraded"
    assert f.data_status != "fallback_current"
    assert "T-1 degraded" in f.detail          # src 标 degraded fallback
    assert f.score == 100.0                    # 2 利空 / 2 = 100%（items 来自 fallback）
