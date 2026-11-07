"""inst_dominant 10-09 真盘 top6 实盘复盘：实际 10-10 open → 10-13 close 收益 vs 回测 mean+0.457%。

trade_journal 里 6 条 signal 的 entry_price 是 10-09 信号日 close 占位（note "实际成交价待用户补"），
unrealized_pnl 是 10-09 晚快照（pre-entry 投影），exit 从未记录。本脚本用 baostock 直连取真实
10-10 open（entry）+ 10-13 close（exit），算战法口径实际收益，回答 "edge-confirmed 真活"。

关联：S236 / trade_journal inst_dominant arm / memory inst-dominant-combo-tradable-2026-10-09
"""
from __future__ import annotations

import baostock as bs

# 10-09 LHB signal → 10-10 open buy → 10-13 close sell (跨周末, T+1 open → T+2 close nostop)
TOP6 = {
    "002384": "sz.002384",
    "688313": "sh.688313",
    "300684": "sz.300684",
    "600330": "sh.600330",
    "002614": "sz.002614",
    "000513": "sz.000513",
}
BACKTEST_MEAN = 0.457  # S236 basic top6 nostop mean
SIGNAL_DATE = "2026-10-09"  # Friday: LHB 信号日（盘后公布）
ENTRY_DATE = "2026-10-12"  # T+1 open（周一，跨周末）
EXIT_DATE = "2026-10-13"  # T+2 close（周二，持有 1 交易日）


def fetch(code: str) -> dict:
    """baostock 取 10-09 close / 10-10 open / 10-13 close（前复权 adjustflag=2）。"""
    rs = bs.query_history_k_data_plus(
        code, "date,open,close,high,low", start_date="2026-10-08",
        end_date="2026-10-17", frequency="d", adjustflag="2",
    )
    bars = {}
    while rs.error_code == "0" and rs.next():
        d, o, c, *_ = rs.get_row_data()
        bars[d] = (o, c)
    sc = bars.get(SIGNAL_DATE, (None, None))[0]  # 10-09 open = journal 占位价
    eo = bars.get(ENTRY_DATE, (None, None))[0]
    xc = bars.get(EXIT_DATE, (None, None))[1]
    sc = float(sc) if sc else None
    eo = float(eo) if eo else None
    xc = float(xc) if xc else None
    ret = (xc - eo) / eo * 100 if (eo and xc) else None
    return {"sig_close": sc, "entry_open": eo, "exit_close": xc, "ret": ret}


def main() -> None:
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[baostock login failed] {lg.error_code} {lg.error_msg}")
        return
    print(f"{'code':<8}{'10-09close':>12}{'10-10open':>12}{'10-13close':>12}{'return':>10}")
    print("-" * 54)
    results = {}
    for sc, bc in TOP6.items():
        r = fetch(bc)
        results[sc] = r
        sc_s = f"{r['sig_close']:.2f}" if r["sig_close"] else "N/A"
        eo_s = f"{r['entry_open']:.2f}" if r["entry_open"] else "N/A"
        xc_s = f"{r['exit_close']:.2f}" if r["exit_close"] else "N/A"
        rt_s = f"{r['ret']:+.3f}%" if r["ret"] is not None else "N/A"
        print(f"{sc:<8}{sc_s:>12}{eo_s:>12}{xc_s:>12}{rt_s:>10}")
    bs.logout()

    rets = [r["ret"] for r in results.values() if r["ret"] is not None]
    print()
    if not rets:
        print("[no valid returns]")
        return
    mean = sum(rets) / len(rets)
    winners = sum(1 for r in rets if r > 0)
    print(f"等权 mean (n={len(rets)}): {mean:+.4f}%")
    print(f"回测基准 (S236 basic top6 nostop): +{BACKTEST_MEAN}%")
    print(f"实盘/回测 比: {mean / BACKTEST_MEAN:.2f}x")
    print(f"胜率: {winners}/{len(rets)} = {winners / len(rets) * 100:.1f}%")
    print(f"最好: {max(rets):+.3f}%  最差: {min(rets):+.3f}%  极差: {max(rets) - min(rets):.3f}%")


if __name__ == "__main__":
    main()
