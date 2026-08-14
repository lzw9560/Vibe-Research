# -*- coding: utf-8 -*-
"""S066 Phase 0b: 全样本因子回归 → factor_significance.json

加载 backtest_samples.json，对 5 因子 + zt_count + total_score 计算：
- Pearson r + 95% CI + p 值（Fisher z 变换）
- 五分位胜率（全样本）
- 因子相关矩阵 + PCA（numpy 实现，不依赖 sklearn）
- alpha 来源假设 A/B/C/D 验证（§14.1）
- Bonferroni 校正

输出：.vibe-research/factor_significance.json

纯统计计算，无网络、无 em_get。
诚实：n 不足的因子标注"样本不足"；CI 包含 0 的标注"不显著"。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
SAMPLES_PATH = REPO / ".vibe-research" / "backtest_samples.json"
OUT = REPO / ".vibe-research" / "factor_significance.json"

FACTORS = [
    "factor_premium_rate",
    "factor_red_rate",
    "factor_seal_rate",
    "factor_rebound_rate",
    "factor_freq_score",
    "zt_count_250d",
    "total_score",
    "wilson_adjusted",
]
BENCHMARK_BASE = 50.0  # 50% = 随机，用 benchmark_A 代替会更准


def load_samples() -> tuple[list[dict], dict]:
    data = json.loads(SAMPLES_PATH.read_text())
    return data["samples"], data.get("benchmarks", {})


def pearson_with_ci(x: list[float], y: list[float]) -> dict:
    """Pearson r + 95% CI（Fisher z 变换）+ 大样本 t 检验 p 值。"""
    n = len(x)
    if n < 3:
        return {"r": None, "ci_low": None, "ci_high": None, "p": None, "n": n}
    arr_x = np.array(x, dtype=float)
    arr_y = np.array(y, dtype=float)
    mx, my = arr_x.mean(), arr_y.mean()
    sx, sy = arr_x.std(ddof=1), arr_y.std(ddof=1)
    if sx == 0 or sy == 0:
        return {"r": None, "ci_low": None, "ci_high": None, "p": None, "n": n, "note": "zero_variance"}
    r = float(np.corrcoef(arr_x, arr_y)[0, 1])
    if math.isnan(r):
        return {"r": None, "ci_low": None, "ci_high": None, "p": None, "n": n}

    # Fisher z 变换求 95% CI
    if abs(r) < 1:
        z = 0.5 * math.log((1 + r) / (1 - r))
        se = 1.0 / math.sqrt(n - 3)
        z_low = z - 1.96 * se
        z_high = z + 1.96 * se
        # 逆变换
        r_low = (math.exp(2 * z_low) - 1) / (math.exp(2 * z_low) + 1)
        r_high = (math.exp(2 * z_high) - 1) / (math.exp(2 * z_high) + 1)
    else:
        r_low = r_high = r

    # t 检验 p 值
    if n > 2 and abs(r) < 1:
        t_stat = r * math.sqrt(n - 2) / math.sqrt(1 - r * r)
        # 大样本近似双尾 p
        # 使用正态近似（n 大时 t→正态）
        p = 2 * (1 - _norm_cdf(abs(t_stat)))
    else:
        p = None

    return {"r": round(r, 4), "ci_low": round(r_low, 4), "ci_high": round(r_high, 4),
            "p": round(p, 6) if p is not None else None, "n": n}


def _norm_cdf(x: float) -> float:
    """标准正态 CDF（近似）。"""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def quintile_winrate(factor_values: list[float], returns: list[float], n_bins: int = 5) -> dict:
    """五分位胜率。returns > 0 = 胜。"""
    n = len(factor_values)
    if n < n_bins * 2:
        return {"bins": [], "n": n, "note": "样本不足"}
    arr = np.array(factor_values, dtype=float)
    ret = np.array(returns, dtype=float)
    # 按因子值排序后分 5 组
    order = np.argsort(arr)
    bin_size = n // n_bins
    bins = []
    for i in range(n_bins):
        start = i * bin_size
        end = (i + 1) * bin_size if i < n_bins - 1 else n
        idx = order[start:end]
        bin_rets = ret[idx]
        win = int((bin_rets > 0).sum())
        total = len(bin_rets)
        bins.append({
            "quintile": i + 1,
            "factor_range": [round(float(arr[idx].min()), 2), round(float(arr[idx].max()), 2)],
            "win_rate": round(win / total * 100, 2) if total > 0 else None,
            "avg_return": round(float(bin_rets.mean()), 4) if total > 0 else None,
            "n": total,
        })
    return {"bins": bins, "n": n}


def correlation_matrix(factors_data: dict[str, list[float]], valid_samples: list[dict]) -> dict:
    """因子相关矩阵（Pearson）。只在两个因子都有值的样本上计算。"""
    keys = list(factors_data.keys())
    matrix = {}
    for i, k1 in enumerate(keys):
        for j, k2 in enumerate(keys):
            if i >= j:
                continue
            # 对齐：只取两个因子都有值的样本
            paired = [(s.get(k1), s.get(k2)) for s in valid_samples
                      if s.get(k1) is not None and s.get(k2) is not None]
            if len(paired) < 10:
                matrix[f"{k1}__{k2}"] = {"r": None, "ci_low": None, "ci_high": None, "n": len(paired)}
                continue
            xs = [p[0] for p in paired]
            ys = [p[1] for p in paired]
            r = pearson_with_ci(xs, ys)
            matrix[f"{k1}__{k2}"] = {"r": r["r"], "ci_low": r["ci_low"], "ci_high": r["ci_high"], "n": r["n"]}
    return {"factors": keys, "pairs": matrix}


def pca_variance(data_matrix: np.ndarray) -> dict:
    """PCA 主成分方差比（numpy SVD，不依赖 sklearn）。

    data_matrix: (n_samples, n_factors) 标准化后。
    返回各主成分解释方差比。
    """
    # 标准化
    mean = data_matrix.mean(axis=0)
    std = data_matrix.std(axis=0)
    std[std == 0] = 1
    normed = (data_matrix - mean) / std
    # 协方差矩阵特征值分解
    cov = np.cov(normed, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    # 降序
    idx = np.argsort(eigvals)[::-1]
    eigvals = eigvals[idx]
    total = eigvals.sum()
    if total == 0:
        return {"explained_variance_ratio": [], "note": "零方差"}
    ratios = [round(float(v / total), 4) for v in eigvals]
    cum = []
    s = 0
    for r in ratios:
        s += r
        cum.append(round(s, 4))
    return {"explained_variance_ratio": ratios, "cumulative": cum}


def to_jsonable(obj):
    """递归转 numpy 类型为原生 Python 类型，保证 JSON 可序列化。"""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    return obj


def main() -> int:
    samples, benchmarks = load_samples()
    print(f"[0b] 总样本: {len(samples)}")

    # 过滤出有次日收益的样本
    valid = [s for s in samples
             if not s.get("missing_next_bar")
             and s.get("return_open2close") is not None
             and s.get("next_pctChg") is not None]
    print(f"[0b] 有效样本（有 next_bar + 收益）: {len(valid)}")

    returns_close2close = [s["return_close2close"] for s in valid if s.get("return_close2close") is not None]
    returns_open2close = [s["return_open2close"] for s in valid]
    next_pct = [s["next_pctChg"] for s in valid]

    # 整体胜率
    c2c_win = sum(1 for r in returns_close2close if r > 0)
    o2c_win = sum(1 for r in returns_open2close if r > 0)
    overall_wr_c2c = round(c2c_win / len(returns_close2close) * 100, 2) if returns_close2close else None
    overall_wr_o2c = round(o2c_win / len(returns_open2close) * 100, 2) if returns_open2close else None

    # 各因子回归
    factor_results = {}
    factors_data = {}
    for f in FACTORS:
        vals = [s.get(f) for s in valid if s.get(f) is not None]
        rets = [s["return_open2close"] for s in valid if s.get(f) is not None]
        if len(vals) < 10:
            factor_results[f] = {"error": "样本不足", "n": len(vals)}
            continue
        factors_data[f] = vals
        r_ci = pearson_with_ci(vals, rets)
        qwin = quintile_winrate(vals, rets)
        factor_results[f] = {
            **r_ci,
            "quintile_winrate": qwin,
            "significant": r_ci["ci_low"] is not None and r_ci["ci_low"] > 0 or (r_ci["ci_high"] is not None and r_ci["ci_high"] < 0),
            "ci_excludes_zero": r_ci["ci_low"] is not None and r_ci["ci_high"] is not None and (r_ci["ci_low"] > 0 or r_ci["ci_high"] < 0),
        }

    # 因子相关矩阵 + PCA
    common_factors = [f for f in FACTORS if f in factors_data]
    corr = correlation_matrix({f: factors_data[f] for f in common_factors}, valid)

    # PCA：构建矩阵——只在所有 common_factors 都有值的样本上构建
    complete_samples = [s for s in valid if all(s.get(f) is not None for f in common_factors)]
    if len(complete_samples) > 10:
        mat = np.array([[s[f] for f in common_factors] for s in complete_samples])
        pca = pca_variance(mat)
        pca["n_complete"] = len(complete_samples)
    else:
        pca = {"note": "样本不足", "n_complete": len(complete_samples)}

    # alpha 来源假设验证（§14.1）
    alpha_hypotheses = verify_alpha_hypotheses(valid, factors_data)

    # Bonferroni 校正
    n_tests = len([f for f in factor_results if "r" in factor_results and factor_results[f].get("r") is not None])
    bonferroni = {}
    for f, res in factor_results.items():
        if res.get("p") is not None:
            adj_p = min(res["p"] * max(n_tests, 1), 1.0)
            bonferroni[f] = {"raw_p": res["p"], "adjusted_p": round(adj_p, 6),
                             "significant_after_correction": adj_p < 0.05}

    # qualify 阈值分析（Phase 0c 一并算）
    qualify_analysis = qualify_threshold_analysis(valid)

    output = {
        "meta": {
            "total_samples": len(samples),
            "valid_samples": len(valid),
            "factors_tested": FACTORS,
            "n_tests": n_tests,
            "benchmark_A": benchmarks.get("benchmark_A"),
            "benchmark_B": benchmarks.get("benchmark_B"),
        },
        "overall_win_rates": {
            "close2close": overall_wr_c2c,
            "open2close": overall_wr_o2c,
            "n_c2c": len(returns_close2close),
            "n_o2c": len(returns_open2close),
        },
        "factor_significance": factor_results,
        "correlation_matrix": corr,
        "pca": pca,
        "alpha_hypotheses": alpha_hypotheses,
        "bonferroni_correction": bonferroni,
        "qualify_threshold_analysis": qualify_analysis,
    }

    OUT.write_text(json.dumps(to_jsonable(output), ensure_ascii=False, indent=2))
    print(f"[0b] 输出: {OUT}")
    print(f"[0b] 整体胜率 c2c={overall_wr_c2c}% o2c={overall_wr_o2c}%")
    for f, res in factor_results.items():
        if "r" in res and res["r"] is not None:
            sig = "✓显著" if res.get("ci_excludes_zero") else "✗不显著"
            print(f"[0b] {f}: r={res['r']} CI=[{res['ci_low']},{res['ci_high']}] p={res['p']} {sig}")
    return 0


def verify_alpha_hypotheses(valid: list[dict], factors_data: dict) -> dict:
    """验证 §14.1 四个 alpha 来源假设。"""
    result = {}

    # A 均值回归：低频次+低连板率票 → 次日收益更高？
    freq = factors_data.get("factor_freq_score", [])
    if freq:
        arr = np.array(freq)
        rets = np.array([s["return_open2close"] for s in valid if s.get("factor_freq_score") is not None])
        median = np.median(arr)
        low_freq_rets = rets[arr <= median]
        high_freq_rets = rets[arr > median]
        result["A_mean_reversion"] = {
            "low_freq_avg_return": round(float(low_freq_rets.mean()), 4) if len(low_freq_rets) else None,
            "high_freq_avg_return": round(float(high_freq_rets.mean()), 4) if len(high_freq_rets) else None,
            "low_freq_winrate": round(float((low_freq_rets > 0).mean() * 100), 2) if len(low_freq_rets) else None,
            "high_freq_winrate": round(float((high_freq_rets > 0).mean() * 100), 2) if len(high_freq_rets) else None,
            "hypothesis_holds": (len(low_freq_rets) > 0 and len(high_freq_rets) > 0
                                 and low_freq_rets.mean() > high_freq_rets.mean()),
        }

    # B 流动性溢价：低频次票是否更小盘？（freq vs market_cap —— 无 market_cap 数据时标 missing）
    result["B_liquidity_premium"] = {
        "note": "需 float_market_cap 数据，当前 backtest_samples 无此字段，标注待补",
        "verifiable": False,
    }

    # C 小样本噪音：74 样本的 r=-0.20 在大样本上是否消失？
    seal_r = pearson_with_ci(
        [s.get("factor_seal_rate", 0) for s in valid],
        [s["return_open2close"] for s in valid],
    )
    result["C_small_sample_noise"] = {
        "large_n_r": seal_r["r"],
        "large_n": seal_r["n"],
        "small_sample_r_was": -0.20,
        "disappeared": seal_r["r"] is not None and abs(seal_r["r"]) < 0.05,
    }

    # D Wilson 压缩：低 zt_count 票的 wilson_adjusted 是否系统性低于 total_score？
    wilson = factors_data.get("wilson_adjusted", [])
    total = factors_data.get("total_score", [])
    zt = factors_data.get("zt_count_250d", [])
    if wilson and total and zt:
        w = np.array(wilson[:min(len(wilson), len(total), len(zt))])
        t = np.array(total[:len(w)])
        z = np.array(zt[:len(w)])
        low_zt_mask = z <= np.median(z)
        diff = t[low_zt_mask] - w[low_zt_mask]
        result["D_wilson_compression"] = {
            "low_zt_count_mean_diff_total_vs_wilson": round(float(diff.mean()), 4) if len(diff) else None,
            "hypothesis_holds": len(diff) > 0 and diff.mean() > 1.0,
            "note": "diff > 0 表示 total > wilson，Wilson 下界压缩了低 zt_count 票的评分",
        }

    return result


def qualify_threshold_analysis(valid: list[dict]) -> dict:
    """Phase 0c：不同总分区间的胜率 + 样本量。"""
    bands = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 1000)]
    result = {}
    for lo, hi in bands:
        band_samples = [s for s in valid if lo <= (s.get("total_score") or 0) < hi]
        if not band_samples:
            result[f"{lo}-{hi}"] = {"n": 0, "win_rate": None}
            continue
        rets = [s["return_open2close"] for s in band_samples]
        win = sum(1 for r in rets if r > 0)
        result[f"{lo}-{hi}"] = {
            "n": len(band_samples),
            "win_rate": round(win / len(rets) * 100, 2),
            "avg_return": round(float(np.mean(rets)), 4),
        }
    return result


if __name__ == "__main__":
    import sys
    sys.exit(main())
