"""edge combo §44 R3 复验：累积收益 vs 回测基准，保守规则降权/停。

支持 arm: inst_dominant（S236 +0.457%）/ a_group_t10（S237 +0.989%）/ combo_5d（S238 net +2.06%，weight 起步 0.5 因 test-set-selection）。

保守规则（用户 2026-10-09 拍板）：
- 累积 mean >= 回测 70% → weight 1.0 维持
- 累积 mean < 70% 但 >= 30% → weight 0.5 降权
- 累积 mean < 30% 或 < 0 → is_active=0 停

60 交易日首次复验（独立日 < 60 → 只提醒不执行降权，避免 underpowered 误杀）。

关联：specs/S236 / specs/S237 / trade_journal.db arm=inst_dominant|a_group_t10
"""
import sqlite3
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DB = DATA / "trade_journal.db"
BACKTEST_MEANS = {  # arm → 回测基准 net mean（S236/S237/S238）
    "inst_dominant": 0.457,  # basic top6 nostop
    "a_group_t10": 0.989,  # combo nostop
    "combo_5d": 1.07,  # top20 去涨停 5日 nostop net（R4: 涨停贡献40%是假edge，mode=filtered 滤涨停后真edge +1.07% t10.29；含涨停版+2.06% live 不可兑现）
}
# 权重档（full=维持 / half=降权 / stop=停）。combo_5d 起步 0.5 试探（test-set-selection），降权 0.25 非 0.5。
ARM_WEIGHTS = {
    "inst_dominant": (1.0, 0.5, 0.0),
    "a_group_t10": (1.0, 0.5, 0.0),
    "combo_5d": (0.5, 0.25, 0.0),
}
MIN_DAYS = 120  # 120 交易日首次复验（专家建议：regime 跳变 3-6月，60天 underpowered）


def replay_check(arm: str = "inst_dominant") -> dict:
    """跑复验，返回 {arm, n, days, mean, weight, is_active, reason, executed}。

    arm: inst_dominant（S236）/ a_group_t10（S237）/ combo_5d（S238 net +2.06%，权重档 0.5/0.25/0）。
    """
    backtest_mean = BACKTEST_MEANS.get(arm, 0.457)
    conn = sqlite3.connect(str(DB))
    rows = conn.execute(
        "SELECT entry_date, net_pnl, unrealized_pnl, is_realized "
        "FROM trade_journal WHERE arm=?",
        (arm,),
    ).fetchall()
    if not rows:
        conn.close()
        return {"arm": arm, "n": 0, "days": 0, "mean": None, "executed": False, "reason": "无 signal"}

    returns = []
    for d, net, unreal, realized in rows:
        pnl = net if (realized and net is not None) else (unreal if unreal is not None else None)
        if pnl is not None:
            returns.append(pnl)
    n = len(returns)
    days = len(set(r[0] for r in rows if r[0]))
    if n == 0:
        conn.close()
        return {"arm": arm, "n": 0, "days": days, "mean": None, "executed": False, "reason": "无收益数据"}

    mean = sum(returns) / n
    result = {"arm": arm, "n": n, "days": days, "mean": round(mean, 3), "executed": False}

    if days < MIN_DAYS:
        result["reason"] = f"天数 {days} < {MIN_DAYS}，只提醒不执行降权（首次复验待 {MIN_DAYS} 交易日）"
        result["weight"] = None
        result["is_active"] = None
        conn.close()
        return result

    t70 = backtest_mean * 0.7
    t30 = backtest_mean * 0.3
    full_w, half_w, stop_w = ARM_WEIGHTS.get(arm, (1.0, 0.5, 0.0))
    if mean >= t70:
        weight, status, reason = full_w, 1, f"维持（mean {mean:.3f}% >= 70%基准 {t70:.3f}%）"
    elif mean >= t30:
        weight, status, reason = half_w, 1, f"降权（mean {mean:.3f}% 在30-70%基准）"
    else:
        weight, status, reason = stop_w, 0, f"停（mean {mean:.3f}% < 30%基准 {t30:.3f}% 或衰减严重）"

    conn.execute(
        "UPDATE arm_status SET is_active=?, weight_override=?, kill_reason=? WHERE arm=?",
        (status, weight, reason, arm),
    )
    conn.commit()
    conn.close()
    result.update({"weight": weight, "is_active": status, "reason": reason, "executed": True})
    return result


if __name__ == "__main__":
    for arm in ("inst_dominant", "a_group_t10", "combo_5d"):
        r = replay_check(arm)
        print(f"\n=== {arm} ===")
        print(f"  {r.get('n')} signals, {r.get('days')} 独立日")
        if r.get("mean") is not None:
            print(f"  累积 mean: {r['mean']}% (vs 回测 {BACKTEST_MEANS.get(arm)}%)")
        print(f"  保守规则: {r['reason']}")
        if r.get("executed"):
            print(f"  arm_status 已更新: is_active={r['is_active']} weight={r['weight']}")
