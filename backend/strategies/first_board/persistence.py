# -*- coding: utf-8 -*-
"""persistence——评分落盘/读盘/日期列表。

实现范围：
- 021 落盘：save_scores
- 读盘：load_scores
- 日期列表：list_score_dates
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from vr_paths import resolve_data_dir  # noqa: PLC0415

from strategies.first_board.universe import MARKET_PHASE_WEIGHTS

_logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# 9 维度评分落盘目录——走 vr_paths.resolve_data_dir（§1.2 私有数据隔离：只落 VR_DATA_DIR，不进 home）。
# S148 审计修复：原硬编码 Path.home()/".vibe-research" 违反隔离底线（数据落错地方，home 的 .vibe-research 是红鲱鱼）。
_SCORES_DIR = resolve_data_dir()
# legacy 读 fallback：旧快照曾误落 home 目录，load/list 双查保历史不丢（save 只写新址）。
_SCORES_DIR_LEGACY = Path.home() / ".vibe-research"


def save_scores(scored: list[dict], date: str, full_result: dict | None = None) -> Path:
    """存 ~/.vibe-research/first_board_scores_{date}.json。

    Args:
        scored: rank_candidates 返回的评分列表。
        date: YYYYMMDD（用于文件名）。
        full_result: run_first_board_filter 的完整返回（含 zt_pool_count/excluded/env_flags），
            传入则一并落盘，供历史快照还原 Pipeline 全过程数据。

    Returns:
        Path：落盘文件路径。
    """
    global _SCORES_DIR
    # S174 兼容：测试 monkeypatch _SCORES_DIR 到临时目录时，_SCORES_DIR 被 patch 为
    # PosixPath 对象（新引用），须重新绑定到当前 global 才能让 save 写到 tmp_path。
    # 直接读模块 global 而非用闭包变量（闭包 _SCORES_DIR 在模块加载时固化）。
    import strategies.first_board.persistence as _p
    scores_dir = _p._SCORES_DIR
    scores_dir.mkdir(parents=True, exist_ok=True)
    out_path = scores_dir / f"first_board_scores_{date}.json"
    meta = {
        "date": date,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(scored),
        "weights": MARKET_PHASE_WEIGHTS,
        "note": "评分权重按市场档位分层（冰点/普通/活跃/亢奋），待回测校准（grill 锁定）",
    }
    payload = {"_meta": meta, "scored_candidates": scored}
    if full_result is not None:
        payload["zt_pool_count"] = full_result.get("zt_pool_count", 0)
        payload["first_board_count"] = full_result.get("first_board_count", 0)
        payload["excluded"] = full_result.get("excluded", [])
        payload["env_flags"] = full_result.get("env_flags", {})
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_scores(date: str) -> dict | None:
    """读 ~/.vibe-research/first_board_scores_{date}.json 历史快照。

    Args:
        date: YYYYMMDD 或 YYYY-MM-DD（内部归一为 YYYYMMDD）。

    Returns:
        dict 含：
        - date: str（快照日期 YYYYMMDD）
        - scored_candidates: list[dict]（9 维度评分列表）
        - updated_at: str（落盘时间戳）
        - zt_pool_count: int（新版本落盘，旧快照缺=0）
        - first_board_count: int
        - excluded: list[dict]
        - env_flags: dict
        无快照/读取失败 → None。
    """
    compact = date.replace("-", "") if "-" in date else date
    path = _SCORES_DIR / f"first_board_scores_{compact}.json"
    if not path.exists():
        # legacy fallback：旧快照曾误落 home 目录，新址缺则查旧址（保历史不丢）
        path = _SCORES_DIR_LEGACY / f"first_board_scores_{compact}.json"
        if not path.exists():
            return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning("load_scores 读取失败 date=%s err=%s", compact, e)
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("_meta", {})
    return {
        "date": meta.get("date", compact),
        "scored_candidates": data.get("scored_candidates", []),
        "updated_at": meta.get("updated_at", ""),
        "zt_pool_count": data.get("zt_pool_count", 0),
        "first_board_count": data.get("first_board_count", 0),
        "excluded": data.get("excluded", []),
        "env_flags": data.get("env_flags", {}),
    }


def list_score_dates() -> list[str]:
    """列出所有有快照的日期（YYYYMMDD 格式，降序）。

    扫描 _SCORES_DIR 下的 first_board_scores_YYYYMMDD.json 文件，
    返回日期字符串列表（最近的在前）。目录不存在/无文件 → []。
    """
    dates: list[str] = []
    seen: set[str] = set()
    # 双查新址 + legacy 旧址，去重（旧快照曾误落 home 目录）
    for _dir in (_SCORES_DIR, _SCORES_DIR_LEGACY):
        if not _dir.exists():
            continue
        for p in _dir.glob("first_board_scores_*.json"):
            # 文件名 first_board_scores_20260818.json → stem first_board_scores_20260818
            stem = p.stem.replace("first_board_scores_", "")
            if stem.isdigit() and len(stem) == 8 and stem not in seen:
                seen.add(stem)
                dates.append(stem)
    dates.sort(reverse=True)
    return dates
