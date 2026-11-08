# -*- coding: utf-8 -*-
"""explore_portfolio_allocation.py — 红利低波 512890 仓位规则回测验证。

practitioner reframe 落地:选股 alpha 穷尽后,散户 edge 在 sizing/风控/行为不在选股。
memory dividend-low-vol-base 给了规则(仓位 20-30% + 长期持有 + 不设止损设总仓 -15% 减仓 + 季再平衡),
但只是文字规则没回测验证。本脚本回测验证规则合理性。

组合:512890 w% + 现金 (1-w)%(现金 return = GC001 ~2%/年 无风险近似,打新 yield 零成本不占仓位)
测:
1. 不同仓位(0/20/30/50/100% 512890)的 return/Sharpe/最大回撤
2. drawdown control:512890 从滚动峰值跌 -15% 减仓一半,回到 -5% 恢复
3. 季再平衡(每 63 交易日调回目标仓位)
4. regime 分段(2019-2020 牛 / 2021-2023 红利 / 2024-2026 当前)

§1.2 工程底线:数据走 akshare 公开接口;数字从数据算禁止臆造;诚实标注盲点。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("portfolio")

ETF_CODE = "512890"
START = "20190118"
CASH_annual = 0.02  # GC001 无风险近似 2%/年


def fetch_etf() -> pd.DataFrame:
    import akshare as ak  # noqa: PLC0415
    df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", start_date=START, end_date="20261108", adjust="qfq")
    df["日期"] = pd.to_datetime(df["日期"])
    return df[["日期", "收盘"]].rename(columns={"收盘": "etf_close"})


def backtest(etf_ret: pd.Series, weight: float, rebalance_period: int = 63) -> dict:
    """固定仓位 w + 季再平衡(每 rebalance_period 日调回 w)的组合回测。
    现金 return = CASH_annual/252/日。"""
    cash_daily = CASH_annual / 252
    n = len(etf_ret)
    equity = 1.0
    cur_w = weight
    equities = [1.0]
    for i in range(n):
        r = etf_ret.iloc[i]
        port_r = cur_w * r + (1 - cur_w) * cash_daily
        equity *= (1 + port_r)
        equities.append(equity)
        # 季再平衡
        if (i + 1) % rebalance_period == 0:
            cur_w = weight
        else:
            # 漂移:根据 etf vs cash return 调整
            cur_w = cur_w * (1 + r) / (1 + port_r) if (1 + port_r) > 0 else cur_w
    eq = pd.Series(equities[1:], index=etf_ret.index)
    rets = eq.pct_change().dropna()
    ann_ret = rets.mean() * 252
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    peak = eq.cummax()
    max_dd = ((eq - peak) / peak).min()
    return {
        "仓位%": int(weight * 100),
        "年化收益%": round(ann_ret * 100, 2),
        "年化波动%": round(ann_vol * 100, 2),
        "Sharpe": round(sharpe, 3),
        "最大回撤%": round(max_dd * 100, 1),
        "终值": round(eq.iloc[-1], 2),
    }


def backtest_drawdown_control(etf_ret: pd.Series, target_w: float, dd_cut: float = -0.15, dd_recover: float = -0.05) -> dict:
    """drawdown control:512890 从滚动峰值跌 dd_cut(-15%)→ 减仓到 target_w/2;
    回到 dd_recover(-5%)→ 恢复 target_w。季再平衡基础。"""
    cash_daily = CASH_annual / 252
    n = len(etf_ret)
    equity = 1.0
    cur_w = target_w
    reduced = False
    equities = [1.0]
    n_cuts = 0
    etf_peak = 1.0
    etf_level = 1.0
    for i in range(n):
        r = etf_ret.iloc[i]
        etf_level *= (1 + r)
        if etf_level > etf_peak:
            etf_peak = etf_level
        etf_dd = (etf_level - etf_peak) / etf_peak if etf_peak > 0 else 0
        # drawdown control 触发
        if not reduced and etf_dd <= dd_cut:
            cur_w = target_w / 2
            reduced = True
            n_cuts += 1
        elif reduced and etf_dd >= dd_recover:
            cur_w = target_w
            reduced = False
        port_r = cur_w * r + (1 - cur_w) * cash_daily
        equity *= (1 + port_r)
        equities.append(equity)
        if (i + 1) % 63 == 0:
            cur_w = target_w / 2 if reduced else target_w
    eq = pd.Series(equities[1:], index=etf_ret.index)
    rets = eq.pct_change().dropna()
    ann_ret = rets.mean() * 252
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    peak = eq.cummax()
    max_dd = ((eq - peak) / peak).min()
    return {
        "目标仓位%": int(target_w * 100),
        "dd控制(-15%减半)": f"{n_cuts}次触发",
        "年化收益%": round(ann_ret * 100, 2),
        "年化波动%": round(ann_vol * 100, 2),
        "Sharpe": round(sharpe, 3),
        "最大回撤%": round(max_dd * 100, 1),
        "终值": round(eq.iloc[-1], 2),
    }


def regime_stats(etf_ret: pd.Series, weight: float) -> pd.DataFrame:
    """regime 分段:2019-2020 牛 / 2021-2023 红利 / 2024-2026 当前。"""
    cash_daily = CASH_annual / 252
    regimes = [
        ("2019-2020 牛+成长", "2019-01-01", "2020-12-31"),
        ("2021-2023 红利行情", "2021-01-01", "2023-12-31"),
        ("2024-2026 当前", "2024-01-01", "2026-12-31"),
    ]
    rows = []
    for label, s, e in regimes:
        mask = (etf_ret.index >= pd.Timestamp(s)) & (etf_ret.index <= pd.Timestamp(e))
        sub = etf_ret[mask]
        if len(sub) < 20:
            continue
        port_r = weight * sub + (1 - weight) * cash_daily
        ann_ret = port_r.mean() * 252
        ann_vol = port_r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        eq = (1 + port_r).cumprod()
        max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
        rows.append({
            "regime": label,
            "交易日": len(sub),
            "年化收益%": round(ann_ret * 100, 2),
            "年化波动%": round(ann_vol * 100, 2),
            "Sharpe": round(sharpe, 3),
            "最大回撤%": round(max_dd * 100, 1),
        })
    return pd.DataFrame(rows)


def main() -> None:
    log.info(f"=== 拉 {ETF_CODE} 红利低波 ETF 日线 ===")
    etf = fetch_etf()
    etf_ret = etf.set_index("日期")["etf_close"].pct_change().dropna()
    log.info(f"{len(etf_ret)} 天, {etf_ret.index.min()} ~ {etf_ret.index.max()}")

    # 1. 不同仓位固定 + 季再平衡
    log.info("\n=== 不同仓位 + 季再平衡(现金 2%/年)===")
    rows = [backtest(etf_ret, w) for w in [0.0, 0.20, 0.30, 0.50, 1.00]]
    print(pd.DataFrame(rows).to_string(index=False))

    # 2. drawdown control(-15% 减半)
    log.info("\n=== drawdown control(目标仓位 -15% 减半, -5% 恢复)===")
    dd_rows = [backtest_drawdown_control(etf_ret, w) for w in [0.20, 0.30, 0.50]]
    print(pd.DataFrame(dd_rows).to_string(index=False))

    # 3. 30% 仓位 regime 分段
    log.info("\n=== 30% 仓位 regime 分段 ===")
    print(regime_stats(etf_ret, 0.30).to_string(index=False))

    # 4. 50% 仓位 regime 分段(对比)
    log.info("\n=== 50% 仓位 regime 分段(对比)===")
    print(regime_stats(etf_ret, 0.50).to_string(index=False))

    # verdict
    log.info("\n=== VERDICT ===")
    base = next(r for r in rows if r["仓位%"] == 30)
    log.info(f"30% 仓位: 年化 {base['年化收益%']}% + Sharpe {base['Sharpe']} + 回撤 {base['最大回撤%']}% (vs 100% 仓位见上表)")
    log.info("memory dividend-low-vol-base 规则(20-30% + 季再平衡 + 总仓 -15% 减仓)回测验证见上")

    out = Path(__file__).parent / "explore_portfolio_allocation_result.txt"
    with out.open("w", encoding="utf-8") as f:
        f.write("=== 不同仓位 + 季再平衡 ===\n")
        f.write(pd.DataFrame(rows).to_string(index=False) + "\n\n")
        f.write("=== drawdown control ===\n")
        f.write(pd.DataFrame(dd_rows).to_string(index=False) + "\n\n")
        f.write("=== 30% 仓位 regime 分段 ===\n")
        f.write(regime_stats(etf_ret, 0.30).to_string(index=False) + "\n")
    log.info(f"\n结果已存: {out}")


if __name__ == "__main__":
    main()
