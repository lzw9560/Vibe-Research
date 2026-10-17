#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日短线标的推送 → 飞书Bot

用法:
  # 盘前推送（8:30）：昨日复盘 + 今日候选
  python3 feishu_daily_push.py --mode premarket

  # 尾盘扫描（14:30）：策略4尾盘错杀信号
  python3 feishu_daily_push.py --mode intraday

  # 盘后复盘（15:30）：今日龙虎榜+热股榜+明日候选
  python3 feishu_daily_push.py --mode postmarket

  # 手动测试
  python3 feishu_daily_push.py --mode test

依赖: hithink-finance CLI + 飞书Webhook
配置: 从 .env 读取 FEISHU_WEBHOOK_URL
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 加载.env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

WEBHOOK = os.getenv("FEISHU_WEBHOOK_URL", "")
if not WEBHOOK:
    print("ERROR: FEISHU_WEBHOOK_URL not set in .env")
    sys.exit(1)

CST = timezone(timedelta(hours=8))

# ─── 交易日历 ───
CALENDAR_CACHE = Path("/tmp/trade_calendar.json")
CALENDAR_DATES: set[str] | None = None


def refresh_trade_calendar() -> None:
    """刷新交易日历缓存（每年9月到期，提前刷新）。"""
    subprocess.run(
        "hithink-finance market calendar "
        "--output /tmp/trade_calendar.json --format json 2>/dev/null",
        shell=True, capture_output=True, timeout=30,
    )


def load_trade_calendar() -> set[str]:
    """加载交易日历，返回 'YYYYMMDD' 集合。缓存过期自动刷新。"""
    global CALENDAR_DATES
    if CALENDAR_DATES is not None:
        return CALENDAR_DATES

    # 缓存文件不存在或超过30天则刷新
    need_refresh = False
    if not CALENDAR_CACHE.exists():
        need_refresh = True
    else:
        import time
        age = time.time() - CALENDAR_CACHE.stat().st_mtime
        if age > 30 * 86400:
            need_refresh = True

    if need_refresh:
        refresh_trade_calendar()

    if not CALENDAR_CACHE.exists():
        CALENDAR_DATES = set()
        return CALENDAR_DATES

    with open(CALENDAR_CACHE) as f:
        d = json.load(f)
    items = d.get("data", {}).get("item", [])
    if not items:
        items = d.get("item", [])
    CALENDAR_DATES = set(it["date"] for it in items)
    return CALENDAR_DATES


# 已知节假日（日历未覆盖时的降级）
_KNOWN_HOLIDAYS = {
    # 2026年国庆中秋
    "20261001", "20261002", "20261003", "20261004",
    "20261005", "20261006", "20261007",
    # 2026年元旦（预估）
    "20260101", "20260102", "20260103",
    # 2026年春节（预估2月中）
    "20260215", "20260216", "20260217", "20260218",
    "20260219", "20260220", "20260221",
    # 2026年清明（预估4月初）
    "20260404", "20260405", "20260406",
    # 2026年五一（预估）
    "20260501", "20260502", "20260503",
    # 2026年端午（预估6月中）
    "20260619", "20260620", "20260621",
    # 2026年中秋（预估9月中）
    "20260914", "20260915", "20260916",
}


def is_trading_day(dt: datetime) -> bool:
    """判断是否为A股交易日。

    优先用交易日历，日历不覆盖该日期时用周末+已知节假日降级。
    """
    dates = load_trade_calendar()
    date_str = dt.strftime("%Y%m%d")

    # 日历覆盖该日期 → 直接查
    if dates and (date_str in dates or any(d > date_str for d in dates)):
        return date_str in dates

    # 日历不覆盖（日期在日历范围之外）→ 降级判断
    # 1. 周末不是交易日
    if dt.weekday() >= 5:
        return False
    # 2. 已知节假日不是交易日
    if date_str in _KNOWN_HOLIDAYS:
        return False
    # 3. 其他工作日视为交易日
    return True


