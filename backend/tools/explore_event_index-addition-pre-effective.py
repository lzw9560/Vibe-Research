# -*- coding: utf-8 -*-
"""指数调入 announcement→effective 真 Shleifer 窗口（pre-effective run-up）事件研究。

策略假设 (Shleifer forced-buying edge):
  指数公司公告调入后→生效前（announcement→effective gap ~10-14 天），
  跟踪该指数的被动资金须在生效日前买入新成份股 → pre-effective price pressure → run-up。
  entry = announcement+1 open, exit = effective close (或 effective-1 close),
  BHAR vs matched universe。若 run-up 为正且 net > cost → 可交易 edge。

关键数据依赖（决定性）:
  本策略由 announcement 日 *定义*——entry = announcement+1 open。
  无 announcement 日 ⇒ 无 entry ⇒ 无 window ⇒ 无法测。这不是"数据缺一点可补"，
  是策略的 *结构性前提* 缺失。effective 日（baostock 有）是窗口的 *终点*，
  但起点（announcement 日）才是 Shleifer 假设的核心——被动资金在 *公告后、生效前* 买入。

数据现状（2026-10-06 独立实测，非引用 probe）:
  - baostock query_hs300/sz50/zz500_stocks(date) 仅返 ['updateDate','code','code_name']，
    updateDate = 生效/快照日（如 2024-06-17），无 announcement 日。全 query_* 方法表
    无任何与"指数调整公告"相关的函数（query_adjust_factor 是复权因子非调整公告）。
  - akshare: 无 CSI(000300/000016/000905) 历史调整函数。
    index_stock_cons_csindex('000300') 返 9 列含'日期'=2026-09-30 快照日非公告日；
    index_detail_hist_adjust_cni('399300') 返空（仅覆盖国证深证系 399xxx 非 CSI 系）。
  - 公告日公开存在（中证指数公司 csindex.com.cn / 上交所 sse.com.cn 发布"定期调整结果公告"，
    公告→生效 gap ~10-14 天 = Shleifer 窗口），但:
    (a) 无免费可编程 API（csindex 无公开 REST，仅当前成份 Excel）；
    (b) WebFetch 取 csindex.com.cn / sse.com.cn / szse.cn 被域名策略拦截；
    (c) WebSearch 能从新闻引述提取近完整对照表（如 2025-11-28 公告→2025-12-12 生效），
        但这是手动汇编日历非可 fetch 的结构化源，且仅近 1-2 年完整，2018-2023 须逐条搜；
    (d) 唯一含结构化公告日的源 = 付费 CSDN 数据集（2005-2023, ¥12-23）——需用户购买决策
        （CLAUDE.md: 花钱操作须问用户）。
  - 结构性 power 限制（即使拿到公告日）: 半年一次 rebalance, 8 年仅 ~16 事件日/指数 < 60
    → per-day-mean t underpowered（与 explore_event_index-addition.py 同一结构性限制）。

诚实判定: honest_verdict = "no-data"
  原因: 公告日（策略的结构性前提）无免费可编程数据源。
  非用 effective 日测 announcement→effective 窗口——那是 *不同窗口*（post-inclusion 漂移，
  已由 explore_event_index-addition.py 测过=underpowered/反转），用它替代 = 窗口偷换 = 外推，
  违 §44 v3 "禁止外推"。本脚本诚实报 no-data，不臆造窗口、不偷换口径。

禁止外推:
  - 单事件策略无数据 ≠ 事件驱动有/无 edge ≠ 短线有/无 edge
  - 本 no-data 仅指 announcement→effective 窗口 *未测*（数据不可得），非"该窗口无 edge"
"""

from __future__ import annotations
import sys
from pathlib import Path

# import shared helpers (DRY — task 要求 import _factor_helpers)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import (  # noqa: E402
    ev_stats,
    day_paired_t,
    bonferroni_p,
    norm_sf_positive,
    ALPHA,
    COST,
)

