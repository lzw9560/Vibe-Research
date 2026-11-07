# -*- coding: utf-8 -*-
"""卡片构建层 — 所有 build_*_card 函数。

从 feishu_daily_push.py 拆出。不改飞书卡片格式，只搬迁代码位置。
卡片格式与原版完全一致（orchestrator 要求）。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

from .data import (
    get_index_snapshot,
    get_hot_stocks,
    get_dragon_tiger,
    get_limit_up_ladder,
    get_skyrocket,
    scan_group_a_stocks,
    check_buy_signals,
)
from .sentiment import calculate_sentiment_score

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def build_premarket_card() -> dict:
    """盘前推送卡片。"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    indices = get_index_snapshot()
    hot = get_hot_stocks()
    dragon = get_dragon_tiger()

    elements = []

    # 指数概览
    if indices:
        idx_text = "**📈 指数快照**\n"
        for idx in indices:
            chg = idx.get("price_change_ratio_pct", 0)
            emoji = "🔴" if chg < 0 else "🟢"
            idx_text += f"{emoji} {idx['thscode'][:6]} {idx['last_price']:.1f} {chg:+.2f}%\n"
        elements.append({"tag": "markdown", "content": idx_text.strip()})

    # 热股榜TOP10
    if hot:
        hot_text = "\n**🔥 热股榜TOP10**\n"
        for h in hot[:10]:
            trend = {"up": "⬆️", "down": "⬇️", "flat": "➡️"}.get(h.get("rank_trend", ""), "")
            hot_text += f"{h['rank']:>2}. {h['name']}({h['thscode'][:6]}) {trend}\n"
        elements.append({"tag": "markdown", "content": hot_text.strip()})

    # 龙虎榜净买入TOP5
    if dragon:
        dt_text = "\n**💰 龙虎榜净买入TOP5**\n"
        for d in dragon[:5]:
            nm = d.get("net_value", 0)
            if nm:
                dt_text += f"• {d['name']}({d['thscode'][:6]}) 净买:{nm/1e8:+.2f}亿\n"
        elements.append({"tag": "markdown", "content": dt_text.strip()})

    # v5.00：回撤断路器诊断+peak衰减建议
    try:
        backend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)

        # v11：RSI择时信号——最强统计显著alpha
        try:
            import urllib.request as _urllib2
            with _urllib2.urlopen(_urllib2.Request("http://127.0.0.1:8900/api/strategy/rsi-timing/signal"), timeout=10) as _r2:
                _rsi_data = json.loads(_r2.read())
                if _rsi_data.get("any_triggered"):
                    rsi_text = "\n**🚨 RSI择时信号触发**\n"
                    for _s in _rsi_data.get("signals", []):
                        _emoji = "✅" if _s["is_triggered"] else "❌"
                        rsi_text += f"{_emoji} {_s['index_name']} RSI={_s['current_rsi']} 阈值<{_s['threshold']}\n"
                        if _s["is_triggered"]:
                            rsi_text += f"  历史: n={_s['sample_size']} mean+{_s['expected_return']}% WR{_s['win_rate']}% p={_s['p_value']}\n"
                            rsi_text += f"  操作: 买ETF持{_s['hold_days']}天 止损{_s['stop_loss_pct']:.0%}\n"
                    elements.append({"tag": "markdown", "content": rsi_text.strip()})
        except Exception:
            pass

        from backend.strategies.tail_dip_engine import diagnose_drawdown_lock, propose_peak_decay

        # 从API拉回撤状态
        import urllib.request as _urllib
        try:
            with _urllib.urlopen(_urllib.Request("http://127.0.0.1:8900/api/journal/drawdown-status"), timeout=5) as _r:
                _dd = json.loads(_r.read())
                _port = _dd.get("portfolio", {})
                _eq = float(_port.get("equity", 0))
                _pk = float(_port.get("peak", 0))
                _dd_pct = float(_port.get("drawdown_pct", 0))
                _days = int(_port.get("days_tracked", 0))
                _sm = float(_port.get("size_multiplier", 0))

                dd_text = f"\n**🛡️ 回撤断路器状态**\n"
                dd_text += f"权益: {_eq:.0f}  峰值: {_pk:.0f}  回撤: {_dd_pct:.1f}%  size_mult: {_sm}\n"

                # 诊断
                diag = diagnose_drawdown_lock(_eq, _pk, 100000.0, _days)
                if diag.is_permanently_locked:
                    dd_text += f"⚠️ 永久锁定：{diag.diagnosis}\n"

                    # peak衰减方案
                    proposal = propose_peak_decay(_eq, _pk, 100000.0, _days)
                    if proposal:
                        dd_text += f"\n**🔧 peak衰减方案**\n"
                        dd_text += f"当前peak={proposal.current_peak:.0f} → 衰减后={proposal.proposed_peak:.0f}（×{proposal.decay_factor}）\n"
                        dd_text += f"触发: {proposal.trigger_reason}\n"
                        dd_text += f"{proposal.recommendation}\n"
                        dd_text += f"⚠️ 需人工确认后实施（不自主修改风控核心逻辑）\n"
                elements.append({"tag": "markdown", "content": dd_text.strip()})
        except Exception:
            pass  # API不可用时不阻塞推送
    except ImportError:
        pass  # 引擎不可用时降级

    elements.append({
        "tag": "note",
        "content": "⚠️ 以上为盘前数据快照，不构成投资建议。策略信号需盘中实时确认。"
    })

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 盘前推送 {now}"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_intraday_card() -> dict:
    """盘中尾盘扫描卡片——RSI+MACD择时信号。

    策略4尾盘错杀已归档（2026-10-17 walk-forward证伪）。
    替换为RSI择时信号（p=0.0002 mean+7.82% WR92% 夏普1.13）。
    """
    now = datetime.now(CST)
    now_str = now.strftime("%H:%M")

    elements = []

    # RSI+MACD择时信号
    try:
        import urllib.request as _urllib
        with _urllib.urlopen(_urllib.Request("http://127.0.0.1:8900/api/strategy/rsi-macd/signal"), timeout=10) as _r:
            _rsi_data = json.loads(_r.read())

            buy_count = _rsi_data.get("buy_count", 0)
            wait_count = _rsi_data.get("wait_count", 0)
            signals = _rsi_data.get("signals", [])

            if buy_count > 0:
                text = f"**🚨 RSI+MACD金叉确认——买入信号（{now_str}）**\n\n"
                for s in signals:
                    if s.get("combo_signal") == "买入":
                        text += f"✅ {s['index_name']} RSI={s['rsi']} MACD金叉\n"
                        text += f"  预期+{s['expected_60d']}% WR{s['win_rate_60d']}% 持60天\n"
                text += "\n**操作：买ETF 100%仓位 持60天 RSI>60退出 不止损**\n"
            elif wait_count > 0:
                text = f"**⏳ RSI已触发 MACD未金叉——等待确认（{now_str}）**\n\n"
                for s in signals:
                    text += f"⏳ {s['index_name']} RSI={s['rsi']} MACD死叉(DIF={s['macd_dif']} DEA={s['macd_dea']})\n"
                text += "\n等MACD金叉后是更强买入时机(WR100% mean+9.53%)\n"
                text += "激进者可直接买(RSI极端超卖) 预期+7.82% WR92%\n"
            else:
                text = f"**{now_str} 无RSI信号**\nRSI未触发买入区间\n"

            elements.append({"tag": "markdown", "content": text.strip()})
    except Exception:
        elements.append({"tag": "markdown", "content": f"**{now_str} RSI信号拉取失败**"})

    elements.append({
        "tag": "note",
        "content": "⚠️ RSI择时 p=0.0002 mean+7.82% WR92% 夏普1.13>持有0.48。不构成投资建议。"
    })

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"🔔 尾盘信号（已归档）{now}"},
            "template": "grey",
        },
        "elements": elements,
    }


