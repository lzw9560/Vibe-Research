#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首板次日溢价基线验证（首板流 spec 前置验证）。

假设：首板涨停股 T+1 开盘价相对 T 日收盘价存在正向溢价（alpha 基础）。
若次日无显著溢价 → 整个首板流 spec 无 alpha 基础，不应立项。

数据源（代码事实已查清）：
  - 涨停池：astock.em_zt_topic_pool("getTopicZTPool", YYYYMMDD, "fbt:asc") → list[dict]
    每项字段：c=code / n=name / p=price(÷1000) / lbc=连板数(1=首板) / zbc=炸板次数 ...
  - K 线：baostock 日K（前复权），优先读 ~/.vibe-research/baostock_kline_cache.json，
    缓存无则 baostock 实时取（每 50 股 re-login）。

设计：
  1. 遍历过去交易日（gene_scores.db eastmoney_live 日期列表，默认 30-120 天）
  2. 对每个 T：取涨停池，过滤 lbc=1（首板）
  3. 对每只首板：T 收盘价 = p÷1000；T+1 开盘价 = baostock K 线 T 下一行 open
  4. 溢价 = (T+1 open - T close) / T close * 100%
  5. 统计：N / mean / median / std / t / p / 正溢价占比 / 成本后净溢价（扣 0.4%）
  6. 存 JSON 到 ~/.vibe-research/first_board_premium_baseline.json

用法：cd backend && .venv/bin/python tools/first_board_premium_baseline.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

KLINE_CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "gene_scores.db"
OUT_JSON = ROOT / ".vibe-research" / "first_board_premium_baseline.json"

# 成本假设：佣金+滑点合计 0.4%（双侧，弱近似）
COST_PCT = 0.4

# baostock 每 N 股 re-login（防长会话超时返空）
RELOGIN_BATCH = 50


def _bs_code(code: str) -> str:
    """6 位代码 → baostock sh./sz. 前缀。"""
    if not code or len(code) != 6:
        return ""
    return f"sh.{code}" if code.startswith("6") else f"sz.{code}"


def _load_kline_cache() -> dict[str, list[dict]]:
    if not KLINE_CACHE.exists():
        return {}
    try:
        return json.loads(KLINE_CACHE.read_bytes())
    except Exception:
        return {}


