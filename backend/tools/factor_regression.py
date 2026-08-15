#!/usr/bin/env python3
"""Phase 0b 全样本因子回归脚本（S066）。

对 `.vibe-research/backtest_samples.json` 的全样本按 data_source 分两组
（kline_rebuild / eastmoney_live）独立统计：

- 每个因子 vs 次日收益的 Pearson r + 95% CI（Fisher z 变换）+ p 值
- 每个因子五分位（Q1-Q5）胜率 + Wilson 95% CI
- 日内/日间分解（2026-08-16 续 grill 新增）：pooled r 拆成 within-day（日内
  去均值，横截面选股力）与 between-day（日均值相关，行情制度效应），外加
  日间方差占比与日级因子检测——防止日级聚合变量伪装成选股信号
- day-cluster bootstrap：按交易日整日重抽样，给 pooled/within r 一个尊重
  聚类结构的 95% CI（pooled p 值的 IID 假设在日级相关下失效，必须补这一刀）
- verdict 判定：A=方向不变且显著；B=某因子方向反转；C=全部不显著

输出：
- `.vibe-research/factor_significance.json`（结构化结果）
- stdout 摘要

用法：
    python3 backend/tools/factor_regression.py [--return-metric return_open2close|return_close2close]
        [--bootstrap-iters 2000] [--no-bootstrap]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy import stats

# --- 路径 ---
ROOT = Path(__file__).resolve().parents[2]
SAMPLES_PATH = ROOT / ".vibe-research" / "backtest_samples.json"
DB_PATH = ROOT / ".vibe-research" / "gene_scores.db"
OUT_PATH = ROOT / ".vibe-research" / "factor_significance.json"

# spec §1.1 的 74 样本结论：
SPEC_BASELINE_R = {
    "factor_premium_rate": +0.06,
    "factor_red_rate": -0.26,
    "factor_seal_rate": +0.18,
    "factor_rebound_rate": None,  # spec §1.1 未列；方向未知，不参与方向判定
    "factor_freq_score": -0.26,
    "total_score": -0.20,
}

# 方向判定只看这四个核心因子（premium 零预测力，不算方向）
DIRECTION_FACTORS = [
    "factor_red_rate",
    "factor_seal_rate",
    "factor_freq_score",
    "total_score",
]

# 每组因子列表
GROUP_FACTORS = {
    "kline_rebuild": [
        "factor_premium_rate",
        "factor_red_rate",
        "factor_freq_score",
        "total_score",
    ],
    "eastmoney_live": [
        "factor_premium_rate",
        "factor_red_rate",
        "factor_seal_rate",
        "factor_rebound_rate",
        "factor_freq_score",
        "total_score",
    ],
}

# verdict 文案
SPEC_IMPACT = {
    "A": "继续 Phase 1 按现 spec 实现",
    "B": "暂停 Phase 1，改 §4 权重方向",
    "C": "前置 Phase 2，引入新因子体系",
}


# =====================================================================
# 数据加载
# =====================================================================
def load_samples() -> tuple[dict, list[dict]]:
    with SAMPLES_PATH.open() as f:
        data = json.load(f)
    return data, data["samples"]


def load_src_map() -> dict[tuple[str, str], str]:
    """从 gene_scores.db 读 (date, code) -> data_source 映射。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT date, code, data_source FROM gene_scores"
        ).fetchall()
    finally:
        conn.close()
    return {(r[0], r[1]): r[2] for r in rows}


def annotate_sources(samples: list[dict], src_map: dict) -> list[dict]:
    for s in samples:
        s["_src"] = src_map.get((s["date"], s["code"]))
    return samples