def build_postmarket_card() -> dict:
    """盘后复盘卡片。"""
    now = datetime.now(CST).strftime("%Y-%m-%d")

    indices = get_index_snapshot()
    hot = get_hot_stocks()
    dragon = get_dragon_tiger()
    ladder = get_limit_up_ladder()
    skyrocket = get_skyrocket()

    elements = []

    # 指数收盘
    if indices:
        text = "**📈 收盘指数**\n"
        for idx in indices:
            chg = idx.get("price_change_ratio_pct", 0)
            vol = idx.get("turnover", 0) / 1e8
            emoji = "🔴" if chg < 0 else "🟢"
            text += f"{emoji} {idx['thscode'][:6]} {idx['last_price']:.1f} {chg:+.2f}% 成交:{vol:.0f}亿\n"
        elements.append({"tag": "markdown", "content": text.strip()})

    # 连板梯队
    if ladder:
        latest = ladder[0] if ladder else {}
        boards = latest.get("boards", {})
        text = "\n**🏗️ 连板梯队**\n"
        for level_name, label in [
            ("seven_over", "7板+"), ("six_board", "6板"), ("five_board", "5板"),
            ("four_board", "4板"), ("three_board", "3板"), ("two_board", "2板"),
        ]:
            stocks = boards.get(level_name, [])
            if stocks:
                names = " ".join(f"{s['name']}({s['board_num']}板)" for s in stocks)
                text += f"{label}: {names}\n"
        elements.append({"tag": "markdown", "content": text.strip()})

    # 热股榜
    if hot:
        text = "\n**🔥 热股榜TOP10**\n"
        for h in hot[:10]:
            text += f"{h['rank']:>2}. {h['name']}({h['thscode'][:6]})\n"
        elements.append({"tag": "markdown", "content": text.strip()})

    # 龙虎榜
    if dragon:
        text = "\n**💰 龙虎榜净买入TOP5**\n"
        for d in dragon[:5]:
            nm = d.get("net_value", 0)
            if nm:
                concepts = ",".join(c["name"] for c in d.get("concept_list", [])[:2])
                text += f"• {d['name']} +{nm/1e8:.2f}亿 [{concepts}]\n"
        elements.append({"tag": "markdown", "content": text.strip()})

    # 策略1（窒息量反转）已证伪归档——不再推候选
    elements.append({
        "tag": "markdown",
        "content": (
            "\n**🎯 策略1·窒息量反转 已归档（2026-10-17）**\n"
            "该信号证伪：t1_open -8.188%（接飞刀死亡信号非反转），低吸类别结构性无edge。"
            "不再推送候选。证据：memory suffocation-reversal-falsified-2026-10-08"
        ),
    })

    elements.append({
        "tag": "note",
        "content": "⚠️ 以上为历史统计特征，不代表未来行为。仅作研究参考，不构成投资建议。"
    })

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 盘后复盘 {now}"},
            "template": "green",
        },
        "elements": elements,
    }


