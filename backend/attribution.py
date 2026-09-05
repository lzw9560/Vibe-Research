"""判断 vs 执行归因：把"市场判断成没成立"与"自己赚没赚钱"交叉起来。

系统里两套验证各回答半个问题：`reflection` / `verification` 说昨晚那份判断今天
成立没有，`journal` / `risk_rules` 说这些天赚了还是亏了。只看一层会得出错的结论 ——
看对了却亏钱和看错了才亏钱要修的地方不同（前者改执行，后者改判断）。

## 四格

|            | 自己赚钱   | 自己亏钱             |
|------------|------------|----------------------|
| **判对了** | 顺风顺水   | ⭐**执行问题**       |
| **判错了** | ⚠️**运气** | 判断问题             |

⚠️「判错还赚钱」那格必须单独点出来，不能混进"总体盈利"里。

## 对齐哪一天（容易搞错）

交易在 **D 日入场**，依据是 **D-1 晚**那份判断；`reflection` 文件里
`prediction_date = D-1`、`eval_date = D`。所以对齐关系是：

    交易的入场日（settled.first_buy） ←→ reflection 的 eval_date

⚠️ **不能按平仓日对齐**：D 日买、D+2 日卖的交易，按平仓日会去比 D+1 晚做的判断 ——
那份判断没参与这笔决策，归因张冠李戴，而两个数都长得正常、看不出来。

## 边界

只统计使用者自己录入的交易与已落盘的复盘产物，不产出任何操作建议。
⛔ 本模块的数据**不接入任何 AI prompt**（守 AGENTS.md 个人数据隔离；P3-T1 闭包扫描锁定）。

## ⚠️ P3 移植降级（2026-09-05）

vibe-astock 的 `_read_hits` 读 `~/.duanxian-agents/reflections/*.json`（其复盘评估
模块 `reflection` 的预测命中数据）。Vibe-Research **无此数据源**（`reflection.py` 是
72 行流式 LLM 调用，语义不同；`prediction_ledger` 是另一套格式，未对齐）。故 `_read_hits`
诚实返空 → `attribution()` 降级 `available:False`（"还没有可用的市场判断记录"），
**不臆造判断命中**。函数结构已就位，待新 spec 接 Vibe-Research 预测命中数据源后激活。

# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified
# Original author: Simon Lin (simonlin0423@gmail.com)
"""
from __future__ import annotations

from typing import Optional

# 四格的名字。⚠️ 顺序别改，前端按 key 取。
QUADRANTS = {
    "right_win": "判对 + 赚钱",
    "right_lose": "判对 + 亏钱",       # ⭐ 执行问题
    "wrong_win": "判错 + 赚钱",        # ⚠️ 运气
    "wrong_lose": "判错 + 亏钱",
}

# 少于这么多天，四格分布是噪声，不给倾向性描述
_MIN_DAYS = 8


def _read_hits() -> dict[str, dict]:
    """每个交易日的「市场判断对没对」。key = eval_date（= 交易入场日）。

    ⚠️ P3 降级：vibe-astock 读 `~/.duanxian-agents/reflections/*.json`（复盘评估的
    预测命中）。Vibe-Research 无此数据源（reflection.py 语义不同、prediction_ledger
    格式未对齐）→ 诚实返空，不臆造判断命中。待新 spec 接预测命中数据源后激活。
    """
    return {}


def _entry_day(trade: dict) -> Optional[str]:
    """交易的入场日。没有成交明细就退回记录日期。"""
    s = trade.get("settled") or {}
    return s.get("first_buy") or trade.get("date")


def _pnl(trade: dict) -> Optional[float]:
    """这笔的已实现盈亏（元）。只填了百分比、没填明细的算不出金额。"""
    s = trade.get("settled") or {}
    v = s.get("realized_pnl")
    return None if v is None else float(v)