def _fetch_baostock_bars(code: str, start_date: str, end_date: str, bs) -> list[dict]:
    """baostock qfq 日 K（start..end）。返 bars（date/open/close 等）。空/错返 []。"""
    bsc = _bs_code(code)
    if not bsc:
        return []
    fields = "date,open,high,low,close,volume,amount,turn,pctChg,isST"
    try:
        rs = bs.query_history_k_data_plus(
            bsc, fields, start_date=start_date, end_date=end_date, adjustflag="2",
        )
    except Exception:
        return []
    if rs.error_code != "0":
        return []
    bars: list[dict] = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({
                "date": d[0],
                "open": float(d[1]) if d[1] else 0.0,
                "close": float(d[4]) if d[4] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return bars


def _t1_open_from_cache(bars: list[dict], t_date: str) -> float | None:
    """缓存 bars（按 date 升序）中找 T 日下一行 open。T 日无 bar 则取首个 > T 的 bar。"""
    for i, b in enumerate(bars):
        if b["date"] > t_date:
            return b.get("open") or None
    return None


def _t1_close_check(bars: list[dict], t_date: str, t_close: float) -> bool:
    """缓存中 T 日 close 是否与涨停池 p÷1000 吻合（±2% 容差，验证字段口径）。"""
    for b in bars:
        if b["date"] == t_date:
            c = b.get("close") or 0
            if t_close <= 0 or c <= 0:
                return True  # 无法验证，放行
            return abs(c - t_close) / t_close < 0.02
    return True  # T 日 bar 不在缓存，放行（由 T+1 是否存在决定）


def _trading_dates_from_db() -> list[str]:
    """从 gene_scores.db eastmoney_live 取交易日列表（升序）。
    末尾日期的 T+1 可能超出缓存范围，由调用方按上限截止。"""
    if not DB.exists():
        return []
    conn = sqlite3.connect(str(DB), timeout=10)
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def _em_date(date_iso: str) -> str:
    """YYYY-MM-DD → YYYYMMDD。"""
    return date_iso.replace("-", "")


def main(days_back: int = 120) -> int:
    import astock

    # ---------- 交易日列表 ----------
    all_em_dates = _trading_dates_from_db()
    if not all_em_dates:
        print("[baseline] gene_scores.db 无 eastmoney_live 日期，中止")
        return 1

    # T+1 需在缓存范围内。缓存末尾日（通常 last bar）之后可能也有数据。
    cache = _load_kline_cache()
    if not cache:
        print("[baseline] baostock_kline_cache.json 不存在或为空，中止")
        return 1

    # 计算缓存覆盖的最大日期（所有股末 bar 的最大值）
    max_cache_date = "0"
    for bars in cache.values():
        if bars:
            last = bars[-1]["date"]
            if last > max_cache_date:
                max_cache_date = last

    # T 必须 < max_cache_date（否则 T+1 可能无数据）
    # days_back 限制：从最新 em_date 往回数
    cutoff = (datetime.strptime(max_cache_date, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
    dates = [d for d in all_em_dates if d < max_cache_date and d >= cutoff]
    if not dates:
        print(f"[baseline] 无满足条件的交易日（em_dates={len(all_em_dates)}, "
              f"max_cache_date={max_cache_date}, cutoff={cutoff}）")
        return 1

    print(f"[baseline] 交易日：{len(dates)}（{dates[0]} ~ {dates[-1]}），"
          f"cache max_date={max_cache_date}")

    # ---------- 遍历 T，取首板池 ----------
    first_boards: list[dict] = []  # {date, code, name, t_close, t1_open, premium}
    miss_codes: set[str] = set()  # 缓存无此股，需 baostock 实时补

    for di, t_date in enumerate(dates):
        t_compact = _em_date(t_date)
        try:
            pool = astock.em_zt_topic_pool("getTopicZTPool", t_compact, "fbt:asc") or []
        except Exception as e:
            print(f"[baseline] T={t_date} em_zt_topic_pool 失败: {e}")
            continue
        if not pool:
            print(f"[baseline] T={t_date} 涨停池为空")
            continue

        n_fb = 0
        for it in pool:
            lbc = it.get("lbc")
            # lbc=1 为首板；lbc 缺失/0 也视为首板（东财口径 1=首板）
            is_first = (str(lbc) == "1") or (lbc in (None, 0, "0"))
            if not is_first:
                continue
            code = str(it.get("c", ""))
            if not code or len(code) != 6:
                continue
            price_raw = it.get("p")
            if price_raw is None or price_raw <= 0:
                continue
            t_close = float(price_raw) / 1000.0  # p÷1000
            if t_close <= 0:
                continue

            # 从缓存取 T+1 open
            bars = cache.get(code, [])
            t1_open = _t1_open_from_cache(bars, t_date) if bars else None

            if t1_open is None:
                # 缓存无此股或无 T+1，标记需 baostock 补
                miss_codes.add(code)
                # 先记录，T+1 留 None
                first_boards.append({
                    "date": t_date, "code": code, "name": it.get("n", ""),
                    "t_close": t_close, "t1_open": None,
                    "source": "cache_miss",
                })
            else:
                # 口径校验（弱）：T 日缓存 close vs 涨停池 p÷1000
                ok = _t1_close_check(bars, t_date, t_close)
                first_boards.append({
                    "date": t_date, "code": code, "name": it.get("n", ""),
                    "t_close": t_close, "t1_open": t1_open,
                    "source": "cache" if ok else "cache_mismatch",
                })
            n_fb += 1
        print(f"[baseline] T={t_date} 涨停池={len(pool)} 首板={n_fb} "
              f"累计首板={len(first_boards)}", flush=True)

    # ---------- baostock 补 cache_miss ----------
    need_bs = [fb for fb in first_boards if fb["t1_open"] is None]
    if need_bs:
        # 去重 code
        uniq_codes = sorted({fb["code"] for fb in need_bs})
        print(f"[baseline] baostock 补 {len(uniq_codes)} 只 cache_miss 股 ...")
        try:
            import baostock as bs
        except ImportError:
            print("[baseline] baostock 未安装，cache_miss 股将跳过")
            bs = None

        if bs:
            def _login():
                lg = bs.login()
                return getattr(lg, "error_code", "0") == "0"

            if not _login():
                print("[baseline] baostock login 失败")
                bs = None

            if bs:
                # 每股取 T 附近一周 K 线（够找 T+1）
                fetched: dict[str, list[dict]] = {}
                t0 = time.time()
                for i, code in enumerate(uniq_codes):
                    if i and i % RELOGIN_BATCH == 0:
                        try:
                            bs.logout()
                        except Exception:
                            pass
                        if not _login():
                            print(f"[baseline] re-login 失败 @ {i}")
                            break
                        print(f"[baseline] re-login @ {i}/{len(uniq_codes)} "
                              f"elapsed={time.time()-t0:.0f}s", flush=True)
                    # 取该股所有首板日期的最小 T 和最大 T+1 窗口
                    fbs_for_code = [fb for fb in need_bs if fb["code"] == code]
                    if not fbs_for_code:
                        continue
                    min_t = min(fb["date"] for fb in fbs_for_code)
                    max_t = max(fb["date"] for fb in fbs_for_code)
                    start = (datetime.strptime(min_t, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
                    end = (datetime.strptime(max_t, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
                    bars = _fetch_baostock_bars(code, start, end, bs)
                    if not bars:
                        # re-login 重试一次
                        if _login():
                            bars = _fetch_baostock_bars(code, start, end, bs)
                    if not bars:
                        continue
                    fetched[code] = bars
                    # 填回 first_boards
                    for fb in fbs_for_code:
                        t1o = _t1_open_from_cache(bars, fb["date"])
                        if t1o is not None:
                            fb["t1_open"] = t1o
                            fb["source"] = "baostock"
                try:
                    bs.logout()
                except Exception:
                    pass

    # ---------- 计算溢价 ----------
    premiums: list[float] = []
    valid_boards: list[dict] = []
    for fb in first_boards:
        if fb["t1_open"] is None or fb["t1_open"] <= 0:
            continue
        tc = fb["t_close"]
        if tc <= 0:
            continue
        prem = (fb["t1_open"] - tc) / tc * 100.0
        fb["premium"] = prem
        premiums.append(prem)
        valid_boards.append(fb)

    N = len(premiums)
    if N == 0:
        print("[baseline] 无有效溢价样本，中止")
        return 1

    # 统计
    import numpy as np
    from scipy import stats

    arr = np.array(premiums, dtype=float)
    mean_pct = float(arr.mean())
    median_pct = float(np.median(arr))
    std_pct = float(arr.std(ddof=1)) if N > 1 else 0.0
    pos_count = int((arr > 0).sum())
    pos_ratio = pos_count / N

    # t 检验 H0: mean=0，单侧（溢价>0）
    t_stat, p_two = stats.ttest_1samp(arr, 0.0)
    p_one = p_two / 2 if t_stat > 0 else 1 - p_two / 2  # 单侧右尾

    # 成本后
    net_arr = arr - COST_PCT
    net_mean = float(net_arr.mean())
    net_pos_count = int((net_arr > 0).sum())
    net_pos_ratio = net_pos_count / N

    # ---------- 报告 ----------
    date_min = min(fb["date"] for fb in valid_boards)
    date_max = max(fb["date"] for fb in valid_boards)
    n_days = len({fb["date"] for fb in valid_boards})

    # 结论判定
    if p_one < 0.05 and mean_pct > 0:
        if net_pos_ratio >= 0.5:
            verdict = "溢价显著>0（p<0.05）且成本后正溢价占比≥50% → 首板流有 alpha 基础"
        else:
            verdict = "溢价显著>0（p<0.05）但成本后正溢价占比<50% → 成本吃掉 alpha，不可用"
    else:
        verdict = "溢价不显著（p>=0.05）→ 首板流无 alpha 基础"

    report = []
    report.append("=== 首板次日溢价基线验证 ===")
    report.append(f"样本：{N} 只首板涨停股，覆盖 {n_days} 个交易日（{date_min} ~ {date_max}）")
    report.append("")
    report.append(f"平均溢价：{'+' if mean_pct>=0 else ''}{mean_pct:.2f}%（±{std_pct:.2f}%）")
    report.append(f"中位数溢价：{'+' if median_pct>=0 else ''}{median_pct:.2f}%")
    report.append(f"正溢价占比：{pos_ratio*100:.1f}%（{pos_count}/{N}）")
    report.append("")
    report.append(f"t 统计量：{t_stat:.2f}")
    report.append(f"p 值（单侧）：{p_one:.4f}")
    report.append("")
    report.append(f"成本后（扣{COST_PCT}%）：")
    report.append(f"  平均净溢价：{'+' if net_mean>=0 else ''}{net_mean:.2f}%")
    report.append(f"  正净溢价占比：{net_pos_ratio*100:.1f}%（{net_pos_count}/{N}）")
    report.append("")
    report.append("结论：")
    report.append(f"  {verdict}")

    report_text = "\n".join(report)
    print()
    print(report_text)

    # 溢价分布（粗略分位）
    q_lo, q_25, q_50, q_75, q_hi = np.percentile(arr, [0, 25, 50, 75, 100])
    print(f"\n[分布分位] P0={q_lo:.2f} P25={q_25:.2f} P50={q_50:.2f} "
          f"P75={q_75:.2f} P100={q_hi:.2f}")

    # 数据来源占比
    src_counts: dict[str, int] = {}
    for fb in valid_boards:
        s = fb.get("source", "?")
        src_counts[s] = src_counts.get(s, 0) + 1
    print(f"[数据来源] {src_counts}")

    # ---------- 存 JSON ----------
    out = {
        "generated_at": datetime.now().isoformat(),
        "params": {
            "days_back": days_back,
            "cost_pct": COST_PCT,
            "date_range": [date_min, date_max],
            "n_days": n_days,
        },
        "stats": {
            "N": N,
            "mean_pct": round(mean_pct, 4),
            "median_pct": round(median_pct, 4),
            "std_pct": round(std_pct, 4),
            "t_stat": round(float(t_stat), 4),
            "p_one_sided": round(float(p_one), 6),
            "pos_ratio": round(pos_ratio, 4),
            "pos_count": pos_count,
            "net_mean_pct": round(net_mean, 4),
            "net_pos_ratio": round(net_pos_ratio, 4),
            "net_pos_count": net_pos_count,
        },
        "distribution": {
            "P0": round(float(q_lo), 4), "P25": round(float(q_25), 4),
            "P50": round(float(q_50), 4), "P75": round(float(q_75), 4),
            "P100": round(float(q_hi), 4),
        },
        "source_counts": src_counts,
        "verdict": verdict,
        "samples": [{"date": fb["date"], "code": fb["code"], "name": fb.get("name", ""),
                      "t_close": round(fb["t_close"], 4),
                      "t1_open": round(fb["t1_open"], 4) if fb["t1_open"] else None,
                      "premium": round(fb["premium"], 4)}
                     for fb in valid_boards],
    }
    try:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT_JSON.with_suffix(".json.tmp")
        tmp.write_bytes(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"))
        tmp.replace(OUT_JSON)
        print(f"\n[baseline] JSON 已存：{OUT_JSON}")
    except Exception as e:
        print(f"[baseline] 存 JSON 失败: {e}")

    return 0


if __name__ == "__main__":
    days = 120
    for i, a in enumerate(sys.argv[1:]):
        if a == "--days" and i + 2 < len(sys.argv):
            days = int(sys.argv[1:][i + 1])
    raise SystemExit(main(days))