def build_test_card() -> dict:
    """测试卡片。"""
    return {
        "header": {
            "title": {"tag": "plain_text", "content": "🤖 飞书Bot连接测试"},
            "template": "green",
        },
        "elements": [
            {"tag": "markdown", "content": "**连接成功** ✅\n\n飞书Bot推送服务已就绪。\n\n**可用命令：**\n• `--mode premarket` 盘前推送\n• `--mode intraday` 尾盘扫描\n• `--mode postmarket` 盘后复盘\n• `--mode test` 测试连接"},
            {"tag": "note", "content": "Vibe-Research × hithink-finance CLI"},
        ],
    }


def build_alert_card(signals: list) -> dict:
    """构建买入信号推送卡片。"""
    now = datetime.now(CST).strftime("%H:%M")
    elements = []

    if not signals:
        elements.append({"tag": "markdown", "content": f"**{now} 暂无触发买入信号的标的**\n\n监控中，信号触发即推送。"})
    else:
        for s in signals:
            color = "🟢" if s["signal"] == "买入" else "🟡" if s["signal"] == "观望" else "🔴"
            text = f"**{color} {s['name']}({s['code'][:6]}) — {s['signal']}**\n\n"
            text += f"现价: {s['price']:.2f}\n"
            text += f"5日均线: {s['ma5']:.2f}\n"
            text += f"今日涨跌: {s['chg_pct']:+.2f}%\n"
            text += f"成交额: {s['turnover']/1e8:.1f}亿\n\n"
            text += f"**买入理由**: {s['reason']}\n"
            text += f"**买入条件**: {s['buy_condition']}\n"
            text += f"**触发状态**: {s['trigger_detail']}\n\n"
            if s["signal"] == "买入":
                text += f"⏹️ 止损: {s['stop_loss_pct']}%\n"
                text += f"🎯 目标: +{s['target_pct']}%\n"
                text += f"📊 仓位: 短线资金的{s['weight']}%\n"
            elements.append({"tag": "markdown", "content": text})
            elements.append({"tag": "hr"})

    elements.append({"tag": "note", "content": "⚠️ 信号基于龙虎榜主力行为分析，不构成投资建议。严格执行止损。"})

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"🔔 买入信号监控 {now}"},
            "template": "red" if signals else "grey",
        },
        "elements": elements,
    }


