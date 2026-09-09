# -*- coding: utf-8 -*-
"""S172 A 臂 floor——ETF 512890 红利低波分批建仓 + 持有 + 周报。

spec: specs/S172-红利低波指数复制臂/spec.md（R4-R6）。
plan: specs/S172-红利低波指数复制臂/plan.md（§2.2）。

长线底仓 hold——无 stop/take 触发（R6），不接 accounting（ETF 市场收益即净收益，
管理费已含净值）。私有数据写 .vibe-research/etf_floor/（vr_paths 模式，gitignored）。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from vr_paths import resolve_data_dir, next_trading_date, is_trading_day  # noqa: E402
from tools.fetch_etf_tracking import (  # noqa: E402
    fetch_etf_quote,
    tracking_error_report,
)

_LOGGER = logging.getLogger("vibe-research")

_FLOOR_DIR: Path = resolve_data_dir() / "etf_floor"
_FLOOR_DIR.mkdir(parents=True, exist_ok=True)
_BATCHES_PATH: Path = _FLOOR_DIR / "batches.json"

#: ETF 代码（华泰柏瑞红利低波 ETF）
ETF_CODE = "512890"
#: 跟踪指数（中证红利低波动指数）
INDEX_CODE = "930955"


def _atomic_write_json(path: Path, data) -> None:
    """atomic write（tmp+os.replace，POSIX 原子 swap）——防 kill 时 truncated JSON。

    scan_long_value_cache.py:58 模式。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_batches() -> list[dict]:
    """读 batches.json，不存在返 []。"""
    if not _BATCHES_PATH.exists():
        return []
    try:
        return json.loads(_BATCHES_PATH.read_bytes())
    except (json.JSONDecodeError, OSError):
        _LOGGER.warning("batches.json 损坏，返空列表")
        return []


# ---------------------------------------------------------------------------
# R4: 分批建仓调度
# ---------------------------------------------------------------------------

def build_position_batches(
    total: int = 100000,
    n_batches: int = 5,
    interval_days: int = 7,
    one_shot: bool = False,
    start_date: str | None = None,
) -> list[dict]:
    """生成分批建仓计划（不自动下单——用户确认后 record_batch 记录实盘）。

    - one_shot=True：单批全额，date=最近交易日
    - one_shot=False：n_batches 批，每批 total//n_batches，间隔 interval_days 交易日
    - start_date：首批日期（YYYY-MM-DD），空则最近交易日

    返回 [{batch_idx, date, amount, status}]。
    """
    from datetime import date as _date, datetime as _dt
    import math

    if start_date:
        first = _date.fromisoformat(start_date)
    else:
        first = next_trading_date() if not is_trading_day() else _date.today()

    if one_shot:
        return [{"batch_idx": 0, "date": first.isoformat(),
                 "amount": total, "status": "planned"}]

    per_batch = total // n_batches
    remainder = total - per_batch * n_batches

    plan: list[dict] = []
    cursor = first
    for i in range(n_batches):
        amt = per_batch + (remainder if i == n_batches - 1 else 0)
        plan.append({
            "batch_idx": i,
            "date": cursor.isoformat(),
            "amount": amt,
            "status": "planned",
        })
        # 前进 interval_days 个交易日
        for _ in range(interval_days):
            cursor = next_trading_date(cursor)
    return plan


def record_batch(batch_idx: int, date: str, price: float,
                 shares: int, amount: float) -> dict:
    """记录已执行的批次到 batches.json（atomic write）。

    返回写入的批次 dict。status 改为 'filled'。
    """
    batches = _load_batches()
    entry = {
        "batch_idx": batch_idx,
        "date": date,
        "price": price,
        "shares": shares,
        "amount": amount,
        "status": "filled",
    }
    # 更新已有条目或追加
    updated = False
    for i, b in enumerate(batches):
        if b.get("batch_idx") == batch_idx:
            batches[i] = entry
            updated = True
            break
    if not updated:
        batches.append(entry)
    batches.sort(key=lambda x: x.get("batch_idx", 0))
    _atomic_write_json(_BATCHES_PATH, batches)
    return entry


# ---------------------------------------------------------------------------
# 持有状态
# ---------------------------------------------------------------------------

def hold_status() -> dict:
    """读 batches.json → 持仓状态汇总。

    返回 {total_cost, total_shares, n_filled, batches, avg_cost}。
    无持仓时 total_shares=0, avg_cost=0.0。
    """
    batches = _load_batches()
    filled = [b for b in batches if b.get("status") == "filled"]
    total_cost = sum(b.get("amount", 0) for b in filled)
    total_shares = sum(b.get("shares", 0) for b in filled)
    avg_cost = (total_cost / total_shares) if total_shares > 0 else 0.0
    return {
        "total_cost": round(total_cost, 2),
        "total_shares": total_shares,
        "n_filled": len(filled),
        "avg_cost": round(avg_cost, 4),
        "batches": filled,
    }


# ---------------------------------------------------------------------------
# R5: 周报
# ---------------------------------------------------------------------------

def weekly_report() -> dict:
    """周报：持仓市值 / 成本基 / 浮动盈亏 / 跟踪误差 / 累计收息。

    调 hold_status（成本基）+ fetch_etf_quote（实时价格）+ tracking_error_report（跟踪误差）。
    取数失败降级标注，不阻塞报告产出。
    """
    status = hold_status()
    quote = fetch_etf_quote(ETF_CODE)

    price = quote.get("price") or 0.0
    market_value = status["total_shares"] * price
    cost_basis = status["total_cost"]
    unrealized_pnl = market_value - cost_basis
    pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0

    te = tracking_error_report(ETF_CODE, INDEX_CODE)

    return {
        "etf_code": ETF_CODE,
        "asof_price": price,
        "market_value": round(market_value, 2),
        "cost_basis": round(cost_basis, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "total_shares": status["total_shares"],
        "avg_cost": status["avg_cost"],
        "n_filled": status["n_filled"],
        "tracking_error": te,
        "risk_disclaimer": "历史统计特征，市场有风险",
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="S172 ETF 红利低波 floor")
    sub = p.add_subparsers(dest="cmd")
    sub_plan = sub.add_parser("plan", help="生成分批建仓计划")
    sub_plan.add_argument("--total", type=int, default=100000)
    sub_plan.add_argument("--batches", type=int, default=5)
    sub_plan.add_argument("--interval", type=int, default=7)
    sub_plan.add_argument("--one-shot", action="store_true")
    sub.add_parser("status", help="查看持仓状态")
    sub.add_parser("report", help="产出周报")
    args = p.parse_args()

    if args.cmd == "plan":
        plan = build_position_batches(args.total, args.batches, args.interval, args.one_shot)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        print(json.dumps(hold_status(), ensure_ascii=False, indent=2))
    elif args.cmd == "report":
        print(json.dumps(weekly_report(), ensure_ascii=False, indent=2))
    else:
        p.print_help()
