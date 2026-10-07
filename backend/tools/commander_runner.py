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


def load_inst_dominant_today() -> list[dict]:
    """当日 LHB 机构主导上榜股（inst_dominant edge-confirmed signal）。

    inst_dominant walk-forward OOS edge-confirmed（8年25327 mean+0.390% p=0.0000 跨regime稳健）。
    查最新交易日 LHB，算机构+外资买占比>50%的上榜股。
    返回 [{code, inst_net_pct}] 按机构占比降序。
    """
    import sqlite3  # noqa: PLC0415
    from collections import defaultdict  # noqa: PLC0415
    conn = sqlite3.connect(str(DT_DB))
    latest = conn.execute("SELECT MAX(trade_date) FROM dragon_tiger_rows").fetchone()[0]
    if not latest:
        conn.close()
        return []
    rows = conn.execute(
        "SELECT security_code, dept_name, buy FROM dragon_tiger_rows "
        "WHERE trade_date=? AND side='buy' AND buy>0", (latest,)
    ).fetchall()
    conn.close()
    by_code: dict = defaultdict(list)
    for code, dept, buy in rows:
        by_code[code].append((dept or "", buy))
    signals: list[dict] = []
    for code, seats in by_code.items():
        total = sum(s[1] for s in seats)
        if total <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        if inst_buy / total > 0.5:
            signals.append({"code": code, "inst_net_pct": round(inst_buy / total * 100, 1)})
    return sorted(signals, key=lambda x: x["inst_net_pct"], reverse=True)


def load_a_group_today() -> list[dict]:
    """当日 A组 picks（涨幅-3%~+10% + 净买<0.5亿 + 净买>0，T+2 买 T+10 卖 watchlist）。

    A组 T+10 walk-forward OOS edge-confirmed（train+0.912%/test+1.094% 都 PASS）。
    查最新交易日 LHB，过滤 A组条件。
    返回 [{code, chg, net_buy_wan}] 按净买降序。
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
        signals.append({"code": code, "chg": round(chg, 2), "net_buy_wan": round(total_net / 1e4, 1)})
    return sorted(signals, key=lambda x: x["net_buy_wan"], reverse=True)


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
    # A组 T+10 edge-confirmed watchlist（独立信号，T+2 买 T+10 卖，lottery stop_rate 72.5%）
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
        lines.append(f"🏆 机构主导 LHB（edge-confirmed walk-forward OOS，top {len(r['inst_dominant_signals'])}，观察池非买入）:")
        for s in r["inst_dominant_signals"]:
            lines.append(f"  • {s['code']}: 机构占比 {s['inst_net_pct']}%")
    elif r.get("inst_dominant_error"):
        lines.append(f"\n⚠️ {r['inst_dominant_error']}")
    # A组 T+10 edge-confirmed watchlist（T+2 买 T+10 卖，lottery stop_rate 72.5%）
    if r.get("a_group_t10_signals"):
        lines.append("")
        lines.append(f"📈 A组 T+10 watchlist（edge-confirmed walk-forward OOS，top {len(r['a_group_t10_signals'])}，T+2买T+10卖，lottery stop_rate 72.5%）:")
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