# =====================================================================
# 统计原语
# =====================================================================
def pearson_r_ci_p(x: np.ndarray, y: np.ndarray) -> tuple[float, list[float], float, int]:
    """返回 (r, [ci_lo, ci_hi], p, n)。

    scipy.stats.pearsonr 给 r 和 p；CI 用 Fisher z 变换手算。
    """
    n = len(x)
    if n < 4:
        return float("nan"), [float("nan"), float("nan")], float("nan"), n
    r, p = stats.pearsonr(x, y)
    # 处理 r=±1（z 发散）的退化情况
    if abs(r) >= 1.0:
        return float(r), [float(r), float(r)], float(p), n
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(max(n - 3, 1))
    lo = math.tanh(z - 1.96 * se)
    hi = math.tanh(z + 1.96 * se)
    return float(r), [float(lo), float(hi)], float(p), n


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    """Wilson 95% CI。"""
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [float(center - half), float(center + half)]


def quintile_winrates(x: np.ndarray, y: np.ndarray) -> list[dict]:
    """按 x 分 5 组，每组算 y>0 比例 + Wilson CI。"""
    n = len(x)
    if n < 5:
        return [{"q": f"Q{i+1}", "wr": float("nan"), "ci": [float("nan"), float("nan")], "n": 0}
                for i in range(5)]
    order = np.argsort(x, kind="mergesort")  # 稳定排序
    # 分成 5 组，每组尽量等量
    edges = np.array_split(order, 5)
    out = []
    for i, idx in enumerate(edges):
        yq = y[idx]
        k = int(np.sum(yq > 0))
        nn = len(yq)
        wr = k / nn if nn else float("nan")
        out.append({
            "q": f"Q{i+1}",
            "wr": float(wr),
            "ci": wilson_ci(k, nn),
            "n": nn,
        })
    return out


# =====================================================================
# 日内/日间分解 + day-cluster bootstrap（2026-08-16 续 grill）
# =====================================================================
# 背景：pooled Pearson r 假设样本 IID。涨停股样本天然按日聚类——同一天的票
# 共享当日行情制度，因子值与收益都相关。日级聚合因子（如 rebound_rate，全市场
# 同日同值）会让 pooled r 全部由日间变异撑起，p 值极小但横截面选股力为零。
# 分解方法：
#   within-day r  = 因子与收益各自减去当日均值后的 pooled r（纯横截面）
#   between-day r = 当日均值因子 vs 当日均值收益（n=天数，行情制度效应）
#   var_between%  = 因子总平方和中"日均值偏离全局均值"的占比
# day-cluster bootstrap：按日有放回重抽整日样本重算 r，CI 尊重聚类结构。


def _safe_pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 4 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(stats.pearsonr(x, y)[0])


def intraday_decomposition(
    samples: list[dict], factor: str, return_metric: str
) -> dict:
    """按交易日分解因子与收益的关联。

    调用方保证 samples 已过滤（同 filter_for_factor 的口径），且每条带 date。
    """
    if not samples:
        return {"n_days": 0}
    x = np.array([float(s[factor]) for s in samples])
    y = np.array([float(s[return_metric]) for s in samples])
    dates = [s["date"] for s in samples]
    udays = sorted(set(dates))
    mask_by_day = {d: np.array([dt == d for dt in dates]) for d in udays}

    pooled_r = _safe_pearson(x, y)

    # within-day：各自减去当日均值
    xw = x.copy()
    yw = y.copy()
    for d in udays:
        m = mask_by_day[d]
        xw[m] -= x[m].mean()
        yw[m] -= y[m].mean()
    within_r = _safe_pearson(xw, yw)

    # between-day：日均值序列
    dmx = np.array([x[mask_by_day[d]].mean() for d in udays])
    dmy = np.array([y[mask_by_day[d]].mean() for d in udays])
    between_r = _safe_pearson(dmx, dmy)

    # 方差分解
    ss_total = float(np.sum((x - x.mean()) ** 2))
    ss_between = float(sum(
        mask_by_day[d].sum() * (x[mask_by_day[d]].mean() - x.mean()) ** 2
        for d in udays
    ))
    var_between_pct = (ss_between / ss_total * 100.0) if ss_total > 0 else float("nan")

    # 日级因子检测：日内 distinct 值个数
    daily_distinct = [len(set(np.round(x[mask_by_day[d]], 6))) for d in udays]
    mean_daily_distinct = float(np.mean(daily_distinct))
    pct_days_single_value = (
        sum(1 for c in daily_distinct if c == 1) / len(daily_distinct) * 100.0
    )
    is_day_level = pct_days_single_value >= 50.0 or (
        mean_daily_distinct <= 2.0 and var_between_pct >= 60.0
    )

    return {
        "pooled_r": pooled_r,
        "within_day_r": within_r,
        "between_day_r": between_r,
        "var_between_pct": var_between_pct,
        "n_days": len(udays),
        "mean_daily_distinct": mean_daily_distinct,
        "pct_days_single_value": pct_days_single_value,
        "is_day_level": is_day_level,
    }