def attribution(limit: int = 500) -> dict:
    """把有交易的每一天拆进四格。

    ⚠️ 只用**已平仓且填了成交明细**的交易 —— 没有金额就没有"那天赚没赚"，
    拿百分比按笔数平均会把 1 万的仓和 1 千的仓当成一样重。
    """
    # P3-T3d：from . import journal → import journal
    import journal

    try:
        trades = (journal.list_trades(limit=limit) or {}).get("trades") or []
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"读交易日志失败：{exc}"}

    hits = _read_hits()
    if not hits:
        # 诚实降级：无市场判断数据源（不臆造命中）——待新 spec 接预测数据后激活
        return {"available": False,
                "reason": "还没有可用的市场判断记录（Vibe-Research 暂无 reflection/"
                          "预测命中数据源），无法做判断/执行归因"}

    # 按入场日汇总当天的已实现盈亏
    by_day: dict[str, dict] = {}
    skipped_no_amount = 0
    skipped_no_read = 0
    for t in trades:
        d = _entry_day(t)
        pnl = _pnl(t)
        if d is None:
            continue
        if pnl is None:
            skipped_no_amount += 1
            continue
        if d not in hits:
            skipped_no_read += 1
            continue
        b = by_day.setdefault(d, {"date": d, "pnl": 0.0, "trades": 0,
                                  "unplanned": 0, **hits[d]})
        b["pnl"] += pnl
        b["trades"] += 1
        if t.get("as_planned") is False:
            b["unplanned"] += 1

    if not by_day:
        return {"available": False, "skipped_no_amount": skipped_no_amount,
                "skipped_no_read": skipped_no_read,
                "reason": ("没有能归因的交易日 —— 需要「填了成交明细的已平仓交易」"
                           "且那天有市场判断记录")}

    cells: dict[str, list[dict]] = {k: [] for k in QUADRANTS}
    for b in sorted(by_day.values(), key=lambda x: x["date"]):
        b["pnl"] = round(b["pnl"], 2)
        # ⚠️ 盈亏恰好为 0 的日子不进任何一格：它既不是赚也不是亏。
        if abs(b["pnl"]) < 1e-6:
            continue
        key = ("right_" if b["hit"] else "wrong_") + ("win" if b["pnl"] > 0 else "lose")
        cells[key].append(b)

    def _sum(rows: list[dict]) -> dict:
        return {"days": len(rows), "pnl": round(sum(r["pnl"] for r in rows), 2),
                "days_list": [r["date"] for r in rows]}

    summary = {k: _sum(v) for k, v in cells.items()}
    counted = sum(s["days"] for s in summary.values())
    return {
        "available": True,
        "days_counted": counted,
        "enough_samples": counted >= _MIN_DAYS,
        "quadrant_labels": QUADRANTS,
        "quadrants": summary,
        "cells": cells,
        "skipped_no_amount": skipped_no_amount,
        "skipped_no_read": skipped_no_read,
        "note": ("按**入场日**对齐：那天的操作依据是前一晚那份判断。"
                 "盈亏为 0 的日子不进任何一格。"),
    }


def render(rep: dict) -> str:
    """四格的纯文本形式（给 UI 兜底展示 / 自用脚本读）。

    ⛔ **不要把它接进任何 AI prompt。** 个人持仓与盈亏一旦进 prompt，模型的
    回答就变成"针对这个人当前处境"的意见 —— 那正是个性化投资建议，
    是本项目合规立足点（非个性化）唯一不能碰的那条线。
    """
    if not rep.get("available"):
        return ""
    q = rep.get("quadrants") or {}
    lines = [f"· 判断/执行归因（{rep['days_counted']} 个有盈亏的交易日）："]
    for k, label in QUADRANTS.items():
        c = q.get(k) or {}
        if c.get("days"):
            lines.append(f"  - {label}：{c['days']} 天，合计 {c['pnl']:+.0f} 元")
    exe = (q.get("right_lose") or {}).get("days") or 0
    luck = (q.get("wrong_win") or {}).get("days") or 0
    if not rep.get("enough_samples"):
        lines.append(f"  ⚠️ 只有 {rep['days_counted']} 天，样本太少，别下结论")
    else:
        if exe:
            lines.append(f"  ⭐ 有 {exe} 天是「看对了却亏钱」—— 这几天的问题在执行不在判断")
        if luck:
            lines.append(f"  ⚠️ 有 {luck} 天是「看错了还赚钱」—— 赚钱会给错判断发正反馈")
    return "\n".join(lines)


__all__ = ["QUADRANTS", "attribution", "render"]