STRATEGY = "index-addition-pre-effective"
FILTER_DEF = (
    "指数调入股, entry=announcement+1 open, exit=effective close, "
    "BHAR vs matched index (sh.000300/000016/000905). "
    "Shleifer forced-buying: 被动资金公告后生效前买入→pre-effective run-up. "
    "要求 announcement 日（结构性前提）。"
)
CROSS_STRATEGY_N = 4  # Bonferroni ×4 (2 策略 × 2 窗口 announcement-gap + post-inclusion)


def probe_baostock_announcement_date() -> dict:
    """实测 baostock 是否提供指数调整 announcement 日。返回 {available, fields, methods}."""
    import baostock as bs

    lg = bs.login()
    login_ok = lg.error_code == "0"
    out = {"available": False, "login_ok": login_ok, "fields": [], "has_announcement_fn": False}
    if not login_ok:
        bs.logout()
        return out
    try:
        rs = bs.query_hs300_stocks(date="2024-06-17")
        out["fields"] = list(rs.fields) if rs.fields else []
        # 检查字段名是否含 announcement/公告
        has_ann = any("announce" in (f or "").lower() or "公告" in (f or "") for f in out["fields"])
        out["available"] = has_ann
        # 全 query_* 方法扫描
        methods = [n for n in dir(bs) if n.startswith("query")]
        out["methods"] = methods
        out["has_announcement_fn"] = any("announce" in m.lower() for m in methods)
    finally:
        bs.logout()
    return out


def probe_akshare_announcement_date() -> dict:
    """实测 akshare 是否提供 CSI 历史调整 announcement 日。返回 {available, detail}."""
    import akshare as ak
    import inspect

    out = {"available": False, "detail": []}

    # 1. 当前成份 snapshot（确认'日期'是快照非公告日）
    try:
        df = ak.index_stock_cons_csindex(symbol="000300")
        cols = list(df.columns)
        date_col = cols[0] if cols else ""
        sample_date = str(df[date_col].iloc[0]) if len(df) else ""
        is_snapshot = sample_date >= "2026-01-01"  # 近期日期=快照非历史公告日
        out["detail"].append(f"index_stock_cons_csindex('000300'): cols={cols}, 首行日期={sample_date}, is_snapshot={is_snapshot} (非公告日)")
        if not any("announce" in (c or "").lower() or "公告" in (c or "") for c in cols):
            out["available"] = False
        else:
            out["available"] = True
    except Exception as e:
        out["detail"].append(f"index_stock_cons_csindex error: {e}")

    # 2. 唯一历史调整函数（确认覆盖范围+无公告日列）
    try:
        df2 = ak.index_detail_hist_adjust_cni(symbol="399300")
        out["detail"].append(
            f"index_detail_hist_adjust_cni('399300'): shape={df2.shape}, cols={list(df2.columns)} (HS300=000300 非 399 系→返空, 该函数仅覆盖国证深证系 399xxx)"
        )
    except Exception as e:
        out["detail"].append(f"index_detail_hist_adjust_cni error: {e}")

    # 3. 扫描所有 index adjust/cons 函数
    fns = [n for n in dir(ak) if "index" in n.lower() and ("adjust" in n.lower() or "cons" in n.lower() or "detail" in n.lower())]
    has_ann_fn = any("announce" in n.lower() for n in fns)
    out["has_announcement_fn"] = has_ann_fn
    out["index_funcs"] = fns
    return out


