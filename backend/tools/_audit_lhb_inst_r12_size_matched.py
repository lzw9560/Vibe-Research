# -*- coding: utf-8 -*-
"""R12 size-matched BHAR——inst_dominant vs 全市场同 decile peers（优化版 sliding window）。

inst_dominant walk-forward OOS edge-confirmed（train+0.426%/test+0.345% 都 PASS）。
但须 R12 排除 size premium（playbook 59% 部分是 size，S2 微盘 91% 是 size 的教训）。
预检 _audit_lhb_inst_size_decile.py: inst_dominant decile1-3 占30%基线（不偏小盘）。

优化：per-code 一次扫，sliding window 20d_amt（O(1) per bar）+ date_idx BHAR（O(N) per code）。
原版 per-bar slice [-20:] 是 O(N×20)，5248 codes × 2123 days = 1100万 × 20 = 2.2亿 ops ~50分钟。
优化版 O(N) per code = 1100万 ops ~10秒。
"""
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf
import bisect

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"
INST_KEYWORDS = ("机构专用", "总部", "高盛", "瑞银", "股通", "摩根", "中信证券股份有限公司上海分公司", "国际金融")
STOP_PCT = -3.0
ALPHA = 0.05


def load_inst_dominant_picks() -> list:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy, net "
        "FROM dragon_tiger_rows WHERE side='buy' AND buy > 0"
    ).fetchall()
    conn.close()
    picks_by_dc: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks_by_dc[(date, code)].append((dept or "", buy or 0, net or 0))
    inst: list = []
    for (date, code), seats in picks_by_dc.items():
        total = sum(s[1] for s in seats)
        if total <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        if inst_buy / total > 0.5:
            inst.append((date, code))
    return sorted(inst)


def compute_all_size_bhar(bars: list) -> tuple[dict, dict]:
    """per code 一次扫，sliding window 20d_amt（O(1) per bar）+ date_idx BHAR（O(N) per code）。
    返回 (date_size, date_bhar)。
    BHAR 口径：trade_date 是 i，T+1 = i+1 open，T+2 = i+2 close，-3% intraday stop。
    """
    n = len(bars)
    amts = [b.get("amount", 0) or 0 for b in bars]
    opens = [b.get("open", 0) or 0 for b in bars]
    lows = [b.get("low", 0) or 0 for b in bars]
    closes = [b.get("close", 0) or 0 for b in bars]
    dates = [b.get("date", "") for b in bars]
    date_size: dict = {}
    date_bhar: dict = {}
    window_sum = 0.0
    window: list = []
    for i in range(n):
        a = amts[i]
        window.append(a)
        window_sum += a
        if len(window) > 20:
            window_sum -= window[0]
            window.pop(0)
        if len(window) >= 10:
            date_size[dates[i]] = window_sum / len(window)
        # BHAR: T+1 open → T+2 close -3% stop (i=trade_date, i+1=T+1, i+2=T+2)
        if i + 2 < n:
            t1_open = opens[i + 1]
            t1_low = lows[i + 1]
            t2_close = closes[i + 2]
            if t1_open > 0:
                stop_price = t1_open * (1 + STOP_PCT / 100)
                if t1_low <= stop_price:
                    date_bhar[dates[i]] = (stop_price / t1_open - 1) * 100
                elif t2_close > 0:
                    date_bhar[dates[i]] = (t2_close / t1_open - 1) * 100
    return date_size, date_bhar


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def audit_r12() -> None:
    picks = load_inst_dominant_picks()
    print(f"=== R12 size-matched BHAR（优化版 sliding window）===")
    print(f"inst_dominant picks: {len(picks)}\n")

    conn = sqlite3.connect(str(KLINE_DB))
    all_rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    print(f"全市场 codes: {len(all_rows)}")

    # date -> [(code, size, bhar)]
    date_market: dict = defaultdict(list)
    for idx, (code, bars_json) in enumerate(all_rows):
        try:
            bars = sorted(json.loads(bars_json), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        date_size, date_bhar = compute_all_size_bhar(bars)
        for d in date_size:
            if d in date_bhar:
                date_market[d].append((code, date_size[d], date_bhar[d]))
        if (idx + 1) % 1000 == 0:
            print(f"  scanned {idx + 1}/{len(all_rows)} codes, dates: {len(date_market)}")

    total_pairs = sum(len(v) for v in date_market.values())
    print(f"全市场 (date, code) 有 size+bhar: {total_pairs}")
    print(f"日期数: {len(date_market)}\n")

    # per-date 全市场分 10 decile + peers bhar by decile + 缓存 deciles
    date_decile_peers: dict = {}
    date_deciles: dict = {}
    for d, items in date_market.items():
        sizes = sorted(it[1] for it in items)
        n = len(sizes)
        if n < 10:
            continue
        deciles = [sizes[min(n - 1, n * i // 10)] for i in range(11)]
        date_deciles[d] = deciles
        peers_by_decile: list = [[] for _ in range(10)]
        for code, size, bhar in items:
            di = min(9, bisect.bisect_right(deciles, size) - 1)
            peers_by_decile[di].append((code, bhar))
        date_decile_peers[d] = peers_by_decile

    # inst picks 匹配
    date_code_idx: dict = {}
    for d, items in date_market.items():
        for code, size, bhar in items:
            date_code_idx[(d, code)] = (size, bhar)

    alphas_by_date: dict = defaultdict(list)
    all_alphas: list = []
    matched = 0
    for date, code in picks:
        if (date, code) not in date_code_idx:
            continue
        size, inst_bhar = date_code_idx[(date, code)]
        if date not in date_decile_peers:
            continue
        deciles = date_deciles[date]
        di = min(9, bisect.bisect_right(deciles, size) - 1)
        peers = date_decile_peers[date][di]
        peers_bhar = [b for c, b in peers if c != code]
        if not peers_bhar:
            continue
        peers_median = statistics.median(peers_bhar)
        alpha = inst_bhar - peers_median
        alphas_by_date[date].append(alpha)
        all_alphas.append(alpha)
        matched += 1

    print(f"matched picks: {matched}/{len(picks)}")
    if not all_alphas:
        print("无 alpha 数据")
        return

    day_means = [statistics.mean(rs) for rs in alphas_by_date.values() if rs]
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(all_alphas)
    wr = sum(1 for a in all_alphas if a > 0) / n * 100 if n else 0
    sr = sorted(all_alphas)
    median = sr[n // 2] if n else 0
    p = normal_p(t)
    verdict = "PASS" if p < ALPHA else "FAIL"
    print(f"\nR12 size-matched alpha (inst_bhar - peers_median, 同日同 decile):")
    print(f"  n={n} days={n_days} mean_alpha={mean:.4f}% median={median:.4f}% WR={wr:.1f}% day_t={t:.2f} p={p:.4f} {verdict}")
    print(f"\n  → {'size-matched edge-confirmed（alpha 非 size premium）' if p < ALPHA and mean > 0 else 'alpha 被 size premium 解释（非真 edge，或 underpowered）'}")
    print(f"  对比 inst_dominant raw BHAR +0.390%（如 alpha 显著正→真 edge 非 size）")


if __name__ == "__main__":
    audit_r12()