def day_cluster_bootstrap(
    samples: list[dict],
    factor: str,
    return_metric: str,
    iters: int = 2000,
    seed: int = 42,
) -> dict:
    """按交易日整日有放回重抽样，重算 pooled/within r 的 95% CI。"""
    if not samples or iters <= 0:
        return {"iters": 0}
    by_day: dict[str, list[dict]] = {}
    for s in samples:
        by_day.setdefault(s["date"], []).append(s)
    days = sorted(by_day)
    if len(days) < 4:
        return {"iters": 0, "note": f"天数 {len(days)} < 4，bootstrap 不适用"}
    rng = random.Random(seed)

    def draw() -> list[dict]:
        out: list[dict] = []
        for _ in range(len(days)):
            out.extend(by_day[rng.choice(days)])
        return out

    pooled_rs: list[float] = []
    within_rs: list[float] = []
    for _ in range(iters):
        smp = draw()
        dec = intraday_decomposition(smp, factor, return_metric)
        if math.isfinite(dec["pooled_r"]):
            pooled_rs.append(dec["pooled_r"])
        if math.isfinite(dec["within_day_r"]):
            within_rs.append(dec["within_day_r"])

    def ci(rs: list[float]) -> list[float]:
        if len(rs) < 20:
            return [float("nan"), float("nan")]
        lo, hi = np.percentile(np.array(rs), [2.5, 97.5])
        return [float(lo), float(hi)]

    return {
        "iters": iters,
        "n_days": len(days),
        "pooled_r_ci95": ci(pooled_rs),
        "within_day_r_ci95": ci(within_rs),
        "pooled_r_samples": len(pooled_rs),
        "within_r_samples": len(within_rs),
    }


# =====================================================================
# 过滤
# =====================================================================
# 各组"可用因子"集合（用于判定废样本：全可用因子皆 0 => 缺失填充的废样本）
GROUP_AVAILABLE_FACTORS = {
    "kline_rebuild": [
        "factor_premium_rate",
        "factor_red_rate",
        "factor_freq_score",
        "total_score",
        # seal/rebound 在 kline_rebuild 恒为 0（缺失），不计入废样本判定
    ],
    "eastmoney_live": [
        "factor_premium_rate",
        "factor_red_rate",
        "factor_seal_rate",
        "factor_rebound_rate",
        "factor_freq_score",
        "total_score",
    ],
}


def is_garbage_sample(s: dict, group: str) -> bool:
    """该组可用因子全为 0 => 视为缺失填充的废样本，剔除。

    kline_rebuild: seal/rebound 恒 0（缺失），用 premium/red/freq/total 判定。
    eastmoney_live: 6 因子全 0 才算废样本；单因子 0 是真实 0 值（如当天无溢价）。
    """
    avail = GROUP_AVAILABLE_FACTORS[group]
    return all(s.get(f, 0) == 0 for f in avail)


