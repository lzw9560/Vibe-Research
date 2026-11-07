# -*- coding: utf-8 -*-
"""前兆预测 first-cut 测试（2026-10-20）。

区别于项目已证伪的"打板延续"（买已涨停赌次日延续），本测"预测"：
今日前兆（强势未涨停 + 量比）能否预测明日涨停/大涨。

前兆 = 今日 pct ∈ [+5%, +7%]（强势但未到涨停）AND 量比 ≥ 2（vol / MA20 vol）。
结果 = 明日 pct 是否 ≥ 涨停阈值（10%板 +9.8% / 20%板 +19.8%）+ 明日 mean return。
对比 base rate（全 stock-days）vs conditional rate（前兆子集）→ lift。

caveat：first-cut，单一前兆组合，无多重检验校正/walk-forward/日聚类（§44 后续）。
关联：memory edge-exhaustive-5batch（证伪延续非预测）/ inst-dominant-edge-falsified（cache 干净后）
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"


def limit_pct(code: str) -> float:
    """涨停 pct 阈值 by board（封板 = close 接近涨停价）。"""
    if code.startswith(("688", "300", "301")):
        return 0.198  # 科创/创业 20%
    if code.startswith(("8", "920", "43")):
        return 0.298  # 北交所 30%（少，略）
    return 0.098  # 沪深主板 10%


def main() -> None:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    print(f"=== 前兆预测 first-cut（{len(rows)} stocks, 8 年干净 cache）===")
    print("前兆 = 今日 pct ∈ [+5%, +7%] AND 量比 ≥ 2\n")

    base_n = 0
    base_limitup = 0
    base_rets: list = []
    prec_n = 0
    prec_limitup = 0
    prec_rets: list = []
    # 额外前兆变体：今日涨停（对照打板延续）+ 今日 +3~+5%（温和强势）
    by_prec: dict = defaultdict(lambda: {"n": 0, "lim": 0, "rets": []})  # type: ignore

    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 25:
            continue
        vols = [float(b.get("volume", 0) or 0) for b in bars]
        lim = limit_pct(code)
        for i in range(1, len(bars) - 1):  # 需 prev + next
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            close = float(bars[i].get("close", 0) or 0)
            if not prev_c or not close:
                continue
            pct = (close - prev_c) / prev_c
            ma20 = statistics.mean(vols[max(0, i - 20):i]) if i >= 1 else 0
            vol_ratio = (vols[i] / ma20) if ma20 else 0
            # next-day
            nxt_c = float(bars[i + 1].get("close", 0) or 0)
            if not nxt_c:
                continue
            nxt_pct = (nxt_c - close) / close
            nxt_limitup = nxt_pct >= lim

            base_n += 1
            base_rets.append(nxt_pct)
            if nxt_limitup:
                base_limitup += 1

            # 前兆 A: +5~+7% + 量比≥2（主力建仓未封板）
            if 0.05 <= pct <= 0.07 and vol_ratio >= 2:
                prec_n += 1
                prec_rets.append(nxt_pct)
                if nxt_limitup:
                    prec_limitup += 1
            # 对照 B: 今日涨停（+9.8%+）= 打板延续测
            if pct >= lim:
                by_prec["B_涨停"]["n"] += 1
                by_prec["B_涨停"]["rets"].append(nxt_pct)
                if nxt_limitup:
                    by_prec["B_涨停"]["lim"] += 1
            # 对照 C: 今日 +3~+5%（温和强势）
            if 0.03 <= pct < 0.05:
                by_prec["C_+3~5%"]["n"] += 1
                by_prec["C_+3~5%"]["rets"].append(nxt_pct)
                if nxt_pct >= lim:
                    by_prec["C_+3~5%"]["lim"] += 1

    base_rate = base_limitup / base_n if base_n else 0
    base_mean = statistics.mean(base_rets) if base_rets else 0
    print(f"{'前兆':<14}{'n':>10}{'次日涨停率':>12}{'lift':>7}{'次日mean':>11}")
    print("-" * 56)
    print(f"{'base(全样本)':<14}{base_n:>10}{base_rate*100:>10.3f}%{1.00:>7.2f}x{base_mean*100:>+9.3f}%")

    def show(label, n, lim_c, rets):
        if not n:
            return
        r = lim_c / n
        m = statistics.mean(rets) if rets else 0
        lift = r / base_rate if base_rate else 0
        print(f"{label:<14}{n:>10}{r*100:>10.3f}%{lift:>6.2f}x{m*100:>+9.3f}%")

    show("A_+5~7%+量≥2x", prec_n, prec_limitup, prec_rets)
    for k in ("B_涨停", "C_+3~5%"):
        d = by_prec[k]
        show(k, d["n"], d["lim"], d["rets"])

    print()
    print("读法：lift>1 = 前兆有预测力；lift≈1 = 无；mean = 次日平均收益（正=买入赚钱）")
    print("caveat：first-cut 单一前兆，无多重检验/walk-forward/日聚类（§44 后续）")


if __name__ == "__main__":
    main()
