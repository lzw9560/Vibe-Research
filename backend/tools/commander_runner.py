# -*- coding: utf-8 -*-
"""commander_runner —— 情绪指挥官主 runner。

串联：情绪诊断(fetch_market_sentiment_metrics) + 仓位分配(calculate_position_allocation) + 飞书推送。

定时调用：
- 09:15 开盘前诊断（scheduled_tasks cron）
- 15:00 盘后复盘

输出：情绪得分 + 状态 + 仓位建议 + 风控 + 各战法 verdict（R30 诚实标注）。
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_market_sentiment_metrics import diagnose
from calculate_position_allocation import allocate

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"
INST_KEYWORDS = (
    "机构专用", "总部", "高盛", "瑞银", "股通", "摩根",
    "中信证券股份有限公司上海分公司", "国际金融",
)


def load_inst_dominant_today(mode: str = "basic") -> list[dict]:
    """当日 LHB 机构资金延续组合候选（inst_dominant combo, S236）。

    mode:
      - "basic": 机构占比>80% + top6 按机构金额（基础版，回测 mean+0.457% WR54.9% 8年1710日）
      - "advanced": basic + 当日涨(change_rate>=0) + 外资>30% + 中价20-100（进阶版 mean+0.879% WR56.0%,
        post-hoc 须60天§44 R3复验，复验前weight=0.5不重仓）
    返回 top6 [{code, inst_net_pct, ibuy, change_rate, close_price, foreign_pct}] 按机构金额降序。
    """
    import sqlite3  # noqa: PLC0415
    from collections import defaultdict  # noqa: PLC0415
    foreign_kw = ("高盛", "瑞银", "股通", "摩根", "国际金融", "总部")
    conn = sqlite3.connect(str(DT_DB))
    latest = conn.execute("SELECT MAX(trade_date) FROM dragon_tiger_rows").fetchone()[0]
    if not latest:
        conn.close()
        return []
    rows = conn.execute(
        "SELECT security_code, dept_name, buy, change_rate, close_price "
        "FROM dragon_tiger_rows WHERE trade_date=? AND side='buy' AND buy>0",
        (latest,),
    ).fetchall()
    conn.close()
    by_code: dict = defaultdict(list)
    for code, dept, buy, chg, cp in rows:
        by_code[code].append((dept or "", buy or 0, chg, cp))
    candidates: list[dict] = []
    for code, seats in by_code.items():
        total = sum(s[1] for s in seats)
        if total <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        inst_pct = inst_buy / total
        if inst_pct <= 0.8:  # >80% 纯化
            continue
        chg = seats[0][2]
        cp = seats[0][3]
        if chg is None or not cp:
            continue
        foreign_buy = sum(s[1] for s in seats if any(k in s[0] for k in foreign_kw))
        foreign_pct = foreign_buy / total
        if mode == "advanced":
            if chg < 0:  # 当日涨(追高/延续，证否抄底)
                continue
            if foreign_pct <= 0.3:  # 外资主导
                continue
            if not (20 <= cp <= 100):  # 中价20-100，避开高价买不满1手
                continue
        candidates.append({
            "code": code,
            "inst_net_pct": round(inst_pct * 100, 1),
            "ibuy": inst_buy,
            "change_rate": round(chg, 2),
            "close_price": cp,
            "foreign_pct": round(foreign_pct * 100, 1),
        })
    candidates.sort(key=lambda x: x["ibuy"], reverse=True)
    if mode == "filtered":
        # v10.5：用tail_dip_engine完整财务红线替换fundamental_filter单一应收过滤
        # 覆盖：商誉>=15% + 应收>=40% + 现金流为负 + 减持 + 数据缺失安全补丁
        from strategies.tail_dip_engine import fetch_financial_substitute_factors, HARD_THRESHOLDS  # noqa: PLC0415
        top12 = candidates[:12]
        passed = []
        for c in top12:
            factors = fetch_financial_substitute_factors(c["code"])
            gw = factors.get("goodwill_ratio")
            gw_blk = factors.get("goodwill_blocked", False)
            ar = factors.get("ar_to_revenue_pct")
            cf_neg = factors.get("cf_negative", False)
            reduction = factors.get("has_reduction_recent", False)
            blocked = (
                (gw_blk and gw is not None)
                or (ar and ar >= 40)
                or cf_neg
                or reduction
                or (not factors)
            )
            if not blocked:
                passed.append(c)
        return passed[:6]
    return candidates[:6]


def load_a_group_today(mode: str = "basic") -> list[dict]:
    """当日 A组 picks（涨幅-3%~+10% + 净买<0.5亿 + 净买>0，T+2 买 T+10 卖 watchlist）。

    A组 T+10 walk-forward OOS edge-confirmed（train+0.912%/test+1.094% 都 PASS）。
    mode:
      - "basic": top5 按净买（watchlist）
      - "combo": top5 跳北交所(920)数据缺，等权组合 nostop（S237，mean+0.989% WR53.6%）
        注：非920但hithink不识的（如部分301xxx）需实盘查K线发现跳过
    返回 [{code, chg, net_buy_wan}] 按净买降序 top5。
    """
    import sqlite3  # noqa: PLC0415
    conn = sqlite3.connect(str(DT_DB))
    latest = conn.execute("SELECT MAX(trade_date) FROM dragon_tiger_rows").fetchone()[0]
    if not latest:
        conn.close()
        return []
    rows = conn.execute(
        "SELECT security_code, SUM(net) as total_net, MAX(change_rate) as chg "
        "FROM dragon_tiger_rows WHERE trade_date=? AND side='buy' AND net IS NOT NULL "
        "GROUP BY trade_date, security_code",
        (latest,),
    ).fetchall()
    conn.close()
    signals: list[dict] = []
    for code, total_net, chg in rows:
        if total_net is None or chg is None:
            continue
        if not (-3 <= chg <= 10):
            continue
        if total_net <= 0:
            continue
        if total_net > 5e7:  # 净买<0.5亿 = <5e7 元
            continue
        if mode in ("combo", "filtered") and code.startswith("920"):  # 北交所 hithink/baostock 不识，跳
            continue
        signals.append({"code": code, "chg": round(chg, 2), "net_buy_wan": round(total_net / 1e4, 1)})
    signals = sorted(signals, key=lambda x: x["net_buy_wan"], reverse=True)
    if mode == "filtered":
        # v10.5：A组T+10也加完整财务红线过滤（同inst_dominant逻辑）
        from strategies.tail_dip_engine import fetch_financial_substitute_factors  # noqa: PLC0415
        top10 = signals[:10]
        passed = []
        for c in top10:
            factors = fetch_financial_substitute_factors(c["code"])
            gw = factors.get("goodwill_ratio")
            gw_blk = factors.get("goodwill_blocked", False)
            ar = factors.get("ar_to_revenue_pct")
            cf_neg = factors.get("cf_negative", False)
            reduction = factors.get("has_reduction_recent", False)
            blocked = (
                (gw_blk and gw is not None)
                or (ar and ar >= 40)
                or cf_neg
                or reduction
                or (not factors)
            )
            if not blocked:
                passed.append(c)
        return passed[:5]
    return signals[:5]


def run() -> dict:
    """主流程：诊断情绪 → 分配仓位 → 沸点期排雷 → 返回结构化结果。"""
    sentiment = diagnose()
    position = allocate(sentiment.score)
    r = {
        "trade_date": sentiment.trade_date,
        "score": sentiment.score,
        "state": sentiment.state,
        "position": {
            "long_pct": position.long_pct,
            "mid_pct": position.mid_pct,
            "short_pct": position.short_pct,
        },
        "stop_loss_rule": position.stop_loss_rule,
        "details": sentiment.details,
        "reasons": sentiment.reasons,
        "verdicts": position.verdicts,
    }
    # 沸点期（score>70）启动排雷过滤器（S234）——对当日涨停前 5 只跑排雷
    # 常态/冰点期不触发（红利低波/中线，不追打板）
    if sentiment.score > 70:
        try:
            from short_term_tactics_filter import filter_stock, to_json  # noqa: PLC0415
            from fetch_market_sentiment_metrics import load_latest_zt  # noqa: PLC0415
            zt = load_latest_zt()
            tactics_results = []
            for row in zt["rows"][:5]:
                code = str(row[0] or "")
                if not code:
                    continue
                # row: (code, lbc, zbc, fbt)
                fr = filter_stock(code, "战法1_弱转强", zt={"fbt": row[3], "lbc": row[1]})
                tactics_results.append(to_json(fr))
            r["tactics_filter_results"] = tactics_results
        except Exception as e:
            r["tactics_filter_error"] = f"沸点期排雷失败: {e}"
    # inst_dominant edge-confirmed signal（独立信号，不限情绪状态——LHB 上榜股跨 regime 稳健）
    try:
        signals = load_inst_dominant_today()
        if signals:
            r["inst_dominant_signals"] = signals[:10]
    except Exception as e:
        r["inst_dominant_error"] = f"机构主导信号失败: {e}"
    # A组 T+10 edge-confirmed watchlist（独立信号，T+2 买 T+10 卖，-10%stop stop_rate 21.6%；R6 -3%stop FAIL p=0.1118 改 -10%；2025-2026 regime FAIL p=0.155 衰减待复验）
    try:
        a_signals = load_a_group_today()
        if a_signals:
            r["a_group_t10_signals"] = a_signals[:10]
    except Exception as e:
        r["a_group_error"] = f"A组 T+10 信号失败: {e}"
    return r


def format_text(r: dict) -> str:
    """格式化为飞书推送文本（人话，不堆术语）。"""
    lines = [
        f"📊 情绪指挥官 {r['trade_date']}",
        f"",
        f"情绪水位: {r['score']}/100 → {r['state']}",
        f"仓位建议 (长/中/短): {r['position']['long_pct']}/{r['position']['mid_pct']}/{r['position']['short_pct']}",
        f"风控: {r['stop_loss_rule']}",
        f"",
        f"得分拆解:",
    ]
    for reason in r["reasons"]:
        lines.append(f"  • {reason}")
    lines.append("")
    lines.append("战法历史 verdict（诚实标注）:")
    for k, v in r["verdicts"].items():
        lines.append(f"  • {k}: {v}")
    # 沸点期排雷结果（S234）
    if r.get("tactics_filter_results"):
        lines.append("")
        lines.append(f"🔥 沸点期排雷（前 {len(r['tactics_filter_results'])} 只涨停候选）:")
        for tr in r["tactics_filter_results"]:
            lines.append(f"  • {tr['name']}({tr['code']}): {tr['safe_action']} risk={tr['risk_level']}")
    elif r.get("tactics_filter_error"):
        lines.append(f"\n⚠️ {r['tactics_filter_error']}")
    # inst_dominant edge-confirmed signal（独立信号，观察池非买入——lottery median 负 WR<50%）
    if r.get("inst_dominant_signals"):
        lines.append("")
        lines.append(f"🏆 机构主导 LHB（edge-confirmed walk-forward OOS，top {len(r['inst_dominant_signals'])}，-8%stop mean+0.336% stop_rate 2.5%，2025-2026增强，观察池非买入）:")
        for s in r["inst_dominant_signals"]:
            lines.append(f"  • {s['code']}: 机构占比 {s['inst_net_pct']}%")
    elif r.get("inst_dominant_error"):
        lines.append(f"\n⚠️ {r['inst_dominant_error']}")
    # A组 T+10 edge-confirmed watchlist（T+2 买 T+10 卖，-10%stop stop_rate 21.6%）
    if r.get("a_group_t10_signals"):
        lines.append("")
        lines.append(f"📈 A组 T+10 watchlist（edge 2018-2024 都PASS，2025-2026 衰减待复验，top {len(r['a_group_t10_signals'])}，T+2买T+10卖，-10%stop stop_rate 21.6%）:")
        for s in r["a_group_t10_signals"]:
            lines.append(f"  • {s['code']}: 涨幅{s['chg']}% 净买{s['net_buy_wan']}万")
    elif r.get("a_group_error"):
        lines.append(f"\n⚠️ {r['a_group_error']}")
    return "\n".join(lines)


def push_feishu(text: str) -> None:
    """飞书推送（失败不阻塞主流程）。push_text 是 async，用 asyncio.run 驱动。"""
    try:
        import asyncio
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from feishu_notifier import FeishuNotifier
        notifier = FeishuNotifier()
        asyncio.run(notifier.push_text(text, ticker="sentiment_commander"))
        print("\n[feishu] ✅ pushed")
    except Exception as e:
        print(f"\n[feishu] ⚠️ skip: {e}")


def main() -> None:
    r = run()
    text = format_text(r)
    print(text)
    push_feishu(text)


if __name__ == "__main__":
    main()
