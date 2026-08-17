#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S066 screener edge 补全验证——让数据决定 grill Q1（a 收益预测器 / b 质量筛 / c 功效不足）。

factor_regression（39ec2d7）已证 within-day r(total_score, 次日收益)≈0——但只验了"次日收益"口径。
本脚本补全：
- (b) 连板概率：high total_score → 更高 P(次日涨停)？若是 → screener 是质量筛（next-day-return r≈0
  是错口径），照常用；若否 → 无连板 edge。
- (c) 功效：within-day r 的 Fisher CI 半宽 = 可检测效应下界；半宽窄 → r≈0 是真 null 非功效不足。
- (a) 复确认 within-day r(total_score, return_close2close) + r(total_score, next_pctChg)。

口径：eastmoney_live 段（§5.3）。连板 = next_pctChg ≥ 9.8（主板 10% 限近似；创业/科创 20% 亦命中，
ST 5% 漏——近似，标注）。合规（§1.2）：全实测、不臆造。

用法：cd backend && ../.venv/bin/python tools/screener_edge_validation.py
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES_PATH = ROOT / ".vibe-research" / "backtest_samples.json"
DB_PATH = ROOT / ".vibe-research" / "gene_scores.db"
OUT_PATH = ROOT / ".vibe-research" / "screener_edge_validation.json"
ZT_NEXT_THRESHOLD = 9.8  # 主板涨停 10% 限近似（创业/科创 20% 亦命中，ST 5% 漏）


def load_src_map() -> dict[tuple[str, str], str]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        return {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT date, code, data_source FROM gene_scores"
        ).fetchall()}
    finally:
        conn.close()


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def fisher_ci(r: float, n: int, zcrit: float = 1.96) -> tuple[float, float, float]:
    """Pearson r 的 Fisher z 95% CI。返 (lo, hi, half_width≈可检测 r 下界)。"""
    if n < 4 or abs(r) >= 0.999:
        return 0.0, 0.0, 0.0
    zr = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    lo_z, hi_z = zr - zcrit * se, zr + zcrit * se
    return math.tanh(lo_z), math.tanh(hi_z), zcrit * se  # half_width 用 z 尺度近似 r


