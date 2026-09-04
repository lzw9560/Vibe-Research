# -*- coding: utf-8 -*-
"""ST-play radar 白名单加载（S148 R3 配套）。

盘后 scheduled 产 ``st_play_radar.json``（{code: "摘帽"|"重组"|"扭亏"}），
供 ``classify_tradability`` 在涨停叉 R1 / 非涨停叉 market_scan 做 ST carve-out
（re-include + st_play 标）。本模块只负责加载（graceful 空）；生产端见
scheduled_tasks（R3，复用 catalyst 公告分类 + news_radar 摘帽/扭亏扫描）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def load_st_play_radar() -> dict[str, str]:
    """加载 ST-play radar 白名单。文件不存在 → 返空（ST flat 排除，安全降级，不阻断主流程）。

    S148 审计修复：原 bare except 零日志——JSON 损坏/权限错/路径异常静默返空 → ST carve-out
    静默失效无信号。现记 warning（返空仍是安全降级，但留痕供排查）。
    """
    try:
        from vr_paths import resolve_data_dir  # noqa: PLC0415
        p: Path = resolve_data_dir() / "st_play_radar.json"
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            _logger.warning("st_play_radar.json 非对象（%s），ST flat 降级", type(data).__name__)
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:  # noqa: BLE001 — 返空是安全降级，但记 warning 留痕
        _logger.warning("load_st_play_radar 加载失败（ST flat 降级）: %s", exc)
        return {}


# ST-play 判定关键词（radar 专用；优先级 摘帽 > 重组 > 扭亏）
_ZHAIMAO_KEYWORDS = ("撤销其他风险警示", "撤销退市风险警示", "撤销风险警示", "摘帽")
_TURNAROUND_KEYWORDS = ("扭亏",)


def _chongzu_keywords() -> tuple[str, ...]:
    """复用 catalyst._ANN_KEYWORDS 的"重组"型关键词（DRY）。"""
    try:
        from candidate_funnel.sources.catalyst import _ANN_KEYWORDS  # noqa: PLC0415
        return next((kws for t, kws in _ANN_KEYWORDS if t == "重组"), ())
    except Exception:
        return ()


def classify_st_play(announcements) -> str | None:
    """从一只票近期公告判定 ST-play 类型。返回 "摘帽"|"重组"|"扭亏"|None。

    优先级：摘帽 > 重组 > 扭亏（摘帽最强）。
    announcements: [{"title": ...}, ...]（catalyst 同款 shape）。
    """
    if not announcements:
        return None
    joined = " ".join(
        (a.get("title", "") if isinstance(a, dict) else "") for a in announcements
    )
    if any(kw in joined for kw in _ZHAIMAO_KEYWORDS):
        return "摘帽"
    if any(kw in joined for kw in _chongzu_keywords()):
        return "重组"
    if any(kw in joined for kw in _TURNAROUND_KEYWORDS):
        return "扭亏"
    return None


def build_st_play_radar(
    st_codes, fetch_announcements,
) -> dict[str, str]:
    """产 ST-play 白名单。st_codes: ST 股代码列表；fetch_announcements(code)->list[dict]。

    逐只查公告 → classify_st_play → 命中摘帽/重组/扭亏 的进白名单。
    fetch 失败/异常 → 跳过该只（不崩，不阻断）。
    返回 {code: play_type}。
    """
    radar: dict[str, str] = {}
    for code in st_codes:
        try:
            anns = fetch_announcements(code) or []
        except Exception:
            anns = []
        play = classify_st_play(anns)
        if play:
            radar[code] = play
    return radar


def save_st_play_radar(radar: dict[str, str]) -> None:
    """落盘 ST-play 白名单到 VR_DATA_DIR/st_play_radar.json（覆盖写）。"""
    from vr_paths import resolve_data_dir  # noqa: PLC0415
    p = resolve_data_dir() / "st_play_radar.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(radar, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def _collect_st_codes() -> list[str]:
    """全量 ST 股代码（code_industry 全量 names 滤 ST/*ST，覆盖涨停叉+非涨停叉双 lane）。

    code_industry 表（gene_scores.db）存全量 code→name。失败/缺表→返空
    （radar 降级 ST flat 排除，安全，不阻断主流程）。
    """
    try:
        import sqlite3  # noqa: PLC0415
        from vr_paths import resolve_data_dir  # noqa: PLC0415
        db = resolve_data_dir() / "gene_scores.db"
        if not db.exists():
            return []
        conn = sqlite3.connect(str(db), timeout=5)
        try:
            rows = conn.execute("SELECT code, name FROM code_industry").fetchall()
            return [str(r[0]) for r in rows if r[1] and ("ST" in r[1] or "*ST" in r[1])]
        finally:
            conn.close()
    except Exception:
        return []


def run_st_play_radar(
    st_codes: list[str] | None = None,
    fetch_announcements=None,
) -> dict[str, str]:
    """盘后跑 ST-play radar：扫 ST 股公告 → 白名单 → 落盘（S148 R3）。

    st_codes / fetch_announcements 可注入（测试）；默认 st_codes=code_industry 全量 ST 股，
    fetch=astock.announcements（em_get 限流 + circuit_breaker）。
    返回白名单 dict（同时落盘 VR_DATA_DIR/st_play_radar.json）。
    """
    if st_codes is None:
        st_codes = _collect_st_codes()
    if fetch_announcements is None:
        import astock  # noqa: PLC0415
        fetch_announcements = astock.announcements
    radar = build_st_play_radar(st_codes, fetch_announcements)
    save_st_play_radar(radar)
    return radar
