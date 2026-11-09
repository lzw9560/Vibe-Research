# -*- coding: utf-8 -*-
"""explore_commodity_trend_follow.py — 商品 ETF 时间序列趋势跟踪 backtest。

向外求(outward explore w46t4bvo8 synthesis 最高杠杆):商品 ETF 趋势跟踪是不同资产类别 + 不同策略范式,
在项目"选股因子 alpha 穷尽"的已证伪 scope 之外。金融学最强先验:趋势跟踪 t~5 两世纪(arxiv:1404.3274)
+ 黄金期货趋势动量 Sharpe 2.88 OOS(arxiv:2511.08571)。

测:
- 518880 黄金 ETF(13yr)/ 161129 原油 ETF(9yr)/ 159980 有色 ETF(7yr)
- time-series trend following:close > MA(lookback) 满仓,< MA 空仓(现金 2%/年)
- 多 lookback(20/60/120/250 日 = 1/3/6/12 月)+ Bonferroni×4
- T+0 cost 0.4%(买卖各 0.2%)+ T+1 信号防前视
- vs 买入持有

诚实 caveat:
- long-only ETF 不能做空只捕获上涨趋势(下跌段空仓现金,不赚做空)
- 黄金 2024-2026 巨牛 = regime 风险可能不泛化
- arxiv:2607.20093 Retail Trader's Ruin 挑战散户趋势信号(虽测股票非商品)
- 多 lookback 须 Bonferroni×4 防过拟合

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
log = logging.getLogger("trend")

CASH_annual = 0.02  # 空仓现金 2%/年(GC001 近似)
COST = 0.004  # T+0 买卖 cost 0.4%(买卖各 0.2%)
LOOKBACKS = [20, 60, 120, 250]  # 1/3/6/12 月
N_BONF = len(LOOKBACKS)  # Bonferroni×4
ETFS = [("518880", "黄金ETF"), ("161129", "原油ETF"), ("159980", "有色ETF")]


def fetch_etf(code: str) -> pd.Series:
    import akshare as ak  # noqa: PLC0415
    df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
    df["日期"] = pd.to_datetime(df["日期"])
    s = df.set_index("日期")["收盘"].astype(float)
    return s.sort_index()


def trend_follow(close: pd.Series, lookback: int) -> dict:
    """time-series trend: close > MA(lookback) 满仓, < MA 空仓现金。T+1 信号防前视 + cost。"""
    ma = close.rolling(lookback).mean()
    signal = (close > ma).astype(int).shift(1).fillna(0)  # T+1 防 look-ahead
    ret = close.pct_change()
    cash_daily = CASH_annual / 252
    port_ret = signal * ret + (1 - signal) * cash_daily
    # cost: signal 变化时扣 COST
    turnover = signal.diff().abs().fillna(0)
    port_ret = port_ret - turnover * COST
    port_ret = port_ret.dropna()
    # 买入持有
    bh_ret = ret.dropna()
    # 统计
    def stats(r):
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + r).cumprod()
        max_dd = ((cum - cum.cummax()) / cum.cummax()).min()
        return {"年化%": round(ann_ret * 100, 2), "波动%": round(ann_vol * 100, 2),
                "Sharpe": round(sharpe, 3), "回撤%": round(max_dd * 100, 1)}
    tf_s = stats(port_ret)
    bh_s = stats(bh_ret)
    # 超额 vs 买入持有(日频配对, NW t 后算)
    excess = port_ret - bh_ret.reindex(port_ret.index)
    excess_ann = excess.mean() * 252
    excess_vol = excess.std() * np.sqrt(252)
    # 简化 t-test(非 NW, explore 用)
    n = len(excess)
    t_stat = excess.mean() / (excess.std() / np.sqrt(n)) if excess.std() > 0 else 0
    from scipy import stats as sps  # noqa: PLC0415
    p_two = 2 * (1 - sps.norm.cdf(abs(t_stat))) if n > 0 else 1
    p_bonf = min(p_two * N_BONF, 1.0)
    # 持仓占比
    holding_pct = signal.mean()
    return {
        "lookback": lookback,
        "tf": tf_s, "bh": bh_s,
        "超额年化%": round(excess_ann * 100, 2),
        "t": round(t_stat, 2),
        "p_two": round(p_two, 4),
        "p_bonf×4": round(p_bonf, 4),
        "PASS_Bonf": p_bonf < 0.05,
        "持仓占比%": round(holding_pct * 100, 0),
        "n_days": n,
    }


def main() -> None:
    out_rows = []
    for code, name in ETFS:
        log.info(f"\n=== {code} {name} ===")
        close = fetch_etf(code)
        log.info(f"{len(close)} 天, {close.index.min()} ~ {close.index.max()}")
        for lb in LOOKBACKS:
            r = trend_follow(close, lb)
            r["code"] = code
            r["name"] = name
            out_rows.append(r)
            log.info(f"  MA{lb}: tf Sharpe {r['tf']['Sharpe']} (年化 {r['tf']['年化%']}% 回撤 {r['tf']['回撤%']}%) "
                     f"vs bh Sharpe {r['bh']['Sharpe']} (年化 {r['bh']['年化%']}%) | 超额 {r['超额年化%']}% t={r['t']} "
                     f"Bonf×4={r['p_bonf×4']} {'PASS' if r['PASS_Bonf'] else 'FAIL'} 持仓{r['持仓占比%']}%")

    # verdict
    log.info("\n=== VERDICT ===")
    df = pd.DataFrame(out_rows)
    pass_rows = df[df["PASS_Bonf"]]
    if len(pass_rows):
        log.info(f"Bonf×4 PASS: {len(pass_rows)} 配置")
        for _, r in pass_rows.iterrows():
            log.info(f"  {r['code']} {r['name']} MA{r['lookback']}: 超额 {r['超额年化%']}% t={r['t']} "
                     f"tf Sharpe {r['tf']['Sharpe']} vs bh {r['bh']['Sharpe']}")
    else:
        log.info("全 FAIL Bonf×4:商品 ETF 趋势跟踪未显著超买入持有(可能 regime/long-only/cost 侵蚀)")

    out = Path(__file__).parent / "explore_commodity_trend_follow_result.txt"
    with out.open("w", encoding="utf-8") as f:
        for _, r in df.iterrows():
            f.write(f"{r['code']} {r['name']} MA{r['lookback']}: tf{r['tf']} vs bh{r['bh']} "
                    f"超额{r['超额年化%']}% t={r['t']} Bonf×4={r['p_bonf×4']} "
                    f"{'PASS' if r['PASS_Bonf'] else 'FAIL'} 持仓{r['持仓占比%']}%\n")
    log.info(f"\n结果已存: {out}")


if __name__ == "__main__":
    main()
