"""S149 Phase 3 critical #1 — daily_review 磁盘持久化层测试。

journal._market_context 零网络盖章的根基：precompute_daily 落盘 JSON +
get_daily_review 先读磁盘 fallback generate_review。
"""
from __future__ import annotations

import json

import pytest

import daily_review as dr_mod
from daily_review import DailyReviewer, ReviewReport, get_reviewer


def _fake_review(date: str) -> ReviewReport:
    """构造一份复盘报告（替 generate_review，避免网络）。"""
    return ReviewReport(
        date=date, sti_score=55.0, sti_phase="发酵", sti_change=2.0,
        zt_total=39, dt_total=1, zb_total=4, advance_count=2400, decline_count=1600,
        sector_heat=[], zt_stocks=[], prev_zt_stats={"limit_up_again_rate": 0.2},
        auction_top=[], updated="2026-09-04 16:00",
    )


@pytest.fixture
def isolated_reviewer(monkeypatch, tmp_path):
    """VR_DATA_DIR→tmp；generate_review→fake（零网络）；money_effect→可控；_CACHE 每测清空。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # 隔离全局单例 + 清 _CACHE（模块级，跨测不残留——防 disk-hit 测的 _CACHE 污染 miss 测）
    monkeypatch.setattr(dr_mod, "_reviewer_instance", None)
    dr_mod._CACHE.clear()
    monkeypatch.setattr(DailyReviewer, "generate_review", lambda self, d: _fake_review(d))
    import emotion_metrics_ext as _em
    monkeypatch.setattr(_em, "money_effect", lambda d: {"available": True, "median": 5.01})
    return tmp_path


def test_precompute_daily_writes_disk_json(isolated_reviewer, tmp_path):
    """precompute_daily 落盘 <VR_DATA_DIR>/daily-review/<date>.json + 设 money_effect_median。"""
    reviewer = get_reviewer()
    result = reviewer.precompute_daily("2026-09-04")
    assert result.money_effect_median == 5.01  # emotion_metrics_ext.money_effect median
    disk = tmp_path / "daily-review" / "2026-09-04.json"
    assert disk.is_file()
    data = json.loads(disk.read_text(encoding="utf-8"))
    assert data["date"] == "2026-09-04"
    assert data["sti_phase"] == "发酵"
    assert data["money_effect_median"] == 5.01


def test_get_daily_review_disk_hit_zero_network(isolated_reviewer, monkeypatch):
    """磁盘命中 → 零网络（generate_review 不被调）。"""
    reviewer = get_reviewer()
    reviewer.precompute_daily("2026-09-04")  # 落盘

    # 标记 generate_review 不可调——磁盘命中不应触网
    call_count = {"n": 0}
    def _boom(self, d):
        call_count["n"] += 1
        raise AssertionError("磁盘命中不应调 generate_review（零网络契约）")
    monkeypatch.setattr(DailyReviewer, "generate_review", _boom)

    out = reviewer.get_daily_review("2026-09-04")
    assert out is not None
    assert out["date"] == "2026-09-04"
    assert out["money_effect_median"] == 5.01
    assert call_count["n"] == 0  # 零网络


def test_get_daily_review_disk_miss_falls_back(isolated_reviewer, monkeypatch):
    """磁盘未命中 → fallback precompute_daily（重算 + 落盘）。"""
    reviewer = get_reviewer()
    # 未 precompute，磁盘空 → fallback
    out = reviewer.get_daily_review("2026-09-04")
    assert out is not None
    assert out["date"] == "2026-09-04"
    # fallback 路径也落盘（下次零网络）
    import os
    assert os.path.isfile(dr_mod._daily_review_path("2026-09-04"))


def test_get_daily_review_corrupt_disk_falls_back(isolated_reviewer, tmp_path, monkeypatch):
    """磁盘损坏 → 当作未命中 fallback 重算（自愈）。"""
    reviewer = get_reviewer()
    # 写一份损坏的磁盘文件
    disk = tmp_path / "daily-review" / "2026-09-04.json"
    disk.parent.mkdir(parents=True, exist_ok=True)
    disk.write_text("{NOT JSON", encoding="utf-8")

    out = reviewer.get_daily_review("2026-09-04")
    assert out is not None
    assert out["date"] == "2026-09-04"  # fallback 重算成功


def test_get_daily_review_wrong_date_disk_rejected(isolated_reviewer, tmp_path):
    """磁盘文件 date 不匹配 → 拒绝（防文件错拷冒充别天）。"""
    reviewer = get_reviewer()
    disk = tmp_path / "daily-review" / "2026-09-04.json"
    disk.parent.mkdir(parents=True, exist_ok=True)
    disk.write_text(json.dumps({"date": "2026-09-03", "sti_phase": "冰点"}),
                    encoding="utf-8")  # 错日期
    out = reviewer.get_daily_review("2026-09-04")
    # 错日期文件不被认 → fallback 重算（date=2026-09-04）
    assert out["date"] == "2026-09-04"


def test_module_get_daily_review_convenience(isolated_reviewer):
    """模块级 get_daily_review(date) 便捷入口走磁盘优先。"""
    reviewer = get_reviewer()
    reviewer.precompute_daily("2026-09-04")
    out = dr_mod.get_daily_review("2026-09-04")
    assert out is not None
    assert out["sti_phase"] == "发酵"


def test_money_effect_failure_does_not_block_review(isolated_reviewer, monkeypatch):
    """money_effect 取失败 → median=None，不阻塞复盘（不臆造）。"""
    import emotion_metrics_ext as _em
    monkeypatch.setattr(_em, "money_effect", lambda d: {"available": False, "reason": "x"})
    reviewer = get_reviewer()
    result = reviewer.precompute_daily("2026-09-04")
    assert result.money_effect_median is None
