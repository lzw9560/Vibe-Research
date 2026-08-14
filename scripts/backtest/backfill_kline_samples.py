# -*- coding: utf-8 -*-
"""S066 Phase 0a: BaoStock 批量回填 kline → backtest_samples.json

从 gene_scores.db 取全部 (date, code) 对（~6600 条 / ~1121 独立 code），
用 BaoStock qfq 日K（含 turn/pctChg/amount/open/high/low/close）批量拉取，
对每条匹配 next_bar，计算 gap_pct / fill_rate / 四种次日收益 + benchmark。

输出：.vibe-research/backtest_samples.json

零 em_get（BaoStock 独立免费源，不封 IP 不限流不要 token）。
诚实边界：signal 日为最后一日时无 next_bar → 标 missing_next_bar，不计入收益统计。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import baostock as bs

REPO = Path(__file__).resolve().parent.parent.parent
DB = REPO / ".vibe-research" / "gene_scores.db"
OUT = REPO / ".vibe-research" / "backtest_samples.json"
KLINE_CACHE = REPO / ".vibe-research" / "baostock_kline_cache.json"

FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg,isST"
# 拉取窗口：gene_scores 最早 2026-01-05，多取前 5 日防匹配漂移，后多取 10 日保 next_bar
START_DATE = "2025-12-25"
END_DATE = "2026-08-14"
SLEEP_BETWEEN_CODES = 0.8  # BaoStock 不限流，保守间隔防超时返空


def code_to_baostock(code: str) -> str:
    """A 股代码 → BaoStock 代码。6 开头 sh，否则 sz。"""
    if code.startswith("6"):
        return f"sh.{code}"
    return f"sz.{code}"


def load_samples() -> list[dict]:
    """从 gene_scores.db 取全部 (date, code) + 5 因子。"""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT date, code, name, total_score, factor_premium_rate, factor_red_rate,
                  factor_seal_rate, factor_rebound_rate, factor_freq_score,
                  wilson_adjusted, qualify, high_gene, zt_count_250d
           FROM gene_scores ORDER BY date, code"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_klines(bs_code: str, _retry: int = 0) -> list[dict]:
    """BaoStock qfq 日K，返回 [{date, open, high, low, close, volume, amount, turn, pctChg, isST}]。

    空结果时尝试 re-login 重试一次（BaoStock 长会话可能超时返空）。
    """
    rs = bs.query_history_k_data_plus(
        bs_code, FIELDS,
        start_date=START_DATE, end_date=END_DATE, adjustflag="2",
    )
    if rs.error_code != "0":
        if _retry < 1:
            bs.logout()
            bs.login()
            return fetch_klines(bs_code, _retry + 1)
        return []
    bars = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({
                "date": d[0],
                "open": float(d[1]) if d[1] else 0.0,
                "high": float(d[2]) if d[2] else 0.0,
                "low": float(d[3]) if d[3] else 0.0,
                "close": float(d[4]) if d[4] else 0.0,
                "volume": float(d[5]) if d[5] else 0.0,
                "amount": float(d[6]) if d[6] else 0.0,
                "turn": float(d[7]) if d[7] else 0.0,
                "pctChg": float(d[8]) if d[8] else 0.0,
                "isST": d[9],
            })
        except (ValueError, IndexError):
            continue
    if not bars and _retry < 1:
        bs.logout()
        bs.login()
        return fetch_klines(bs_code, _retry + 1)
    return bars


def match_next_bar(bars: list[dict], signal_date: str) -> tuple[dict | None, dict | None]:
    """在 bars 中找 signal_date 的 bar 和它的 next_bar。
    返回 (signal_bar, next_bar)，缺失返 (None, None)。
    """
    idx = None
    for i, b in enumerate(bars):
        if b["date"] == signal_date:
            idx = i
            break
    if idx is None:
        return None, None
    if idx + 1 >= len(bars):
        return bars[idx], None  # 最后一日，无 next_bar
    return bars[idx], bars[idx + 1]


def compute_sample(sample: dict, signal_bar: dict, next_bar: dict | None) -> dict:
    """计算单样本的 gap/fill/returns。"""
    close = signal_bar["close"]  # 涨停日收盘 = 涨停价（封板）
    result = {
        **sample,
        "signal_close": close,
        "signal_turn": signal_bar["turn"],
        "signal_amount": signal_bar["amount"],
        "signal_pctChg": signal_bar["pctChg"],
    }
    if next_bar is None:
        result["missing_next_bar"] = True
        result["gap_pct"] = None
        result["fillable"] = None
        result["return_close2close"] = None
        result["return_open2close"] = None
        result["return_open2high"] = None
        result["return_open2low"] = None
        result["next_pctChg"] = None
        return result

    next_open = next_bar["open"]
    result["missing_next_bar"] = False
    result["next_open"] = next_open
    result["next_close"] = next_bar["close"]
    result["next_high"] = next_bar["high"]
    result["next_low"] = next_bar["low"]
    result["next_turn"] = next_bar["turn"]
    result["next_amount"] = next_bar["amount"]
    result["next_pctChg"] = next_bar["pctChg"]

    # gap_pct = (next_open - close) / close * 100
    if close > 0:
        result["gap_pct"] = round((next_open - close) / close * 100, 4)
    else:
        result["gap_pct"] = None

    # fillable: next_open < close(涨停价) → 非一字板，可买
    result["fillable"] = next_open < close

    # 四种收益
    if close > 0:
        result["return_close2close"] = round((next_bar["close"] - close) / close * 100, 4)
    else:
        result["return_close2close"] = None
    if next_open > 0:
        result["return_open2close"] = round((next_bar["close"] - next_open) / next_open * 100, 4)
        result["return_open2high"] = round((next_bar["high"] - next_open) / next_open * 100, 4)
        result["return_open2low"] = round((next_bar["low"] - next_open) / next_open * 100, 4)
    else:
        result["return_open2close"] = None
        result["return_open2high"] = None
        result["return_open2low"] = None
    return result


def compute_benchmarks(samples: list[dict]) -> dict:
    """benchmark_A: 全样本次日红盘率；benchmark_B: CSI300 次日上涨率。"""
    valid = [s for s in samples if not s.get("missing_next_bar") and s.get("next_pctChg") is not None]
    if valid:
        red_count = sum(1 for s in valid if s["next_pctChg"] > 0)
        benchmark_A = round(red_count / len(valid) * 100, 2)
    else:
        benchmark_A = None

    # benchmark_B: CSI300 次日上涨率（独立拉取）
    benchmark_B = compute_csi300_benchmark()
    return {
        "benchmark_A": benchmark_A,  # 全涨停股次日红盘率
        "benchmark_A_n": len(valid),
        "benchmark_B": benchmark_B["win_rate"],
        "benchmark_B_n": benchmark_B["n"],
    }


def compute_csi300_benchmark() -> dict:
    """CSI300 次日上涨概率。从 BaoStock 拉 sh.000300 指数日K。"""
    rs = bs.query_history_k_data_plus(
        "sh.000300", "date,close,pctChg",
        start_date=START_DATE, end_date=END_DATE, adjustflag="3",
    )
    bars = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({"date": d[0], "close": float(d[1]) if d[1] else 0, "pctChg": float(d[2]) if d[2] else 0})
        except (ValueError, IndexError):
            continue
    if len(bars) < 2:
        return {"win_rate": None, "n": 0}
    up_count = sum(1 for b in bars if b["pctChg"] > 0)
    return {"win_rate": round(up_count / len(bars) * 100, 2), "n": len(bars)}


def load_kline_cache() -> dict:
    if KLINE_CACHE.exists():
        try:
            return json.loads(KLINE_CACHE.read_text())
        except Exception:
            return {}
    return {}


def save_kline_cache(cache: dict) -> None:
    KLINE_CACHE.write_text(json.dumps(cache, ensure_ascii=False))


def main() -> int:
    samples = load_samples()
    print(f"[0a] gene_scores 样本: {len(samples)} 条")

    codes = sorted(set(s["code"] for s in samples))
    print(f"[0a] 独立 code: {len(codes)} 个")

    cache = load_kline_cache()
    print(f"[0a] kline 缓存: {len(cache)} 个 code 已有")

    lg = bs.login()
    if lg.error_code != "0":
        print(f"[0a] BaoStock login 失败: {lg.error_msg}", file=sys.stderr)
        return 1

    # 按 code 分组 samples
    by_code: dict[str, list[dict]] = {}
    for s in samples:
        by_code.setdefault(s["code"], []).append(s)

    results: list[dict] = []
    codes_done = 0
    codes_with_data = 0
    codes_failed = 0

    for code in codes:
        if code in cache and cache[code]:
            bars = cache[code]
        else:
            bs_code = code_to_baostock(code)
            bars = fetch_klines(bs_code)
            cache[code] = bars
            save_kline_cache(cache)
            time.sleep(SLEEP_BETWEEN_CODES)
            codes_done += 1
            if codes_done % 50 == 0:
                print(f"[0a] 进度: {codes_done}/{len(codes)} code 拉取完成", flush=True)

        if not bars:
            codes_failed += 1
            # 该 code 的所有 sample 标 missing
            for s in by_code.get(code, []):
                results.append({**s, "missing_next_bar": True, "error": "no_kline_data"})
            continue

        codes_with_data += 1
        for s in by_code[code]:
            signal_bar, next_bar = match_next_bar(bars, s["date"])
            if signal_bar is None:
                results.append({**s, "missing_next_bar": True, "error": "signal_date_not_in_kline"})
                continue
            results.append(compute_sample(s, signal_bar, next_bar))

    bs.logout()

    benchmarks = compute_benchmarks(results)

    # 统计
    total = len(results)
    missing = sum(1 for r in results if r.get("missing_next_bar"))
    fillable = sum(1 for r in results if r.get("fillable") is True)
    has_return = sum(1 for r in results if r.get("return_open2close") is not None)

    output = {
        "meta": {
            "source": "baostock_qfq",
            "total_samples": total,
            "missing_next_bar": missing,
            "fillable_count": fillable,
            "has_return_count": has_return,
            "codes_total": len(codes),
            "codes_with_data": codes_with_data,
            "codes_failed": codes_failed,
        },
        "benchmarks": benchmarks,
        "samples": results,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False))
    print(f"[0a] 输出: {OUT}")
    print(f"[0a] 总样本 {total}, missing_next_bar {missing}, 有收益 {has_return}")
    print(f"[0a] benchmark_A(涨停股次日红盘率)={benchmarks['benchmark_A']}% (n={benchmarks['benchmark_A_n']})")
    print(f"[0a] benchmark_B(CSI300次日上涨率)={benchmarks['benchmark_B']}% (n={benchmarks['benchmark_B_n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