def build_picks(announcement_dates: dict) -> list[dict]:
    """从 announcement 日构建 picks。entry=announcement+1 open, exit=effective close.

    需 announcement_dates: {(index_key, code): {announcement_date, effective_date}}.
    若 announcement_dates 为空（数据不可得）→ 返 [] → 无法测。
    这正是本策略的结构性前提：无 announcement 日 = 无 picks。
    """
    if not announcement_dates:
        return []
    picks: list[dict] = []
    # 若有公告日数据，此处应:
    #   1. baostock fetch kline (announcement-1 ~ effective+2)
    #   2. entry = announcement+1 open (T+1 open, 非收盘——公告当日收盘后才可行动)
    #   3. exit = effective close (被动资金 effective 日完成建仓, run-up 在 effective 前结束)
    #   4. BHAR = stock_ret - matched_index_ret (同窗口, 隔离市场 beta)
    #   5. is_yizi_t1 跳过 (announcement+1 一字涨停买不进)
    #   6. per-day-mean t (cluster by announcement date)
    # 公告日数据不可得 → build_picks 返 [] → 下游 verdict = no-data
    return picks


def main() -> None:
    print("=" * 72)
    print(f"事件研究: {STRATEGY} (announcement→effective 真 Shleifer 窗口)")
    print("=" * 72)
    print(f"假设: 公告后→生效前被动资金 forced buying → pre-effective run-up")
    print(f"entry=announcement+1 open, exit=effective close, BHAR vs matched index")
    print(f"过严口径: BHAR 非 raw EV (除权除息教训) | per-day-mean t | Bonf×{CROSS_STRATEGY_N} | walk-forward OOS + train_ev>0")
    print()

    # ---- 1. 数据前提探测（独立实测，非引用 probe）----
    print("[1/3] 数据前提探测: announcement 日是否可编程获取")
    print("-" * 72)
    print("(a) baostock...")
    bs_probe = probe_baostock_announcement_date()
    print(f"    login_ok={bs_probe['login_ok']}")
    print(f"    query_hs300_stocks fields={bs_probe['fields']}")
    print(f"    'updateDate' = 生效/快照日 (如 2024-06-17), 非 announcement 日")
    print(f"    全 query_* 方法 ({len(bs_probe.get('methods', []))}): {bs_probe.get('methods', [])[:8]}{'...' if len(bs_probe.get('methods', [])) > 8 else ''}")
    print(f"    has_announcement_fn={bs_probe['has_announcement_fn']} → {'有' if bs_probe['available'] else '无'} announcement 日")

    print("\n(b) akshare...")
    ak_probe = probe_akshare_announcement_date()
    for d in ak_probe["detail"]:
        print(f"    {d}")
    print(f"    index adjust/cons funcs: {ak_probe.get('index_funcs', [])}")
    print(f"    has_announcement_fn={ak_probe.get('has_announcement_fn', False)} → {'有' if ak_probe['available'] else '无'} announcement 日")

    announcement_available = bs_probe["available"] or ak_probe["available"]
    print(f"\n(c) 其他通道（probe 已测+WebSearch 补充验证）:")
    print(f"    csindex.com.cn: 公告日公开但无 REST API; WebFetch 被域名策略拦截")
    print(f"    sse.com.cn / szse.cn: WebFetch 全拦截")
    print(
        f"    WebSearch: 能从新闻引述提取近 1-2 年对照表 (如 2025-11-28 公告→2025-12-12 "
        f"生效, gap 14 天=Shleifer 窗口), 但手动汇编日历非可 fetch 结构化源, 2018-2023 须逐条搜"
    )
    print(f"    付费 CSDN 数据集 (2005-2023, ¥12-23): 唯一含结构化公告日, 需用户购买决策")

    print(f"\n>>> announcement 日可编程获取: {announcement_available}")
    if not announcement_available:
        print(">>> 结构性前提缺失: 策略由 announcement 日 *定义* (entry=announcement+1 open),")
        print("    无 announcement 日 ⇒ 无 entry ⇒ 无 window ⇒ 无法测。")

    # ---- 2. build_picks（依赖 announcement 日）----
    print(f"\n[2/3] build_picks (entry=announcement+1 open, exit=effective close)")
    print("-" * 72)
    announcement_dates: dict = {} if not announcement_available else {}
    picks = build_picks(announcement_dates)
    print(f"    announcement_dates 可得: {len(announcement_dates)} 条")
    print(f"    picks 构建: {len(picks)} 条 (announcement 日不可得→0)")

    # ---- 3. verdict cascade ----
    print(f"\n[3/3] verdict cascade (§44 v3)")
    print("-" * 72)
    if not announcement_available:
        print("    数据前提缺失 → 无法进入统计判定")
        print("    禁止用 effective 日测 announcement→effective 窗口:")
        print("      effective 日 = 窗口终点, 但起点 (announcement 日) 是 Shleifer 假设核心;")
        print("      effective-日基测试 = post-inclusion 漂移 (不同窗口), 已由")
        print("      explore_event_index-addition.py 测过 (underpowered/反转). 用它替代=窗口偷换=外推, 违 §44 v3.")
        verdict = "no-data"
        n_events = 0
        n_dates = 0
        bhar_gross = 0.0
        bhar_net = 0.0
        key = (
            "announcement 日 (策略结构性前提: entry=announcement+1 open) 无免费可编程数据源. "
            "baostock 仅 effective 快照日 (3 字段无 announcement); akshare 无 CSI 历史调整函数含公告日; "
            "csindex/sse WebFetch 被拦截; 唯一结构化源=付费 CSDN (¥12-23 需用户决策). "
            "且即使手编 ~16 半年事件日 < 60 → underpowered. "
            "未测 announcement→effective 窗口 (非该窗口无 edge——是数据不可得). "
            "禁止外推: 单事件策略 no-data ≠ 事件驱动有/无 edge ≠ 短线有/无 edge."
        )
    else:
        # 若有 announcement 日数据, 跑全口径 (此处不可达——当前无数据)
        picks_rets = [0.0]  # placeholder, 不可达
        s = ev_stats(picks_rets)
        net_ev = s["ev"] - COST * 100
        bhar_gross = s["ev"]
        bhar_net = net_ev
        n_events = s["n"]
        by_date: dict[str, list[float]] = {}
        dt = day_paired_t(by_date)
        p_raw = dt["p_one_sided"]
        p_bonf = bonferroni_p(p_raw, CROSS_STRATEGY_N)
        n_dates = dt["n_days"]
        verdict = "exploratory"  # placeholder
        key = "announcement 日可得路径 (当前不可达)"

    print(f"\n>>> HONEST VERDICT: {verdict}")
    print(f"    n_events={n_events} n_dates={n_dates} BHAR_gross={bhar_gross}% net={bhar_net}%")
    print(f"    (Bonferroni×{CROSS_STRATEGY_N}, walk-forward, DSR/PBO 均不可运行——无 picks)")

    print(f"\n{'=' * 72}")
    print(f"[FINAL SUMMARY] {STRATEGY}")
    print(f"{'=' * 72}")
    print(f"策略: {STRATEGY}")
    print(f"定义: {FILTER_DEF}")
    print(f"verdict: {verdict}")
    print(f"n_events={n_events}, n_dates={n_dates}")
    print(f"BHAR gross={bhar_gross}%, net={bhar_net}%")
    print(f"\n诚实约束:")
    print(f"  - 测的是 announcement→effective 真 Shleifer 窗口 (非 post-inclusion 漂移)")
    print(f"  - BHAR 非 raw EV (除权除息教训: raw EV 含市场 beta)")
    print(f"  - announcement 日=策略结构性前提, 无它无法测; 不臆造窗口/不偷换 effective 口径")
    print(f"  - 即使数据可得, 半年 rebalance 8 年~16 事件日 < 60 → 结构性 underpowered")
    print(f"禁止外推: 单事件策略 no-data ≠ 事件驱动有/无 edge ≠ 短线有/无 edge.")
    print(f"          本 no-data 仅指 announcement→effective 窗口未测(数据不可得), 非该窗口无 edge.")


if __name__ == "__main__":
    main()