def build_alert_card_live() -> dict:
    """实时检查信号并构建卡片。"""
    signals = check_buy_signals()
    return build_alert_card(signals)


def build_scan_card() -> dict:
    """构建A组跟庄筛选推送卡片。"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    a_group = scan_group_a_stocks()

    elements = []

    if a_group:
        text = f"**🎯 A组跟庄筛选（{now}）**\n\n"
        text += "基于3个月304只标的回测验证：\n"
        text += "A组特征（涨幅-3%~+10%+净买<0.5亿+热度>100）\n"
        text += "T+2追买胜率59%，平均收益+5.3%\n\n"
        for s in a_group:
            text += f"⭐ {s['name']}({s['code'][:6]})\n"
            text += f"  涨跌:{s['chg']:+.1f}% 净买:{s['net']:.2f}亿 热度:{s['hot_rank']}\n"
            text += f"  概念:{s['concepts']}\n"
            text += f"  操作:T+2分2笔买入 止损-15% 止盈+20%\n\n"
        elements.append({"tag": "markdown", "content": text.strip()})
    else:
        elements.append({"tag": "markdown", "content": f"**{now} A组筛选：今日无符合条件的标的**\n\nB组陷阱特征（不碰）：涨停+净买>0.5亿+热度<100"})

    elements.append({"tag": "note", "content": "⚠️ 基于历史统计特征(胜率59%)，不代表未来行为。仅作研究参考，不构成投资建议。"})

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"🎯 A组跟庄筛选 {now}"},
            "template": "green" if a_group else "grey",
        },
        "elements": elements,
    }


def build_sentiment_card() -> dict:
    """构建情绪指挥官推送卡片。"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    s = calculate_sentiment_score()

    elements = []

    # 情绪诊断
    text = f"**{s['state']} 情绪得分：{s['score']}/100**\n\n"
    text += f"📊 分项得分：\n"
    text += f"  量能({s['vol_score']}/25) 赚钱效应({s['effect_score']}/25) 连板({s['ladder_score']}/22) 资金({s['flow_score']}/13)\n\n"
    text += f"📈 市场数据：\n"
    text += f"  两市成交：{s['total_turnover_yi']:.0f}亿\n"
    text += f"  涨跌家数：{s['up_count']}涨 / {s['down_count']}跌\n"
    text += f"  涨停/跌停：{s['limit_up']} / {s['limit_down']}\n"
    text += f"  最高连板：{s['max_boards']}板\n"
    elements.append({"tag": "markdown", "content": text.strip()})

    elements.append({"tag": "hr"})

    # 仓位建议
    alloc = s["allocation"]
    text = f"**🎯 仓位分配**\n\n"
    text += f"  长线：{alloc['长线']}%\n"
    text += f"  中线：{alloc['中线']}%\n"
    text += f"  短线：{alloc['短线']}%\n\n"
    text += f"**战法：** {s['strategy']}"
    elements.append({"tag": "markdown", "content": text.strip()})

    elements.append({"tag": "hr"})

    # 问财指令
    text = f"**🔍 问财选股指令（可直接复制）**\n\n```\n{s['wencai']}\n```"
    elements.append({"tag": "markdown", "content": text.strip()})

    elements.append({"tag": "hr"})

    # 风控
    text = f"**🚨 风控红线**\n\n{s['risk']}"
    elements.append({"tag": "markdown", "content": text.strip()})

    template = "blue" if s["score"] <= 35 else "orange" if s["score"] <= 70 else "red"
    elements.append({"tag": "note", "content": "⚠️ 情绪评分基于量化指标，不构成投资建议。市场有风险，入市需谨慎。"})

    return {
        "header": {
            "title": {"tag": "plain_text", "content": f"{s['state']} 情绪指挥官 {now}"},
            "template": template,
        },
        "elements": elements,
    }
