# -*- coding: utf-8 -*-
"""explore_dividend_low_vol_etf.py — 红利低波 512890 底仓诚实收口。

认知债:value 三族(E/P/B/P/D/P)月频死后显著负(t-3.5),但红利低波 512890 仍作为底仓持有——
这个矛盾必须收口。512890 是 value proxy(value 死了它也该死)还是独立 alpha(与 value 死矛盾)?

收口第一步:512890 vs 沪深300 的 return/波动/Sharpe/drawdown/beta/alpha + 低波特征。
- 若 512890 跑赢沪深300 + 低波 → 资产配置价值(分红现金流+低波,非 selection alpha)
- 若 512890 跑输 → 底仓该调整
- market beta 回归 alpha 是否显著 → 是否有 market 之外的收益来源

诚实框定(memory dividend-low-vol-base + value-factor-falsified):
- 512890 上市 2019-01-18,测 2019-2026(7.8 年)。ETF 不退市,幸存者偏差影响小(不像个股)
- benchmark 沪深300 是大盘,512890 红利低波(中小盘价值),beta 可能 <1
- value proxy 控制(E/P+D/P)需月频因子数据,本脚本做 market beta 第一步,proxy 控制留 II 期
- A 股 2020+ 红利行情特异性(结构性行情,中证红利 2021-2023 跑赢成长)
- 1510.01679 学术:控制 E/P+D/P 后红利低波 residual flat → value proxy 非 independent alpha(SSRN paywalled 未独立核实)

§1.2 工程底线:数据走 akshare 公开接口;数字从数据算禁止臆造;诚实框定底仓定位。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("divlowvol")

ETF_CODE = "512890"
BENCH_CODE = "sh000300"  # 沪深300
START = "20190118"  # 512890 上市日


def fetch_etf() -> pd.DataFrame:
    import akshare as ak  # noqa: PLC0415
    df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", start_date=START, end_date="20261108", adjust="qfq")
    df["日期"] = pd.to_datetime(df["日期"])
    return df[["日期", "收盘"]].rename(columns={"收盘": "etf_close"})


def fetch_bench() -> pd.DataFrame:
    import akshare as ak  # noqa: PLC0415
    df = ak.stock_zh_index_daily_em(symbol=BENCH_CODE)
    df["date"] = pd.to_datetime(df["date"])
    mask = df["date"] >= pd.Timestamp(START)
    return df.loc[mask, ["date", "close"]].rename(columns={"date": "日期", "close": "bench_close"})


def stats(returns: pd.Series, label: str) -> dict:
    """年化 return / 波动 / Sharpe / max drawdown（日 return → 年化×252）。"""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    # max drawdown
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()
    return {
        "标的": label,
        "交易日": len(returns),
        "年化收益%": round(ann_ret * 100, 2),
        "年化波动%": round(ann_vol * 100, 2),
        "Sharpe": round(sharpe, 3),
        "最大回撤%": round(max_dd * 100, 1),
    }


def main() -> None:
    log.info(f"=== 拉 {ETF_CODE} 红利低波 ETF + 沪深300 benchmark ===")
    etf = fetch_etf()
    bench = fetch_bench()
    log.info(f"512890: {len(etf)} 天, {etf['日期'].min()} ~ {etf['日期'].max()}")
    log.info(f"沪深300: {len(bench)} 天, {bench['日期'].min()} ~ {bench['日期'].max()}")

    # 对齐日期
    df = pd.merge(etf, bench, on="日期", how="inner").dropna()
    df["etf_ret"] = df["etf_close"].pct_change()
    df["bench_ret"] = df["bench_close"].pct_change()
    df = df.dropna()
    log.info(f"对齐后: {len(df)} 天")

    # 1. 基础统计对比
    log.info("\n=== 基础统计对比 ===")
    etf_stats = stats(df["etf_ret"], "512890红利低波")
    bench_stats = stats(df["bench_ret"], "沪深300")
    cmp = pd.DataFrame([etf_stats, bench_stats])
    print(cmp.to_string(index=False))

    # 2. market beta 回归:etf_ret ~ bench_ret
    log.info("\n=== market beta 回归 (512890 ~ 沪深300) ===")
    x = df["bench_ret"].values
    y = df["etf_ret"].values
    # OLS: y = alpha + beta * x
    beta, alpha = np.polyfit(x, y, 1)
    # alpha 年化
    alpha_ann = alpha * 252
    # R²
    y_pred = alpha + beta * x
    ss_res = ((y - y_pred) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    # residual vol（特质波动）
    resid = y - y_pred
    resid_vol_ann = resid.std() * np.sqrt(252)
    print(f"  beta = {beta:.3f}（<1 = 低 beta 防御型）")
    print(f"  alpha(日) = {alpha:.5f} → 年化 alpha = {alpha_ann*100:.2f}%")
    print(f"  R² = {r2:.3f}（市场 beta 解释比例）")
    print(f"  残差年化波动 = {resid_vol_ann*100:.2f}%（特质风险）")

    # 3. 低波特征
    log.info("\n=== 低波特征 ===")
    etf_vol = df["etf_ret"].std() * np.sqrt(252)
    bench_vol = df["bench_ret"].std() * np.sqrt(252)
    print(f"  512890 年化波动 = {etf_vol*100:.2f}% vs 沪深300 = {bench_vol*100:.2f}%")
    print(f"  波动比 = {etf_vol/bench_vol:.3f}（<1 = 确实低波）")

    # 4. 分年表现（看 2020+ 红利行情特异性）
    log.info("\n=== 分年收益对比（看 2020+ 红利行情特异性）===")
    df["year"] = df["日期"].dt.year
    yearly = df.groupby("year").agg(
        etf_ret=("etf_ret", lambda x: (1 + x).prod() - 1),
        bench_ret=("bench_ret", lambda x: (1 + x).prod() - 1),
    )
    yearly["超额%"] = (yearly["etf_ret"] - yearly["bench_ret"]) * 100
    yearly["etf_ret%"] = (yearly["etf_ret"] * 100).round(1)
    yearly["bench_ret%"] = (yearly["bench_ret"] * 100).round(1)
    print(yearly[["etf_ret%", "bench_ret%", "超额%"]].round(1).to_string())

    # 5. verdict
    log.info("\n=== VERDICT ===")
    log.info(f"512890 年化 {etf_stats['年化收益%']}% vs 沪深300 {bench_stats['年化收益%']}%, "
             f"超额 {etf_stats['年化收益%']-bench_stats['年化收益%']:+.2f}%")
    log.info(f"波动 {etf_stats['年化波动%']}% vs {bench_stats['年化波动%']}% (低波比 {etf_vol/bench_vol:.3f}), "
             f"Sharpe {etf_stats['Sharpe']} vs {bench_stats['Sharpe']}")
    log.info(f"market beta {beta:.3f} + 年化 alpha {alpha_ann*100:+.2f}% (R² {r2:.2f})")
    log.info(f"最大回撤 512890 {etf_stats['最大回撤%']}% vs 沪深300 {bench_stats['最大回撤%']}%")

    # 诚实框定
    out = Path(__file__).parent / "explore_dividend_low_vol_etf_result.txt"
    with out.open("w", encoding="utf-8") as f:
        f.write("=== 基础统计对比 ===\n")
        f.write(cmp.to_string(index=False) + "\n\n")
        f.write(f"market beta = {beta:.3f}, 年化 alpha = {alpha_ann*100:+.2f}%, R² = {r2:.3f}\n")
        f.write(f"残差年化波动 = {resid_vol_ann*100:.2f}%\n\n")
        f.write("=== 分年收益 ===\n")
        f.write(yearly[["etf_ret%", "bench_ret%", "超额%"]].round(1).to_string() + "\n")
    log.info(f"\n结果已存: {out}")


if __name__ == "__main__":
    main()
