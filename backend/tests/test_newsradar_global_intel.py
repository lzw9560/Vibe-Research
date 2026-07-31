# -*- coding: utf-8 -*-
"""S020 P3 newsradar 全球情报赛道单测。monkeypatch worldmonitor，零网络。"""
import newsradar


def _patch_wm(monkeypatch, clusters=None, intel=None):
    from data.sources import worldmonitor as wm
    monkeypatch.setattr(wm, "fetch_news_clusters", lambda jmespath=None: clusters)
    monkeypatch.setattr(wm, "fetch_news_intelligence", lambda jmespath=None: intel)


def test_fetch_global_intel_merges_and_desc(monkeypatch):
    clusters = {"result": {"content": [{"type": "text", "text": '[{"title":"B","ts":"2026-07-29"}]'}]}}
    intel = {"result": {"content": [{"type": "text", "text": '[{"headline":"A","date":"2026-07-30"}]'}]}}
    _patch_wm(monkeypatch, clusters, intel)
    items = newsradar._fetch_global_intel()
    assert len(items) == 2
    assert items[0]["title"] == "A"  # 时间倒序 07-30 在前
    assert all(it["source"] == "worldmonitor" for it in items)
    # 零个股字段
    assert all("symbol" not in it and "code" not in it for it in items)


def test_fetch_global_intel_unreachable_returns_empty(monkeypatch):
    """worldmonitor 不可达（返 None）→ 空赛道，不抛、不臆造。"""
    _patch_wm(monkeypatch, None, None)
    items = newsradar._fetch_global_intel()
    assert items == []


def test_fetch_global_intel_wm_import_fails(monkeypatch):
    """worldmonitor 模块导入失败 → 空赛道（newsradar 保 stdlib-only 不崩）。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "data.sources.worldmonitor" or name.startswith("data.sources.worldmonitor"):
            raise ImportError("simulated")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert newsradar._fetch_global_intel() == []


def test_fetch_radar_has_global_intel_track(monkeypatch):
    """fetch_radar 输出含「全球情报」赛道，与 12 RSS 赛道同构并列。"""
    _patch_wm(monkeypatch, None, None)  # 不可达 → 空赛道缺省
    # 避免 RSS 真实抓取：patch _fetch_source 返空
    monkeypatch.setattr(newsradar, "_fetch_source", lambda src, per, cutoff, redline: [])
    data = newsradar.fetch_radar()
    keys = [i["key"] for i in data["industries"]]
    assert "global_intel" in keys
    gi = next(i for i in data["industries"] if i["key"] == "global_intel")
    assert gi["name"] == "全球情报" and gi["items"] == []
    assert data["stats"]["industries"] == 13  # 12 RSS + 1 全球情报