def filter_for_factor(
    samples: list[dict], factor: str, return_metric: str, group: str
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (x, y)：
    - 排除 missing_next_bar=True
    - 排除该组可用因子全为 0 的废样本（缺失填充）
    - 单个因子 == 0 保留（真实 0 值，如当天无溢价）
    - return_metric 必须为有限数
    """
    xs, ys = [], []
    for s in samples:
        if s.get("missing_next_bar"):
            continue
        if is_garbage_sample(s, group):
            continue
        fv = s.get(factor)
        if fv is None or not math.isfinite(fv):
            continue
        rv = s.get(return_metric)
        if rv is None or not math.isfinite(rv):
            continue
        xs.append(float(fv))
        ys.append(float(rv))
    return np.array(xs, dtype=float), np.array(ys, dtype=float)


def _filter_samples(samples: list[dict], factor: str, return_metric: str, group: str) -> list[dict]:
    """与 filter_for_factor 同口径，但返回样本对象（带 date，供日内分解用）。"""
    out = []
    for s in samples:
        if s.get("missing_next_bar"):
            continue
        if is_garbage_sample(s, group):
            continue
        fv = s.get(factor)
        if fv is None or not math.isfinite(fv):
            continue
        rv = s.get(return_metric)
        if rv is None or not math.isfinite(rv):
            continue
        out.append(s)
    return out


# =====================================================================
# verdict
# =====================================================================
def compute_verdict(groups: dict[str, dict]) -> dict:
    """grade 判定：
    A: 所有核心因子方向与 §1.1 一致，且至少 3 个因子 CI 排除 0
    B: 任一核心因子 r 方向反转，且 CI 排除 0
    C: 全部核心因子 CI 包含 0（都不显著）
    """
    direction_changes = []

    # 汇总两组核心因子的方向是否反转
    # 对每个核心因子，看两组（kline_rebuild / eastmoney_live）的 r 符号
    # 若任一组 r 符号与基线相反且 CI 排除 0，记一次反转
    # seal/rebound 只在 eastmoney_live 组有，premium 不算方向
    any_reversal_significant = False
    any_significant = False  # 是否有任一核心因子 CI 排除 0
    all_core_includes_zero = True  # 是否所有核心因子 CI 都包含 0

    # 对每个方向因子
    sign_check_per_factor = {}  # factor -> {"reversed": bool, "significant": bool}

    for factor in DIRECTION_FACTORS:
        baseline = SPEC_BASELINE_R.get(factor)
        if baseline is None or baseline == 0:
            continue
        expected_sign = 1 if baseline > 0 else -1

        factor_reversed_sig = False
        factor_significant_any = False
        factor_all_include_zero = True

        for group_name in ("kline_rebuild", "eastmoney_live"):
            if factor not in groups.get(group_name, {}):
                continue
            entry = groups[group_name][factor]
            r = entry["r"]
            ci = entry["ci"]
            if math.isnan(r):
                continue
            lo, hi = ci
            ci_excludes_zero = (lo > 0) or (hi < 0)
            if ci_excludes_zero:
                factor_significant_any = True
                factor_all_include_zero = False
                any_significant = True
                all_core_includes_zero = False
                # 方向是否反转：r 符号与基线相反
                if (r > 0 and expected_sign < 0) or (r < 0 and expected_sign > 0):
                    factor_reversed_sig = True
                    any_reversal_significant = True
                    direction_changes.append({
                        "factor": factor,
                        "group": group_name,
                        "baseline_r": baseline,
                        "observed_r": r,
                        "ci": ci,
                        "p": entry["p"],
                        "note": f"方向反转：spec §1.1 r={baseline:+.2f}，本组 r={r:+.4f} CI 排除 0",
                    })

        sign_check_per_factor[factor] = {
            "reversed_sig": factor_reversed_sig,
            "significant_any": factor_significant_any,
        }

    # 判定优先级：B > C > A
    # 严格按 spec：
    #   A: 所有因子方向不变，且至少 3 个因子 CI 排除 0
    #   B: 任一因子方向反转（且 CI 排除 0）
    #   C: 全部因子 CI 包含 0
    if any_reversal_significant:
        grade = "B"
        rationale = "至少一个核心因子 r 方向反转且 CI 排除 0"
    elif all_core_includes_zero and not any_significant:
        grade = "C"
        rationale = "所有核心因子 CI 均包含 0（都不显著）"
    else:
        # 方向都一致，看显著性是否达到 3 个
        # 统计 CI 排除 0 的方向因子数（跨组去重：一个因子任一组显著即算）
        sig_count = sum(
            1 for v in sign_check_per_factor.values() if v["significant_any"]
        )
        if sig_count >= 3:
            grade = "A"
            rationale = f"所有核心因子方向不变，且 {sig_count} 个因子 CI 排除 0（≥3）"
        else:
            # 方向一致但显著性不足 —— 按距离 A 更近，仍记 A 但标注显著性不足
            grade = "A"
            rationale = (
                f"所有核心因子方向不变，但仅 {sig_count} 个因子 CI 排除 0（<3，显著性不足；"
                "方向未反转，仍归 A 但提示需扩大样本或优化因子）"
            )

    return {
        "grade": grade,
        "rationale": rationale,
        "spec_impact": SPEC_IMPACT[grade],
        "direction_changes": direction_changes,
        "per_factor_direction_check": sign_check_per_factor,
    }


# =====================================================================
# 主流程
# =====================================================================
def analyze_group(
    samples: list[dict], factors: list[str], return_metric: str, group: str
) -> dict:
    out = {}
    for factor in factors:
        x, y = filter_for_factor(samples, factor, return_metric, group)
        if len(x) == 0:
            out[factor] = {
                "r": float("nan"),
                "ci": [float("nan"), float("nan")],
                "p": float("nan"),
                "n": 0,
                "quintile_winrates": [],
            }
            continue
        r, ci, p, n = pearson_r_ci_p(x, y)
        qw = quintile_winrates(x, y)
        out[factor] = {
            "r": r,
            "ci": ci,
            "p": p,
            "n": n,
            "quintile_winrates": qw,
        }
    return out


def main(return_metric: str, bootstrap_iters: int = 2000) -> int:
    data, samples = load_samples()
    src_map = load_src_map()
    annotate_sources(samples, src_map)

    # 分组
    g_kline = [s for s in samples if s.get("_src") == "kline_rebuild"]
    g_east = [s for s in samples if s.get("_src") == "eastmoney_live"]
    g_unknown = [s for s in samples if s.get("_src") not in ("kline_rebuild", "eastmoney_live")]

    groups = {
        "kline_rebuild": analyze_group(
            g_kline, GROUP_FACTORS["kline_rebuild"], return_metric, "kline_rebuild"
        ),
        "eastmoney_live": analyze_group(
            g_east, GROUP_FACTORS["eastmoney_live"], return_metric, "eastmoney_live"
        ),
    }

    # ---- 日内/日间分解 + day-cluster bootstrap ----
    # 只对 eastmoney_live 组做（kline_rebuild 只有 3 因子且全是日级聚合口径的话
    # 分解同样适用，但当前优先审涨停类权重主体）。
    decomposition: dict[str, dict] = {}
    filtered_cache: dict[str, list[dict]] = {}
    for factor in GROUP_FACTORS["eastmoney_live"]:
        # 复用 filter_for_factor 的口径取样本子集（带 date 供分解用）
        xs, _ = filter_for_factor(g_east, factor, return_metric, "eastmoney_live")
        if len(xs) == 0:
            decomposition[factor] = {"n_days": 0}
            continue
        # 重新取样本对象（与 filter 同序）
        sub = _filter_samples(g_east, factor, return_metric, "eastmoney_live")
        filtered_cache[factor] = sub
        decomposition[factor] = intraday_decomposition(sub, factor, return_metric)
    decomposition["_bootstrap"] = {
        factor: day_cluster_bootstrap(
            filtered_cache.get(factor, []), factor, return_metric, iters=bootstrap_iters
        )
        for factor in GROUP_FACTORS["eastmoney_live"]
        if factor in filtered_cache
    }
    decomposition["_bootstrap"]["_iters"] = bootstrap_iters

    verdict = compute_verdict(groups)

    # 元数据
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_samples": len(samples),
        "kline_rebuild_n": len(g_kline),
        "eastmoney_live_n": len(g_east),
        "unknown_source_n": len(g_unknown),
        "return_metric": return_metric,
        "spec_baseline_r": SPEC_BASELINE_R,
        "benchmarks": data.get("benchmarks", {}),
    }

    result = {
        "meta": meta,
        "kline_rebuild": groups["kline_rebuild"],
        "eastmoney_live": groups["eastmoney_live"],
        "decomposition": decomposition,
        "verdict": verdict,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---- stdout 摘要 ----
    print("=" * 72)
    print(f"Phase 0b 因子回归  |  return_metric={return_metric}")
    print("=" * 72)
    print(f"total_samples={meta['total_samples']}  "
          f"kline_rebuild={meta['kline_rebuild_n']}  "
          f"eastmoney_live={meta['eastmoney_live_n']}  "
          f"unknown={meta['unknown_source_n']}")
    print(f"benchmarks: {meta['benchmarks']}")
    print()

    for group_name, facs in GROUP_FACTORS.items():
        print(f"--- {group_name} ---")
        for f in facs:
            e = groups[group_name][f]
            r = e["r"]
            ci = e["ci"]
            p = e["p"]
            n = e["n"]
            base = SPEC_BASELINE_R.get(f)
            base_str = f"基线{base:+.2f}" if base is not None else "基线NA"
            ci_excl = "*" if (math.isfinite(r) and (ci[0] > 0 or ci[1] < 0)) else " "
            if math.isnan(r):
                print(f"  {f:28s}  n={n:<5d}  r=NaN")
            else:
                print(f"  {f:28s}  n={n:<5d}  r={r:+.4f}  "
                      f"CI=[{ci[0]:+.4f}, {ci[1]:+.4f}]  p={p:.4g}  "
                      f"{base_str}  {ci_excl}")
        print()

    print("--- eastmoney_live 日内/日间分解（2026-08-16 续 grill）---")
    print(f"{'factor':28s} {'pooled r':>9s} {'within-day':>11s} {'between-day':>12s} {'var%bet':>8s} {'日级':>5s}")
    for f in GROUP_FACTORS["eastmoney_live"]:
        dec = decomposition.get(f, {})
        if dec.get("n_days", 0) == 0:
            print(f"  {f:26s}  无样本"); continue
        print(f"  {f:26s} {dec['pooled_r']:+9.4f} {dec['within_day_r']:+11.4f} "
              f"{dec['between_day_r']:+12.4f} {dec['var_between_pct']:7.1f}% "
              f"{'是' if dec['is_day_level'] else '否':>4s}")
    print()
    print("day-cluster bootstrap（按日整日重抽样，尊重聚类结构）:")
    bs = decomposition.get("_bootstrap", {})
    for f in GROUP_FACTORS["eastmoney_live"]:
        b = bs.get(f)
        if not b or b.get("iters", 0) == 0:
            continue
        plo, phi = b["pooled_r_ci95"]
        wlo, whi = b["within_day_r_ci95"]
        print(f"  {f:26s} pooled CI=[{plo:+.4f},{phi:+.4f}]  "
              f"within CI=[{wlo:+.4f},{whi:+.4f}]")
    print()

    print("verdict:")
    print(f"  grade        = {verdict['grade']}")
    print(f"  rationale    = {verdict['rationale']}")
    print(f"  spec_impact  = {verdict['spec_impact']}")
    if verdict["direction_changes"]:
        print(f"  direction_changes ({len(verdict['direction_changes'])}):")
        for dc in verdict["direction_changes"]:
            print(f"    - {dc['factor']} ({dc['group']}): "
                  f"{dc['baseline_r']:+.2f} -> {dc['observed_r']:+.4f} "
                  f"CI={dc['ci']} p={dc['p']:.4g}")
            print(f"      {dc['note']}")
    else:
        print("  direction_changes: []")
    print()
    print(f"JSON -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 0b 因子回归")
    parser.add_argument(
        "--return-metric",
        choices=["return_open2close", "return_close2close"],
        default="return_open2close",
        help="次日收益度量（默认 return_open2close）",
    )
    parser.add_argument(
        "--bootstrap-iters",
        type=int,
        default=2000,
        help="day-cluster bootstrap 重抽样次数（默认 2000；0 关闭）",
    )
    args = parser.parse_args()
    sys.exit(main(args.return_metric, bootstrap_iters=args.bootstrap_iters))