def run_cli(cmd: str) -> dict | None:
    """运行 hithink-finance CLI 并返回 JSON。"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        # 取最后一行JSON（可能有stderr提示混入）
        lines = result.stdout.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        return None
    except Exception:
        return None


def send_feishu(card: dict) -> bool:
    """发送飞书卡片消息。"""
    import urllib.request

    payload = json.dumps({"msg_type": "interactive", "card": card}).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("code") == 0 or result.get("StatusCode") == 0
    except Exception as e:
        print(f"发送失败: {e}")
        return False


def get_index_snapshot() -> list:
    """获取主要指数快照。"""
    d = run_cli(
        "hithink-finance index snapshot "
        "--thscodes 000001.SH,399001.SZ,399006.SZ,000300.SH,000016.SH,000905.SH "
        "--format json 2>/dev/null"
    )
    if not d or not d.get("ok"):
        return []
    return d.get("data", {}).get("item", [])


def get_hot_stocks() -> list:
    """获取热股榜。"""
    d = run_cli("hithink-finance special hot-stock --period day --format json 2>/dev/null")
    if not d or not d.get("ok"):
        return []
    return d.get("data", {}).get("item", [])[:20]


def get_dragon_tiger() -> list:
    """获取龙虎榜。"""
    d = run_cli("hithink-finance special dragon-tiger --board-type all --format json 2>/dev/null")
    if not d or not d.get("ok"):
        return []
    items = d.get("data", {}).get("stock_items", [])
    items.sort(key=lambda x: x.get("net_value", 0) if x.get("net_value") else 0, reverse=True)
    return items[:15]


def get_limit_up_ladder() -> list:
    """获取连板天梯。"""
    d = run_cli("hithink-finance special limit-up-ladder --format json 2>/dev/null")
    if not d or not d.get("ok"):
        return []
    return d.get("data", {}).get("item", [])[:3]


def get_skyrocket() -> list:
    """获取飙升榜。"""
    d = run_cli("hithink-finance special skyrocket --period day --format json 2>/dev/null")
    if not d or not d.get("ok"):
        return []
    return d.get("data", {}).get("item", [])[:10]


def get_market_snapshot_all() -> list:
    """获取全市场快照。"""
    d = run_cli(
        "hithink-finance market snapshot --limit 5000 --output /tmp/snap_push.json --format json 2>/dev/null"
    )
    if not d or not d.get("ok"):
        return []
    with open("/tmp/snap_push.json") as f:
        data = json.load(f)
    return data.get("data", {}).get("item", [])


def scan_strategy1_suffocation() -> list:
    """策略1：窒息量反转扫描 — 连跌+缩量。

    ⚠️ 2026-10-17 归档：窒息量低吸已证伪（t1_open -8.188% WR1.9%，接飞刀死亡信号非反转）。
    见 memory suffocation-reversal-falsified-2026-10-08。函数保留供复现，不再接入盘后推送买入候选。
    """
    all_stocks = get_market_snapshot_all()
    if not all_stocks:
        return []

    # 筛选当日跌幅>3%的候选
    candidates = []
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        turnover = s.get("turnover")
        price = s.get("last_price")
        if chg is None or turnover is None or price is None:
            continue
        if chg < -3 and turnover > 5000000 and 2 < price < 80:
            candidates.append(s)

    # 取跌幅最大的20只拉历史验证
    candidates.sort(key=lambda x: x["price_change_ratio_pct"])
    results = []
    for c in candidates[:20]:
        code = c["thscode"]
        start_ms = int((datetime.now(CST).timestamp() - 10 * 86400) * 1000)
        end_ms = int(datetime.now(CST).timestamp() * 1000)
        d = run_cli(
            f"hithink-finance market history --thscode {code} "
            f"--start-ms {start_ms} --end-ms {end_ms} "
            f"--output /tmp/hist_push_{code}.json --format json 2>/dev/null"
        )
        if not d or not d.get("ok"):
            continue
        try:
            with open(f"/tmp/hist_push_{code}.json") as f:
                hist = json.load(f)
            items = hist.get("data", {}).get("item", [])
            if len(items) < 3:
                continue
            recent = items[-5:]
            total_chg = sum(
                ((it["close_price"] - it["open_price"]) / it["open_price"]) * 100
                for it in recent
            )
            vols = [it["turnover"] for it in recent]
            avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else vols[0]
            latest_vol = vols[-1]
            vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1

            if total_chg < -10 and vol_ratio < 0.7:
                results.append({
                    "code": code,
                    "price": c["last_price"],
                    "chg_today": c["price_change_ratio_pct"],
                    "total_chg_5d": total_chg,
                    "vol_ratio": vol_ratio,
                    "turnover": latest_vol / 1e8,
                })
        except Exception:
            continue
    return results[:5]


def scan_strategy4_tail_drop() -> list:
    """策略4进化版：尾盘错杀承接扫描（集成 tail_dip_engine 多专家共识引擎）。

    ⚠️ 2026-10-17 归档：本信号经 8 年 walk-forward 证伪（见 build_intraday_card
    证伪通告）。函数保留供复现/参考，不再接入买入候选推送。

    v2.00 进化点：
    - calculate_anomalous_deviation：个股vs板块偏离度>=3%才算错杀（非绝对跌幅）
    - financial_red_line_shield：商誉/质押/连板高度硬红线过滤
    - 跌幅限定-3%~-5%甜区（回测最优，重跌是基本面恶化）
    - 止损-10%（误杀率仅9.8%，非旧版-5%的22%）
    - 周五自动升级安全门槛
    """
    all_stocks = get_market_snapshot_all()
    if not all_stocks:
        return []

    # 导入进化引擎
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
    try:
        from strategies.tail_dip_engine import (
            calculate_anomalous_deviation,
            financial_red_line_shield,
            HARD_THRESHOLDS,
        )
    except ImportError:
        # 引擎不可用时降级为原始口径（不阻塞推送）
        return _scan_strategy4_tail_drop_legacy(all_stocks)

    # 判断是否周五/周末前（收紧安全门槛）
    now = datetime.now(CST)
    is_weekend_eve = now.weekday() == 4  # Friday

    # v4.00：用全市场中位数涨跌幅替代深证成指近似（更抗极值）
    # 降级链：全市场中位数 → 深证成指 → 0
    valid_stocks = [s for s in all_stocks if s.get("price_change_ratio_pct") is not None]
    sector_change_pct = 0.0
    sector_source = "降级(无数据)"
    if valid_stocks:
        sorted_chgs = sorted(s["price_change_ratio_pct"] for s in valid_stocks)
        sector_change_pct = sorted_chgs[len(sorted_chgs) // 2]  # 中位数
        sector_source = f"全市场中位数(n={len(valid_stocks)})"
    else:
        indices = get_index_snapshot()
        if indices:
            for idx in indices:
                if "399001" in idx.get("thscode", ""):
                    sector_change_pct = idx.get("price_change_ratio_pct", 0.0)
                    sector_source = "深证成指(降级)"
                    break

    results = []
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        turnover = s.get("turnover")
        price = s.get("last_price")
        volume = s.get("volume")
        if chg is None or turnover is None or price is None:
            continue

        # ━━━ 基础筛选：跌幅-3%~-5%甜区 + 成交额>1000万 + 价格2-80 ━━━
        if chg > HARD_THRESHOLDS["min_drop_pct"]:  # > -3% 不算错杀
            continue
        if chg < HARD_THRESHOLDS["max_drop_pct"]:  # < -5% 重跌不接
            continue
        if turnover < HARD_THRESHOLDS["min_amount"]:
            continue
        if price < HARD_THRESHOLDS["min_price"] or price > 80:
            continue

        # ━━━ 错杀偏离度因子：个股跌 vs 板块涨跌 ━━━
        # 量能收缩比：用 vol_ratio 近似（CLI snapshot 有 vol_ratio 字段）
        vol_ratio_raw = s.get("vol_ratio", 1.0) or 1.0
        # vol_ratio 是量比（今日量/前5日均量），直接传入
        deviation = calculate_anomalous_deviation(
            code=s.get("thscode", ""),
            individual_change_pct=chg,
            sector_change_pct=sector_change_pct,
            volume_today=float(volume or 0),
            volume_ma5=float(volume or 0) / max(vol_ratio_raw, 0.01),  # 反推5日均量
        )

        if not deviation.is_anomalous:
            continue  # 非错杀（板块共跌）→ 跳过

        # ━━━ 财务红线防火墙（降级模式：无财务数据时跳过红线检查）━━━
        # 生产环境应接入akshare拉商誉/质押/应收数据
        # 这里用 limitup_boards 近似（从涨停池数据判断）
        redline = financial_red_line_shield(
            code=s.get("thscode", ""),
            name=s.get("name", ""),
            limitup_boards=0,  # 跌3%+的票不可能是连板，设0
            is_weekend_eve=is_weekend_eve,
        )
        if not redline.passed:
            continue  # 红线拦截

        results.append({
            "code": s.get("thscode", ""),
            "name": s.get("name", ""),
            "price": price,
            "chg": chg,
            "turnover": turnover / 1e8,
            "deviation": deviation.anomalous_deviation,
            "confidence": deviation.confidence,
            "detail": deviation.detail,
            "stop_loss": HARD_THRESHOLDS["max_stop_loss"],   # -10%
            "take_profit": HARD_THRESHOLDS["take_profit"],   # +10%
            "max_hold": HARD_THRESHOLDS["max_hold_days"] if not is_weekend_eve else 3,
            "is_weekend_eve": is_weekend_eve,
        })

    # 按偏离度降序（偏离越大越可能是错杀）
    results.sort(key=lambda x: x["deviation"], reverse=True)
    return results[:10]


def _scan_strategy4_tail_drop_legacy(all_stocks: list) -> list:
    """策略4原始口径降级版（tail_dip_engine 不可用时使用）。"""
    results = []
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        turnover = s.get("turnover")
        price = s.get("last_price")
        if chg is None or turnover is None or price is None:
            continue
        if chg < -3 and turnover > 10000000 and 2 < price < 80:
            results.append({
                "code": s["thscode"],
                "price": price,
                "chg": chg,
                "turnover": turnover / 1e8,
            })
    results.sort(key=lambda x: x["chg"])
    return results[:10]


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
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
        from strategies.tail_dip_engine import diagnose_drawdown_lock, propose_peak_decay

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
    """盘中尾盘扫描卡片。

    ⚠️ 2026-10-17 归档：策略4尾盘错杀低吸经 8 年 walk-forward 证伪
    （原报告样本内 -10% 档 +0.72% → 8 年复测 -0.039% FAIL；walk-forward
    train 负 / test 非显著 → NOT confirmed；R12 相对 alpha +0.36% 为 lottery
    中位负、不可长仓兑现）。不再推送候选，改为证伪通告。
    详见 strategy4_backtest_result.md §5 + memory tail-dip-falsified-2026-10-17。
    """
    now = datetime.now(CST)

    elements = [{
        "tag": "markdown",
        "content": (
            "**⚠️ 策略4·尾盘错杀已归档（2026-10-17）**\n\n"
            "该信号经 8 年 walk-forward 复测证伪：\n"
            "• 原样本内 -10% 档 +0.72% → 8 年复测 -0.039%（FAIL）\n"
            "• walk-forward OOS：train 负 / test 非显著 → NOT confirmed\n"
            "• R12 相对 alpha +0.36% 为 lottery（中位负、胜率<50%），不可长仓兑现\n\n"
            "不再推送候选。低吸类别结构性无 edge（与窒息量低吸证伪一致）。\n"
            "证据：strategy4_backtest_result.md §5 / 脚本 _audit_tail_dip_full.py"
        ),
    }]

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


# ─── A组跟庄筛选（基于3个月304只标的回测验证） ───
# A组特征：龙虎榜日涨幅-3%~+10% + 净买入<0.5亿 + 热度排名>100
# 回测结果：A组T+2追买胜率59%，平均收益+5.3%（vs随机-2.7%）
# B组陷阱：涨停+净买入大+热度高 → 胜率仅19%，收益-8.5%


def scan_group_a_stocks() -> list:
    """扫描龙虎榜，筛选A组特征标的（可跟庄）。
    
    A组特征（回测验证有效）：
    1. 当日涨幅 -3% ~ +10%（不是涨停/暴涨20%）
    2. 净买入 < 0.5亿（主力在建仓不是一把打完）
    3. 热度排名 > 100（不是最热的票，散户关注度低）
    4. 净买入为正
    """
    # 拉龙虎榜
    d = run_cli("hithink-finance special dragon-tiger --board-type all --format json 2>/dev/null")
    if not d or not d.get("ok"):
        return []
    
    items = d.get("data", {}).get("stock_items", [])
    
    a_group = []
    for it in items:
        net = it.get("net_value", 0) or 0
        if net <= 0:
            continue
        
        chg = it.get("change", 0) * 100  # 转百分比
        net_yi = net / 1e8  # 亿
        hot_rank = it.get("hot_rank", 999)
        
        # A组筛选条件
        cond1 = -3 <= chg <= 10  # 涨幅适中
        cond2 = net_yi < 0.5  # 净买入小
        cond3 = hot_rank > 100 or hot_rank == 999  # 热度低
        cond4 = net > 0  # 净买入为正
        
        if cond1 and cond2 and cond3 and cond4:
            concepts = ",".join(c["name"] for c in it.get("concept_list", [])[:3])
            a_group.append({
                "code": it.get("thscode", ""),
                "name": it.get("name", ""),
                "chg": chg,
                "net": net_yi,
                "hot_rank": hot_rank,
                "concepts": concepts,
                "reason": f"A组特征：涨幅{chg:+.1f}%+净买{net_yi:.2f}亿+热度{hot_rank}",
                "buy_condition": "T+2开盘分2笔买入",
                "stop_loss_pct": -15,
                "target_pct": 20,
                "weight": 20,
            })
    
    # 按净买入排序
    a_group.sort(key=lambda x: x["net"], reverse=True)
    return a_group[:5]  # 最多推5只


# ─── 监控标的池（动态生成+手动补充） ───
WATCH_LIST: list = []  # 不再硬编码，改为动态扫描


def get_watch_list() -> list:
    """获取监控标的列表：动态扫描A组标的。"""
    if WATCH_LIST:
        return WATCH_LIST
    return scan_group_a_stocks()


def get_realtime_price(codes: list[str]) -> dict:
    """批量获取实时价格。"""
    code_str = ",".join(codes)
    d = run_cli(
        f"hithink-finance market snapshot --thscodes {code_str} --format json 2>/dev/null"
    )
    if not d or not d.get("ok"):
        return {}
    items = d.get("data", {}).get("item", [])
    return {it["thscode"]: it for it in items}


def get_recent_klines(code: str, days: int = 30) -> list:
    """获取近N日K线（默认30天，确保至少5条用于MA5）。"""
    start_ms = int((datetime.now(CST).timestamp() - days * 86400) * 1000)
    end_ms = int(datetime.now(CST).timestamp() * 1000)
    fn = f"/tmp/alert_hist_{code}.json"
    d = run_cli(
        f"hithink-finance market history --thscode {code} "
        f"--start-ms {start_ms} --end-ms {end_ms} "
        f"--output {fn} --format json 2>/dev/null"
    )
    if not d or not d.get("ok"):
        return []
    try:
        with open(fn) as f:
            hist = json.load(f)
        # 兼容两种数据结构
        items = hist.get("data", {}).get("item", [])
        if not items:
            items = hist.get("item", [])
        return items
    except Exception:
        return []


def calc_ma5(klines: list) -> float | None:
    """计算5日均线。"""
    if len(klines) < 5:
        return None
    recent5 = klines[-5:]
    return sum(it["close_price"] for it in recent5) / 5


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


def check_buy_signals() -> list:
    """检查所有监控标的的买入信号。"""
    watch = get_watch_list()
    if not watch:
        return []
    codes = [w["code"] for w in watch]
    prices = get_realtime_price(codes)

    signals = []
    for w in watch:
        code = w["code"]
        rt = prices.get(code)
        if not rt:
            continue

        price = rt.get("last_price", 0)
        chg_pct = rt.get("price_change_ratio_pct", 0)
        turnover = rt.get("turnover", 0)
        open_price = rt.get("open_price", 0)
        prev_price = rt.get("prev_price", 0)

        klines = get_recent_klines(code, 30)
        ma5 = calc_ma5(klines) if klines else None

        signal = "观望"
        trigger_detail = ""

        if ma5 and price > 0:
            # 信号1：低开（开盘价<前收×0.99）→ 低位承接
            if open_price < prev_price * 0.99:
                signal = "买入"
                trigger_detail = f"低开{(prev_price-open_price)/prev_price*100:.1f}%，主力可能低吸"

            # 信号2：回踩5日线不破（价格在5日线±2%范围内）
            elif abs(price - ma5) / ma5 < 0.02 and chg_pct < 3:
                signal = "买入"
                trigger_detail = f"回踩5日线({ma5:.2f})，接近支撑位"

            # 信号3：高开3%以上不追
            elif open_price > prev_price * 1.03:
                signal = "观望"
                trigger_detail = f"高开{(open_price/prev_price-1)*100:.1f}%，不追高"

            # 信号4：放量站稳5日线
            elif price > ma5 and chg_pct > 0 and chg_pct < 3:
                signal = "买入"
                trigger_detail = f"站稳5日线({ma5:.2f})，温和上涨{chg_pct:+.1f}%"

            else:
                signal = "观望"
                trigger_detail = f"价格{price:.2f} vs 5日线{ma5:.2f}，未触发条件"
        else:
            signal = "观望"
            trigger_detail = "数据不足"

        signals.append({
            "code": code,
            "name": w["name"],
            "price": price,
            "ma5": ma5 or 0,
            "chg_pct": chg_pct,
            "turnover": turnover,
            "signal": signal,
            "trigger_detail": trigger_detail,
            "reason": w["reason"],
            "buy_condition": w["buy_condition"],
            "stop_loss_pct": w["stop_loss_pct"],
            "target_pct": w["target_pct"],
            "weight": w["weight"],
        })

    return signals


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


def calculate_sentiment_score() -> dict:
    """计算市场情绪得分（0-100）并返回状态+仓位建议。"""
    # 1. 量能指标（30%）
    indices = get_index_snapshot()
    vol_score = 15  # 默认
    total_turnover = 0
    if indices:
        for idx in indices:
            total_turnover += idx.get("turnover", 0)
        total_yi = total_turnover / 1e8
        if total_yi > 15000:
            vol_score = 25
        elif total_yi > 10000:
            vol_score = 20
        elif total_yi > 7000:
            vol_score = 15
        else:
            vol_score = 5  # 地量=冰点

    # 2. 涨跌家数（30%）
    all_stocks = get_market_snapshot_all()
    up_count = 0
    down_count = 0
    limit_up = 0
    limit_down = 0
    for s in all_stocks:
        chg = s.get("price_change_ratio_pct")
        if chg is None:
            continue
        if chg > 0:
            up_count += 1
        elif chg < 0:
            down_count += 1
        if chg >= 9.5:
            limit_up += 1
        if chg <= -9.5:
            limit_down += 1

    if up_count + down_count > 0:
        up_ratio = up_count / (up_count + down_count)
    else:
        up_ratio = 0.5

    if up_ratio > 0.75 and limit_down < 10:
        effect_score = 25
    elif up_ratio > 0.55:
        effect_score = 18
    elif up_ratio > 0.45:
        effect_score = 12
    else:
        effect_score = 5

    # 3. 连板梯队（25%）
    ladder = get_limit_up_ladder()
    ladder_score = 8  # 默认
    max_boards = 0
    if ladder:
        latest = ladder[0] if ladder else {}
        boards = latest.get("boards", {})
        for level in ["seven_over", "six_board", "five_board", "four_board", "three_board", "two_board"]:
            stocks = boards.get(level, [])
            if stocks:
                for s in stocks:
                    bn = s.get("board_num", 0)
                    if bn > max_boards:
                        max_boards = bn
        if max_boards >= 7:
            ladder_score = 22
        elif max_boards >= 5:
            ladder_score = 18
        elif max_boards >= 3:
            ladder_score = 12
        elif max_boards >= 2:
            ladder_score = 8
        else:
            ladder_score = 3

    # 4. 资金流向（15%）— 无北向数据，用龙虎榜净买入近似
    dragon = get_dragon_tiger()
    flow_score = 8  # 默认
    if dragon:
        total_net = sum(d.get("net_value", 0) or 0 for d in dragon[:10])
        if total_net > 5e8:
            flow_score = 13
        elif total_net > 0:
            flow_score = 8
        else:
            flow_score = 3

    # 综合得分
    total_score = vol_score + effect_score + ladder_score + flow_score

    # 状态判定
    if total_score <= 35:
        state = "🧊 冰点期"
        allocation = {"长线": 70, "中线": 20, "短线": 10}
        strategy = "长线红利防御：高股息DRIP+超跌核心资产"
        wencai = "股息率大于5%, PB小于1, 央企国企, 非ST, 流通市值大于100亿, 按股息率降序"
        risk = "短线可空仓，长线持有不动"
    elif total_score <= 70:
        state = "🔄 震荡期"
        allocation = {"长线": 30, "中线": 50, "短线": 20}
        strategy = "中线波段轮动：行业动量+小市值Alpha"
        wencai = "申万二级行业涨幅前3, 市值50-200亿, 换手率3-8%, MACD金叉, 非ST"
        risk = "破20日线止损中线仓位"
    else:
        state = "🔥 沸点期"
        allocation = {"长线": 10, "中线": 20, "短线": 70}
        strategy = "短线龙头进攻：打板接力+1进2+题材热点"
        wencai = "今日涨停, 非ST, 非新股, 换手率5-20%, 所属行业为[当前最热题材], 按市值降序"
        risk = "开盘低开>5%（核按钮）→短线立刻停止接力"

    return {
        "score": total_score,
        "state": state,
        "vol_score": vol_score,
        "effect_score": effect_score,
        "ladder_score": ladder_score,
        "flow_score": flow_score,
        "max_boards": max_boards,
        "up_count": up_count,
        "down_count": down_count,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "total_turnover_yi": total_turnover / 1e8 if total_turnover else 0,
        "allocation": allocation,
        "strategy": strategy,
        "wencai": wencai,
        "risk": risk,
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


# ─── 主入口 ───
def main():
    parser = argparse.ArgumentParser(description="每日短线标的推送 → 飞书Bot")
    parser.add_argument("--mode", required=True, choices=["premarket", "intraday", "postmarket", "alert", "scan", "sentiment", "test"])
    parser.add_argument("--force", action="store_true", help="强制推送，跳过交易日判断")
    args = parser.parse_args()

    # test 模式不受交易日限制
    if args.mode != "test" and not args.force:
        now = datetime.now(CST)
        if not is_trading_day(now):
            date_str = now.strftime("%Y-%m-%d")
            weekday_name = ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()]
            print(f"⏭️ {date_str} {weekday_name}，非交易日，跳过推送（--force 可强制）")
            return

    builders = {
        "premarket": build_premarket_card,
        "intraday": build_intraday_card,
        "postmarket": build_postmarket_card,
        "alert": build_alert_card_live,
        "scan": build_scan_card,
        "sentiment": build_sentiment_card,
        "test": build_test_card,
    }

    card = builders[args.mode]()
    ok = send_feishu(card)
    if ok:
        print(f"✅ 推送成功 ({args.mode})")
    else:
        print(f"❌ 推送失败 ({args.mode})")
        sys.exit(1)


if __name__ == "__main__":
    main()
