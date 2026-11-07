# -*- coding: utf-8 -*-
"""数据获取层 — run_cli + 各数据获取函数。

从 feishu_daily_push.py 拆出。改进：
- run_cli 区分异常类型（TimeoutExpired/JSONDecodeError/非零退出），记日志
  原版吞所有异常返回 None；新版保留「返回 None 不阻塞主流程」的契约，
  但记日志便于诊断
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def run_cli(cmd: str) -> dict | None:
    """运行 hithink-finance CLI 并返回解析后的 JSON dict。

    失败返回 None（不抛异常，保持向后兼容的"不阻塞主流程"契约）。
    但会区分异常类型记日志，便于诊断：
    - TimeoutExpired：CLI 卡死
    - JSONDecodeError：CLI 输出非 JSON（stderr 混入或格式变更）
    - 非零退出码：CLI 报错
    """
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        logger.warning("CLI 超时(30s): %s", cmd[:80])
        return None
    except Exception as e:
        logger.warning("CLI 执行异常: %s | cmd=%s", e, cmd[:80])
        return None

    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip().splitlines()[-1:]
        logger.warning(
            "CLI 非零退出(%d): %s | stderr=%s",
            result.returncode, cmd[:80], stderr_tail[0][:120] if stderr_tail else "",
        )
        return None

    # 取最后一行 JSON（可能有 stderr 提示混入）
    lines = result.stdout.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("CLI 输出 JSON 解析失败: %s | line=%s", e, line[:120])
                return None
    logger.warning("CLI 输出无可解析 JSON: %s | stdout_lines=%d", cmd[:80], len(lines))
    return None


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
    try:
        with open("/tmp/snap_push.json") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取全市场快照文件失败: %s", e)
        return []
    return data.get("data", {}).get("item", [])


# ─── 监控标的池（动态生成+手动补充） ───
WATCH_LIST: list = []  # 不再硬编码，改为动态扫描


def scan_group_a_stocks() -> list:
    """扫描龙虎榜，筛选A组特征标的（可跟庄）。

    A组特征（回测验证有效）：
    1. 当日涨幅 -3% ~ +10%（不是涨停/暴涨20%）
    2. 净买入 < 0.5亿（主力在建仓不是一把打完）
    3. 热度排名 > 100（不是最热的票，散户关注度低）
    4. 净买入为正
    """
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

    a_group.sort(key=lambda x: x["net"], reverse=True)
    return a_group[:5]  # 最多推5只


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
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取K线文件失败 code=%s: %s", code, e)
        return []


def calc_ma5(klines: list) -> float | None:
    """计算5日均线。"""
    if len(klines) < 5:
        return None
    recent5 = klines[-5:]
    return sum(it["close_price"] for it in recent5) / 5


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
