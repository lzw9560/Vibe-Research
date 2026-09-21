# -*- coding: utf-8 -*-
"""S208: post-首板 relay + 板块补涨 candidate scanner（T10 auto-source）。

专家 reframe（2026-09-16，panel w1iu01jnl）：原"pre-涨停 scanner"3 信号里 2 死/证否——
- high_gene >=80 死信号（max total_score 50.46，0 picks ever）+ gene_score selection edge 证否（0.942x）→ DROP
- relay_seed (lbc==1) standalone 重测 lianban_lift 已 null（0.986x）→ reframe post-首板（compound with sector activity）
- sector_startup 真 pre-涨停 v2（须 code_industry 全会员）

本 scanner 是 **PLUMBING**（修 funnel 错源 correctness bug + 喂 manual trigger），非 edge 验证——
真 edge 问题在 T10 executor entry/exit 规则（止盈止损从波动股提 trade edge），并行设计。
zero em_get（zt_history.db + gene_scores.db 离线）。pit guard T-1 only。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]  # repo root（backend/pre_limitup_scanner.py → parents[1]=repo）
DATA = ROOT / ".vibe-research"
ZT_DB = DATA / "zt_history.db"
GENE_DB = DATA / "gene_scores.db"


def _zt_history_lbc1(date: str) -> list[dict[str, Any]]:
    """zt_history T-1 WHERE lbc==1 AND is_final=1（首板，post-首板 pre-二板）。

    返 [{code, hybk, lbc}]。lbc>=2 连板排除（非 pre-二板）。
    """
    if not ZT_DB.exists():
        return []
    conn = sqlite3.connect(str(ZT_DB))
    try:
        rows = conn.execute(
            "SELECT code, hybk, lbc FROM zt_history WHERE date=? AND lbc=1 AND is_final=1",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    return [{"code": r[0], "hybk": r[1] or "", "lbc": int(r[2])} for r in rows]


def _zt_history_lbc_ge2(date: str) -> list[dict[str, Any]]:
    """S211: zt_history T-1 WHERE lbc>=2 AND lbc<=3 AND is_final=1（连板接力，consecutive_relay arm 源）。

    返 [{code, hybk, lbc}]。lbc 2-3 连板（甜点区间）。
    lbc>=4 排除（deep_dive 证 edge 消失 -0.02%，高位风险——tools/s203_consecutive_relay_deep_dive.py）。
    """
    if not ZT_DB.exists():
        return []
    conn = sqlite3.connect(str(ZT_DB))
    try:
        rows = conn.execute(
            "SELECT code, hybk, lbc FROM zt_history WHERE date=? AND lbc>=2 AND lbc<=3 AND is_final=1",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    return [{"code": r[0], "hybk": r[1] or "", "lbc": int(r[2])} for r in rows]


def _sector_zt_count(date: str, industry: str) -> int:
    """板块涨停家数（sector_cycle._get_zt_count_by_date_industry，查 gene_scores.db）。失败降级 0。"""
    if not industry:
        return 0
    try:
        from strategies.sector_cycle import _get_zt_count_by_date_industry
        return _get_zt_count_by_date_industry(date, industry)
    except Exception:  # noqa: BLE001 — sector_cycle 失败降级 0（不臆造）
        return 0


def scan_pre_limitup(run_date: str, previous_trade_day: str | None = None) -> list[dict[str, Any]]:
    """S208: post-首板 relay candidate scanner（T10 auto-source）。

    Gathers lbc==1 首板 from zt_history T-1 + sector zt_count (sector_cycle)。
    **Drops high_gene**（死阈值 >=80 vs max 50.46 + 证否 0.942x，恒 0）。
    pit guard T-1 only（不取 T 日盘中）。zero em_get。

    Returns:
        list[dict]——每 dict 5 keys：{code, sector_rank:None, zt_count_today:int, lbc:1, high_gene:0}。
        喂 scan_early_admission(run_date, candidates, previous_trade_day)。
    """
    if not previous_trade_day:
        # T-1 = 前一交易日（非日历日 -1，跨周末/节假日取非交易日→0 picks）
        try:
            from vr_paths import prev_trading_date_str  # lazy import 避循环
            previous_trade_day = prev_trading_date_str(datetime.strptime(run_date, "%Y-%m-%d").date())
        except Exception:
            previous_trade_day = run_date

    candidates: list[dict[str, Any]] = []
    for fb in _zt_history_lbc1(previous_trade_day):
        zt_count = _sector_zt_count(previous_trade_day, fb["hybk"])
        candidates.append({
            "code": fb["code"],
            "sector_rank": None,  # MVP（gene_scores 无 sector_rank 列；early_admission 只快照不判定）
            "zt_count_today": zt_count,
            "lbc": 1,
            "high_gene": 0,  # DROPPED（死阈值 + 证否 0.942x，不扫 cutoff 反 data dredging）
        })
    return candidates


def scan_consecutive_relay(run_date: str, previous_trade_day: str | None = None) -> list[dict[str, Any]]:
    """S211: consecutive_relay arm candidate scanner（lbc>=2 连板接力，overnight gap path）。

    Gathers lbc>=2 连板 from zt_history T-1（signal date = previous_trade_day = run_date）。
    zero em_get（zt_history.db 离线）。pit guard T-1 only。

    Returns:
        list[dict]——每 dict {code, lbc}。喂 JournalRecorder._process_consecutive_relay。
        entry: D 日 close（一字板 filter），exit: D+1 open（overnight gap 捕获）。
    """
    # signal date = previous_trade_day = run_date（注释 :107，D 日连板 entry D close exit D+1 open）
    # 默认 = run_date 非 D-1 日历日（跨周末/节假日取非交易日→0 picks；caller 都显式传 target_date）
    if not previous_trade_day:
        previous_trade_day = run_date

    return [{"code": r["code"], "lbc": r["lbc"]} for r in _zt_history_lbc_ge2(previous_trade_day)]