def wilson(wins: int, n: int, zcrit: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + zcrit * zcrit / n
    c = (p + zcrit * zcrit / (2 * n)) / d
    h = zcrit * ((p * (1 - p) / n + zcrit * zcrit / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def within_day_r(samples: list[dict], y_field: str) -> dict:
    """日内（去 date 均值）横截面 r(total_score, y_field) + Fisher CI + 可检测 r。"""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        if s.get("total_score") is None or s.get(y_field) is None:
            continue
        by_date[s["date"]].append(s)
    resid_x: list[float] = []
    resid_y: list[float] = []
    for d, ss in by_date.items():
        if len(ss) < 3:
            continue
        mx = sum(s["total_score"] for s in ss) / len(ss)
        my = sum(s[y_field] for s in ss) / len(ss)
        resid_x.extend(s["total_score"] - mx for s in ss)
        resid_y.extend(s[y_field] - my for s in ss)
    r = pearson(resid_x, resid_y)
    lo, hi, hw = fisher_ci(r, len(resid_x))
    return {"within_day_r": round(r, 4), "n": len(resid_x),
            "ci": [round(lo, 4), round(hi, 4)], "detectable_r_floor": round(hw, 4)}


def main() -> int:
    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    src_map = load_src_map()
    samples = []
    for s in data.get("samples", []):
        if src_map.get((s.get("date"), s.get("code"))) != "eastmoney_live":
            continue
        if s.get("total_score") is None or s.get("next_pctChg") is None:
            continue
        samples.append(s)
    print(f"eastmoney_live + 有 total_score + next_pctChg: {len(samples)} 样本")
    if not samples:
        return 1

    # (b) 连板概率 per total_score 五分位
    scores = sorted(samples, key=lambda s: s["total_score"])
    q = max(1, len(scores) // 5)
    quintiles = []
    for i in range(5):
        chunk = scores[i * q: (i + 1) * q] if i < 4 else scores[i * q:]
        n = len(chunk)
        zt = sum(1 for s in chunk if s.get("next_pctChg", 0) >= ZT_NEXT_THRESHOLD)
        lo, hi = wilson(zt, n)
        quintiles.append({
            "quintile": f"Q{i+1}", "score_range": [
                chunk[0]["total_score"] if chunk else None,
                chunk[-1]["total_score"] if chunk else None,
            ],
            "n": n, "zt_next": zt, "p_zt": round(zt / n, 4) if n else None,
            "p_zt_ci": [round(lo, 4), round(hi, 4)] if n else None,
        })
    # 连板单调：Q5(高分) P(zt) > Q1(低分)?
    q1p = quintiles[0]["p_zt"] or 0
    q5p = quintiles[4]["p_zt"] or 0
    lianban_monotonic = q5p > q1p

    # (a)/(c) within-day r
    r_ret = within_day_r(samples, "return_close2close")
    r_pct = within_day_r(samples, "next_pctChg")

    # verdict
    ret_null = r_ret["ci"][0] <= 0 <= r_ret["ci"][1]  # CI 含 0
    pct_null = r_pct["ci"][0] <= 0 <= r_pct["ci"][1]
    powered = r_ret["detectable_r_floor"] < 0.05  # 能检测 r<0.05 → 非功效不足
    # 连板显著性：Q5(高分) CI 下界 > Q1(低分) CI 上界 → 不重叠 → 显著
    q1ci = quintiles[0]["p_zt_ci"] or [0.0, 0.0]
    q5ci = quintiles[4]["p_zt_ci"] or [0.0, 0.0]
    lianban_sig = lianban_monotonic and (q5ci[0] > q1ci[1])

    if lianban_sig:
        verdict = ("连板概率 Q5>Q1 显著 → total_score 预测连板 → screener 是质量筛(b)，"
                   "next-day-return r≈0 是错口径，照常用；不 pivot 选股基础。")
    elif not powered:
        verdict = (f"功效不足(c)：within-day 可检测 r 下界={r_ret['detectable_r_floor']}（>0.05），"
                   "r≈0 可能是测不出小效应而非真无——需更多天数。")
    elif ret_null and pct_null:
        verdict = ("total_score 既不预测次日收益(a) 也不预测次日涨跌幅/连板 —— 选股无验证 edge；"
                   "top-N-by-total_score 当前无 edge，该诚实标注（标未 validated，不阻断接入跑通）+ 等 60 天复验或 pivot 选股基础。"
                   "60日复验窗口：破2x→validated 升级权重，<2x→保留接入标注复验未破2x。")
    else:
        verdict = "部分信号，见下表。"

    out = {
        "generated_at": datetime.now().isoformat(),
        "n_eastmoney_live": len(samples),
        "zt_threshold": ZT_NEXT_THRESHOLD,
        "quintile_lianban": quintiles,
        "lianban_q5_gt_q1": lianban_monotonic, "lianban_significant": lianban_sig,
        "within_day_r_return_close2close": r_ret,
        "within_day_r_next_pctChg": r_pct,
        "verdict": verdict,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n连板概率（next_pctChg>={ZT_NEXT_THRESHOLD}）per total_score 五分位:")
    print(f"{'quintile':<5}{'score':>12}{'n':>6}{'p_zt':>8}{'95%CI':>20}")
    for qd in quintiles:
        ci = f"[{qd['p_zt_ci'][0]},{qd['p_zt_ci'][1]}]" if qd["p_zt_ci"] else "—"
        print(f"{qd['quintile']:<5}{str(qd['score_range']):>12}{qd['n']:>6}"
              f"{str(qd['p_zt']):>8}{ci:>20}")
    print(f"\nwithin-day r(total_score, return_close2close) = {r_ret['within_day_r']} "
          f"CI {r_ret['ci']} (n={r_ret['n']}, 可检测 r≥{r_ret['detectable_r_floor']})")
    print(f"within-day r(total_score, next_pctChg)        = {r_pct['within_day_r']} "
          f"CI {r_pct['ci']} (可检测 r≥{r_pct['detectable_r_floor']})")
    print(f"\n连板 Q5>Q1={lianban_monotonic} 显著={lianban_sig}")
    print(f"verdict: {verdict}")
    print(f"输出: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
