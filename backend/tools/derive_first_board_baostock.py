# -*- coding: utf-8 -*-
"""Baostock 派生涨停首板 60 日宇宙（§44v2 gap run 数据准备）。

从 baostock_kline_cache.json（5226 codes 复权 K 线）单遍派生 60 交易日首板宇宙，
交叉验证 vs 东财 zt_pool_hist_cache/zt_history.db + 同花顺 ths_limit_up_pool + hithink 涨停池。

涨停判定：close == round(prev_close × (1+limit), 2)（ROUND_HALF_UP 到分）。
prev_close 由 pctChg 反推（pctChg=真实日收益，不受前复权影响，self-contained per date）。
limit 按板块：ST 5% / 创业科创(300/301/688) 20% / 北交(4xx/8xx/920) 30% / 主板 10%。
首板 = 涨停(D) AND NOT 涨停(D-1)（集合差）。

baostock 无 IP 限制（无需防封）。东财用文件 cache（已落盘，无网络）；
ths 走 data.sources.eastmoney.ths_limit_up_pool（_ths_get 限流 + ths breaker）；
hithink 走 data.sources.hithink_src.limit_up_pool（circuit_breaker + 有界重试）。
输出 JSON 落 .vibe-research/first_board_universe_baostock_60d.json。

用法（backend/ cwd）：
  backend/.venv/bin/python backend/tools/derive_first_board_baostock.py
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
import decimal
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / ".vibe-research"
BACKEND = REPO / "backend"
CACHE = DATA / "baostock_kline_cache.json"
EM_POOL_HIST = DATA / "zt_pool_hist_cache.json"
EM_HISTORY_DB = DATA / "zt_history.db"
OUT = DATA / "first_board_universe_baostock_60d.json"
END_DATE = "2026-09-03"  # 60-day window 末（2026-09-04 仅 149 bars 不完整，排除）
WINDOW_SIZE = 60
TOL = 0.005  # 涨停价容差（分）
PCT_PREFILTER_SLACK = 0.6  # pctChg 粗筛下限 slack（10%板<9.4 排除 …）

# ths/hithink 4 路对齐采样日（均有东财数据，近端便于 live 源覆盖）
SAMPLE_DATES = ["2026-09-03", "2026-09-02", "2026-08-28"]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("derive_first_board")


# ── 涨停判定（纯函数，无 IO）──────────────────────────────────────────────────

def round_half_up(x: float) -> float:
    """交易所四舍五入到分（ROUND_HALF_UP）。"""
    return float(decimal.Decimal(str(x)).quantize(
        decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


def limit_pct(code: str, is_st: str) -> float:
    """板块涨停幅度（%）。ST5 / 创业科创20 / 北交30 / 主板10。"""
    if is_st == "1":
        return 5.0
    if code[:3] in ("300", "301") or code[:3] == "688":
        return 20.0
    if code[0] in ("4", "8") or code[:3] == "920":
        return 30.0
    return 10.0


def board_name(code: str, is_st: str) -> str:
    """板块名（报告用）。"""
    if is_st == "1":
        return "ST"
    if code[:3] in ("300", "301") or code[:3] == "688":
        return "创业科创"
    if code[0] in ("4", "8") or code[:3] == "920":
        return "北交"
    return "主板"


def prev_close_from_pct(close: float, pct: float) -> float:
    """从 pctChg 反推真实 prev_close（pctChg=真实日收益，不受复权影响）。"""
    denom = 1.0 + pct / 100.0
    return close / denom if denom != 0 else close


def is_limit_up(code: str, bar: dict) -> bool:
    """bar 是否涨停。close == round(prev×(1+limit),2) ±0.005（prev 由 pctChg 反推）。"""
    lp = limit_pct(code, bar["isST"])
    if bar["pctChg"] < lp - PCT_PREFILTER_SLACK:  # 粗筛
        return False
    pc = prev_close_from_pct(bar["close"], bar["pctChg"])
    lim = round_half_up(pc * (1.0 + lp / 100.0))
    return abs(bar["close"] - lim) <= TOL


# ── 派生（baostock cache → zt/fb 集合）─────────────────────────────────────────

def load_cache() -> tuple[dict, dict[str, dict]]:
    """加载 baostock cache，返 (raw, code→{date:bar} 索引)。"""
    t0 = time.time()
    raw = json.loads(CACHE.read_bytes())
    codebars = {c: {b["date"]: b for b in bars} for c, bars in raw.items()}
    log.info(f"[load] {len(raw)} codes, {time.time()-t0:.1f}s")
    return raw, codebars


def get_window(codebars: dict) -> list[str]:
    """60 交易日窗口 ending END_DATE（+1 prior 供 window[0] 的 D-1 判定）。"""
    all_dates = sorted({b["date"] for bd in codebars.values() for b in bd.values()})
    eidx = all_dates.index(END_DATE)
    window = all_dates[eidx - WINDOW_SIZE + 1: eidx + 1]
    assert len(window) == WINDOW_SIZE, f"window size {len(window)} != {WINDOW_SIZE}"
    log.info(f"[window] {window[0]} -> {window[-1]} ({len(window)} days)")
    return window


def derive_zt(codebars: dict, dates: list[str]) -> dict[str, set[str]]:
    """单遍派生 dates 内每日涨停集合。返 {date: set(code)}。self-contained per bar。"""
    t0 = time.time()
    wset = set(dates)
    zt_by_date: dict[str, set[str]] = defaultdict(set)
    for code, bd in codebars.items():
        for dt, b in bd.items():
            if dt not in wset:
                continue
            if is_limit_up(code, b):
                zt_by_date[dt].add(code)
    log.info(f"[derive_zt] {len(dates)} dates, {time.time()-t0:.1f}s")
    return dict(zt_by_date)


def derive_first_boards(
    zt_by_date: dict[str, set[str]], window: list[str], prior: str | None
) -> dict[str, set[str]]:
    """首板 = 涨停(D) - 涨停(D-1)。window[0] 的 D-1 用 prior（多算 1 日 zt）。"""
    fb_by_date: dict[str, set[str]] = {}
    for i, dt in enumerate(window):
        cur = zt_by_date.get(dt, set())
        prev_dt = window[i - 1] if i > 0 else prior
        prev = zt_by_date.get(prev_dt, set()) if prev_dt else set()
        fb_by_date[dt] = cur - prev
    return fb_by_date


def build_records(
    codebars: dict, fb_by_date: dict[str, set[str]], window: list[str]
) -> list[dict]:
    """首板 flat 记录（code+date+limit+板块+close+pctChg+prev_close+limit_price）。"""
    records: list[dict] = []
    for dt in window:
        for code in sorted(fb_by_date.get(dt, set())):
            b = codebars[code].get(dt)
            if not b:
                continue
            lp = limit_pct(code, b["isST"])
            pc = prev_close_from_pct(b["close"], b["pctChg"])
            records.append({
                "code": code, "date": dt,
                "close": b["close"], "pctChg": b["pctChg"],
                "limit_pct": lp, "board": board_name(code, b["isST"]),
                "isST": b["isST"] == "1",
                "prev_close": round(pc, 4),
                "limit_price": round_half_up(pc * (1.0 + lp / 100.0)),
            })
    return records


def build_daily(zt_by_date, fb_by_date, window) -> dict[str, dict]:
    daily = {}
    for dt in window:
        zt = len(zt_by_date.get(dt, set()))
        fb = len(fb_by_date.get(dt, set()))
        daily[dt] = {"zt": zt, "first_board": fb, "lianban": zt - fb}
    return daily


def save_output(records, daily, window, prior) -> Path:
    out = {
        "meta": {
            "source": "baostock_kline_cache.json",
            "method": "close==round(prev_close*(1+limit),2); prev_close from pctChg "
                      "(real daily return, forward-split robust); first_board=zt(D)-zt(D-1)",
            "window": [window[0], window[-1]],
            "window_days": len(window),
            "prior_date_for_window0": prior,
            "end_date": END_DATE,
            "limit_rules": "ST5% / 创业科创(300/301/688)20% / 北交(4xx/8xx/920)30% / 主板10%",
            "tolerance": TOL,
            "note": "2026-09-04 excluded (149 bars incomplete); new-IPO first-day +44% "
                    "may be mis-treated as 20% (known divergence); D-1 no-data treated as 非涨停",
        },
        "totals": {
            "first_board": len(records),
            "zt": sum(d["zt"] for d in daily.values()),
            "lianban": sum(d["lianban"] for d in daily.values()),
        },
        "daily": daily,
        "first_boards": records,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info(f"[save] {OUT} ({len(records)} first_board records)")
    return OUT


# ── 交叉验证：东财（文件 cache，无网络）──────────────────────────────────────

def _norm(code: str) -> str:
    """归一 code 到 6 位（去前缀/补零）。"""
    return str(code).strip().zfill(6)[-6:]


def cross_validate_em_history(zt_by_date, fb_by_date, window) -> dict:
    """vs zt_history.db（lbc=1=首板）。涨停 + 首板 recall。东财为准。

    stale-phantom 检测：东财某日 codes >90% 重复 prior 日 = stale re-snapshot
    （如 Aug26 100% dup of Aug25，is_final=0 的 16:00 不完整快照）→ 单独算 clean recall。
    """
    if not EM_HISTORY_DB.exists():
        log.warning("[xval em_history] zt_history.db 不存在，跳过")
        return {}
    conn = sqlite3.connect(str(EM_HISTORY_DB))
    em_dates = sorted({r[0] for r in conn.execute("SELECT DISTINCT date FROM zt_history")})
    # 预取每日 em_zt / em_fb（lbc=1=首板）
    em_zt_by_date: dict[str, set[str]] = {}
    em_fb_by_date: dict[str, set[str]] = {}
    for dt in em_dates:
        em_zt_by_date[dt] = {_norm(r[0]) for r in conn.execute(
            "SELECT code FROM zt_history WHERE date=?", (dt,))}
        em_fb_by_date[dt] = {_norm(r[0]) for r in conn.execute(
            "SELECT code FROM zt_history WHERE date=? AND lbc=1", (dt,))}
    conn.close()
    overlap = [d for d in window if d in em_zt_by_date]
    # stale-phantom：东财某日 >90% 重复 prior overlap 日 codes
    stale_dates: set[str] = set()
    for i, dt in enumerate(overlap):
        if i == 0:
            continue
        cur = em_zt_by_date.get(dt, set())
        prev = em_zt_by_date.get(overlap[i - 1], set())
        if prev and cur and len(cur & prev) / len(cur) > 0.90:
            stale_dates.add(dt)
    tot_em_zt = tot_em_fb = match_zt = match_fb = 0
    cle_tot_zt = cle_tot_fb = cle_match_zt = cle_match_fb = 0
    bs_only_fb: list[str] = []
    em_only_fb: list[str] = []
    per_date = []
    for dt in overlap:
        em_zt = em_zt_by_date[dt]
        em_fb = em_fb_by_date[dt]
        bs_zt = zt_by_date.get(dt, set())
        bs_fb = fb_by_date.get(dt, set())
        mz = len(bs_zt & em_zt)
        mf = len(bs_fb & em_fb)
        match_zt += mz
        match_fb += mf
        tot_em_zt += len(em_zt)
        tot_em_fb += len(em_fb)
        if dt not in stale_dates:  # clean（去 stale phantom）
            cle_match_zt += mz
            cle_match_fb += mf
            cle_tot_zt += len(em_zt)
            cle_tot_fb += len(em_fb)
        for c in (bs_fb - em_fb):
            bs_only_fb.append(c)
        for c in (em_fb - bs_fb):
            em_only_fb.append(c)
        per_date.append({
            "date": dt, "em_zt": len(em_zt), "bs_zt": len(bs_zt), "zt_match": mz,
            "em_fb": len(em_fb), "bs_fb": len(bs_fb), "fb_match": mf,
            "stale": dt in stale_dates,
        })
    recall_zt = (match_zt / tot_em_zt * 100) if tot_em_zt else 0
    recall_fb = (match_fb / tot_em_fb * 100) if tot_em_fb else 0
    cle_recall_zt = (cle_match_zt / cle_tot_zt * 100) if cle_tot_zt else 0
    cle_recall_fb = (cle_match_fb / cle_tot_fb * 100) if cle_tot_fb else 0
    log.info(f"[xval em_history] 涨停 recall {match_zt}/{tot_em_zt} = {recall_zt:.1f}% "
             f"| 首板 recall {match_fb}/{tot_em_fb} = {recall_fb:.1f}% ({len(overlap)} overlap)")
    log.info(f"  clean（ex stale phantom {sorted(stale_dates) or '无'}）: "
             f"涨停 {cle_match_zt}/{cle_tot_zt} = {cle_recall_zt:.1f}% "
             f"| 首板 {cle_match_fb}/{cle_tot_fb} = {cle_recall_fb:.1f}%")
    return {
        "overlap_dates": len(overlap),
        "recall_zt_pct": round(recall_zt, 1),
        "recall_fb_pct": round(recall_fb, 1),
        "clean_recall_zt_pct": round(cle_recall_zt, 1),
        "clean_recall_fb_pct": round(cle_recall_fb, 1),
        "stale_dates": sorted(stale_dates),
        "bs_only_fb_sample": bs_only_fb[:20],
        "em_only_fb_sample": em_only_fb[:20],
        "per_date": per_date,
    }


def cross_validate_em_pool(zt_by_date, window) -> dict:
    """vs zt_pool_hist_cache.json（东财涨停池 daily snapshot，code only 无 lbc）。涨停 recall。"""
    if not EM_POOL_HIST.exists():
        log.warning("[xval em_pool] zt_pool_hist_cache.json 不存在，跳过")
        return {}
    hist = json.loads(EM_POOL_HIST.read_bytes())
    tot = match = n_dates = 0
    bs_only: list[str] = []
    em_only: list[str] = []
    aug26_note = ""
    for dt in window:
        key = dt.replace("-", "")
        em = {_norm(it["code"]) for it in hist.get(key, []) if it.get("code")}
        if not em:
            continue  # 空快照（Jul9~Aug14 空）跳过
        bs = zt_by_date.get(dt, set())
        n_dates += 1
        match += len(bs & em)
        tot += len(em)
        for c in (bs - em):
            bs_only.append(c)
        for c in (em - bs):
            em_only.append(c)
        if key == "20260826":  # 已知 stale-snapshot artifact
            a25 = {_norm(it["code"]) for it in hist.get("20260825", []) if it.get("code")}
            dup = len(em & a25)
            aug26_note = f"Aug26: {dup}/{len(em)} = {dup/len(em)*100:.0f}% dup of Aug25 (stale snapshot)"
    recall = (match / tot * 100) if tot else 0
    log.info(f"[xval em_pool] 涨停 recall {match}/{tot} = {recall:.1f}% ({n_dates} non-empty dates)")
    if aug26_note:
        log.info(f"  {aug26_note}")
    return {
        "non_empty_dates": n_dates, "recall_zt_pct": round(recall, 1),
        "bs_only_sample": bs_only[:20], "em_only_sample": em_only[:20],
        "aug26_stale_note": aug26_note,
    }


# ── 交叉验证：同花顺 + hithink（live，防封路径，2-3 日）────────────────────────

def _import_project() -> None:
    """注入 backend/ 到 sys.path（backend 非 package，root-level import）。"""
    b = str(BACKEND)
    if b not in sys.path:
        sys.path.insert(0, b)


def cross_validate_ths(zt_by_date, fb_by_date, dates) -> dict:
    """vs ths_limit_up_pool（_ths_get 限流 + ths breaker）。high_days '1天1板'=首板。"""
    _import_project()
    try:
        from data.sources.eastmoney import ths_limit_up_pool
    except Exception as e:
        log.warning(f"[xval ths] import 失败: {e}")
        return {"status": "import_failed", "error": str(e)}
    result = {}
    for dt in dates:
        d = dt.replace("-", "")
        try:
            items = ths_limit_up_pool(d)  # 走 _ths_get 防封
        except Exception as e:
            log.warning(f"[xval ths] {dt} 请求失败: {e}")
            result[dt] = {"status": "request_failed", "error": str(e)}
            continue
        ths_zt = {_norm(it["code"]) for it in items if it.get("code")}
        ths_fb = {_norm(it["code"]) for it in items
                   if it.get("high_days") == "首板"}  # ths 用"首板"标记首板（非"1天1板"）
        bs_zt = zt_by_date.get(dt, set())
        bs_fb = fb_by_date.get(dt, set())
        result[dt] = {
            "ths_zt": len(ths_zt), "bs_zt": len(bs_zt),
            "zt_match": len(bs_zt & ths_zt),
            "ths_fb": len(ths_fb), "bs_fb": len(bs_fb),
            "fb_match": len(bs_fb & ths_fb),
            "recall_zt_pct": round(len(bs_zt & ths_zt) / len(ths_zt) * 100, 1) if ths_zt else 0,
        }
        log.info(f"[xval ths] {dt}: 涨停 ths={len(ths_zt)} bs={len(bs_zt)} "
                 f"match={len(bs_zt & ths_zt)} | 首板 ths={len(ths_fb)} bs={len(bs_fb)} "
                 f"match={len(bs_fb & ths_fb)}")
        time.sleep(5)  # ths 限流：≥4-5s 间隔
    return result


def cross_validate_hithink(zt_by_date, dates) -> dict:
    """vs hithink limit_up_pool（circuit_breaker + 有界重试，key via .env load_dotenv）。"""
    _import_project()
    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env")  # HITHINK_FINANCE_API_KEY（不裸读 .env 内容）
    except Exception as e:
        log.warning(f"[xval hithink] load_dotenv 失败: {e}")
    try:
        from data.sources.hithink_src import limit_up_pool
    except Exception as e:
        log.warning(f"[xval hithink] import 失败: {e}")
        return {"status": "import_failed", "error": str(e)}
    result = {}
    for dt in dates:
        try:
            items = limit_up_pool(dt)  # 走 circuit_breaker 防封
        except Exception as e:
            log.warning(f"[xval hithink] {dt} 请求失败: {e}")
            result[dt] = {"status": "request_failed", "error": str(e)}
            continue
        if not items:
            log.info(f"[xval hithink] {dt}: 空（熔断/Key/endpoint 不契）")
            result[dt] = {"status": "empty", "hi_zt": 0}
            continue
        hi_zt = {_norm(it["code"]) for it in items if it.get("code")}
        bs_zt = zt_by_date.get(dt, set())
        result[dt] = {
            "hi_zt": len(hi_zt), "bs_zt": len(bs_zt),
            "zt_match": len(bs_zt & hi_zt),
            "recall_zt_pct": round(len(bs_zt & hi_zt) / len(hi_zt) * 100, 1) if hi_zt else 0,
            "sample_item": items[0] if items else None,
        }
        log.info(f"[xval hithink] {dt}: 涨停 hi={len(hi_zt)} bs={len(bs_zt)} "
                 f"match={len(bs_zt & hi_zt)}")
        time.sleep(2)
    return result


# ── 分歧分析（bs-only 多判 / em-only 漏）───────────────────────────────────────

def divergence_breakdown(em_only_codes: list[str], bs_only_codes: list[str],
                         codebars: dict) -> dict:
    """em-only（东财有 baostock 漏）+ bs-only（baostock 多判）按板块/ST 归类。"""
    def classify(codes: list[str]) -> dict:
        by_board: dict[str, int] = defaultdict(int)
        st = 0
        for c in codes:
            c = _norm(c)
            b = codebars.get(c, {})
            is_st = "0"
            # 取任一 bar 的 isST
            for bb in b.values():
                is_st = bb.get("isST", "0")
                break
            if is_st == "1":
                st += 1
                by_board["ST"] += 1
            elif c[:3] in ("300", "301") or c[:3] == "688":
                by_board["创业科创"] += 1
            elif c[0] in ("4", "8") or c[:3] == "920":
                by_board["北交"] += 1
            else:
                by_board["主板"] += 1
        return {"total": len(codes), "by_board": dict(by_board), "st_count": st}
    return {
        "em_only_baostock_missed": classify(em_only_codes),
        "bs_only_baostock_extra": classify(bs_only_codes),
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    raw, codebars = load_cache()
    window = get_window(codebars)
    # 多算 1 个 prior 日，供 window[0] 的 D-1 判定（避免 window[0] 全当首板）
    all_dates = sorted({b["date"] for bd in codebars.values() for b in bd.values()})
    eidx = all_dates.index(END_DATE)
    prior = all_dates[eidx - WINDOW_SIZE] if eidx - WINDOW_SIZE >= 0 else None
    zt_dates = window + ([prior] if prior else [])

    zt_by_date = derive_zt(codebars, zt_dates)
    fb_by_date = derive_first_boards(zt_by_date, window, prior)
    records = build_records(codebars, fb_by_date, window)
    daily = build_daily(zt_by_date, fb_by_date, window)

    total_zt = sum(d["zt"] for d in daily.values())
    total_fb = len(records)
    total_lb = total_zt - total_fb
    log.info(f"[totals] 60d 涨停={total_zt} 首板={total_fb} 连板={total_lb}")
    # 逐日样本（首尾各 5 + 全部日数简表）
    log.info("[daily] 首尾各 5 日：")
    for dt in window[:5] + window[-5:]:
        d = daily[dt]
        log.info(f"  {dt}: zt={d['zt']:>3} fb={d['first_board']:>3} lb={d['lianban']:>3}")

    out_path = save_output(records, daily, window, prior)

    # 交叉验证
    log.info("\n=== 交叉验证：东财 zt_history.db（lbc=1=首板）===")
    em_hist = cross_validate_em_history(zt_by_date, fb_by_date, window)
    log.info("\n=== 交叉验证：东财 zt_pool_hist_cache.json（涨停池）===")
    em_pool = cross_validate_em_pool(zt_by_date, window)

    # 分歧分析（em_history 的 em-only/bs-only 首板）
    div: dict = {}
    if em_hist:
        div = divergence_breakdown(
            em_hist.get("em_only_fb_sample", []),
            em_hist.get("bs_only_fb_sample", []),
            codebars,
        )
        if div.get("em_only_baostock_missed"):
            log.info(f"[div] em-only(漏) {div['em_only_baostock_missed']}")
        if div.get("bs_only_baostock_extra"):
            log.info(f"[div] bs-only(多判) {div['bs_only_baostock_extra']}")

    log.info("\n=== 交叉验证：同花顺 ths_limit_up_pool（live，_ths_get 防封）===")
    ths = cross_validate_ths(zt_by_date, fb_by_date, SAMPLE_DATES)
    log.info("\n=== 交叉验证：hithink limit_up_pool（live，circuit_breaker 防封）===")
    hithink = cross_validate_hithink(zt_by_date, SAMPLE_DATES)

    # 汇总报告
    log.info("\n" + "=" * 70)
    log.info("=== 汇总报告 ===")
    log.info(f"输出: {out_path}")
    log.info(f"60 日首板总数: {total_fb}（涨停 {total_zt} / 连板 {total_lb}）")
    if em_hist:
        log.info(f"东财 zt_history: 涨停 recall {em_hist['recall_zt_pct']}% "
                 f"| 首板 recall {em_hist['recall_fb_pct']}% "
                 f"({em_hist['overlap_dates']} overlap)")
        log.info(f"  clean（ex stale phantom {em_hist.get('stale_dates', [])}）: "
                 f"涨停 {em_hist.get('clean_recall_zt_pct')}% "
                 f"| 首板 {em_hist.get('clean_recall_fb_pct')}%")
    if em_pool:
        log.info(f"东财 zt_pool: 涨停 recall {em_pool['recall_zt_pct']}% "
                 f"({em_pool['non_empty_dates']} non-empty dates)")
        if em_pool.get("aug26_stale_note"):
            log.info(f"  {em_pool['aug26_stale_note']}")
    if ths:
        for dt, r in ths.items():
            if isinstance(r, dict) and "zt_match" in r:
                log.info(f"ths {dt}: 涨停 recall {r['recall_zt_pct']}% "
                         f"(ths={r['ths_zt']} bs={r['bs_zt']} match={r['zt_match']})")
            elif isinstance(r, dict):
                log.info(f"ths {dt}: {r.get('status', r)}")
    if hithink:
        for dt, r in hithink.items():
            if isinstance(r, dict) and "zt_match" in r:
                log.info(f"hithink {dt}: 涨停 recall {r['recall_zt_pct']}% "
                         f"(hi={r['hi_zt']} bs={r['bs_zt']} match={r['zt_match']})")
            elif isinstance(r, dict):
                log.info(f"hithink {dt}: {r.get('status', r)}")
    log.info("\n已知口径分歧（诚实标注）：")
    log.info("  - ST +5%: baostock 用 isST 字段判 5% 限，东财涨停池口径可能不同 → baostock 多判")
    log.info("  - 创业/科创新股首日 +44%: baostock 误按 20% 限判定 → baostock 多判（false positive）")
    log.info("  - 一字板: prev_close 由 pctChg 反推，一字板封死时口径边界，可能 ±1 漂移")
    log.info("  - 北交所(4xx/8xx/920): baostock 覆盖与东财涨停池口径可能不一致")
    log.info("  - Aug26 zt_history.db stale: 100% dup of Aug25 (is_final=0 的 16:00 不完整快照) "
             "→ baostock 正确规避；zt_pool_hist_cache Aug26 非 dup（25% carryover，真实快照）")


if __name__ == "__main__":
    main()
