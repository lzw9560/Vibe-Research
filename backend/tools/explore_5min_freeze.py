# -*- coding: utf-8 -*-
"""探索性：baostock_5min_freeze 涨停股 5min 分时→封板时机 T+1 edge。

封板时机 edge 的 5min 粒度版——算精确封板时间（秒板/早盘/盘中/尾板）。
- entry=当日 open（涨停股开盘买，bars[0].open ≈ 9:30 开盘）
- exit=次日 open（T+1 卖）
- §44 v3 R4 survivorship 标注（全涨停股——无未涨停对照，标 survivorship 假 edge 风险）

数据：baostock_5min_freeze（13 天 <60 → exploratory）
跑法：cd backend && .venv/bin/python tools/explore_5min_freeze.py
"""

import json
import sqlite3
import statistics
import sys
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

INTRADAY = resolve_data_dir() / "intraday_accumulation" / "intraday_microstructure.db"
KLINE = resolve_data_dir() / "baostock_kline_cache.json"


def load_kline_bars(code):
    """从 kline cache JSON 取 code 日线 bars（非 db——baostock_kline_cache.db 0 byte 残留）。"""
    if not hasattr(load_kline_bars, "_cache"):
        load_kline_bars._cache = {}
    if code in load_kline_bars._cache:
        return load_kline_bars._cache[code]
    if not hasattr(load_kline_bars, "_all"):
        try:
            with open(KLINE, "r", encoding="utf-8") as f:
                load_kline_bars._all = json.load(f)
        except Exception:
            load_kline_bars._all = {}
    raw = load_kline_bars._all.get(code, [])
    out = [
        {
            "date": str(b.get("date", ""))[:10],
            "open": float(b.get("open", 0) or 0),
            "close": float(b.get("close", 0) or 0),
        }
        for b in raw
        if b.get("date") and float(b.get("open", 0) or 0) > 0
    ]
    out.sort(key=lambda x: x["date"])
    load_kline_bars._cache[code] = out
    return out


def parse_seal_time(bars_json):
    """从 5min bars 算封板时间——第一个 close==high 且后续 volume 趋零的 bar 的 time。

    封板特征：close==high（收盘=最高，封死）+ 后续 bars volume 极低（封板后成交枯竭）。
    返 (seal_time_str, seal_bucket)：秒板/早盘/盘中/尾板。
    """
    try:
        bars = json.loads(bars_json)
    except Exception:
        return None, None
    if not bars:
        return None, None
    # 找第一个 close==high 的 bar（封板 bar）
    for i, b in enumerate(bars):
        if b.get("close", 0) > 0 and abs(b.get("close", 0) - b.get("high", 0)) < 0.01:
            # 验证后续 volume 衰减（封板后成交枯竭）
            later_vols = [bars[j].get("volume", 0) for j in range(i + 1, min(i + 4, len(bars)))]
            seal_vol = b.get("volume", 0)
            if later_vols and seal_vol > 0:
                avg_later = sum(later_vols) / len(later_vols)
                # 封板后 volume 显著衰减（<50% 封板量）→ 真封死
                if avg_later < seal_vol * 0.5:
                    t = str(b.get("time", ""))
                    # time 格式 20260904093500000 → HHMM
                    if len(t) >= 10:
                        hhmm = t[8:12]
                        h, m = int(hhmm[:2]), int(hhmm[2:4])
                        mins = h * 60 + m
                        if mins <= 9 * 60 + 40:  # 9:40 前
                            return hhmm, "秒板(≤9:40)"
                        elif mins <= 10 * 60 + 30:  # 10:30 前
                            return hhmm, "早盘(9:40-10:30)"
                        elif mins <= 13 * 60:  # 13:00 前
                            return hhmm, "盘中(10:30-13:00)"
                        else:
                            return hhmm, "尾板(>13:00)"
    return None, None


def main():
    db = sqlite3.connect(str(INTRADAY))
    rows = db.execute("""
        SELECT date, code, bars_json FROM baostock_5min_freeze
        ORDER BY date, code
    """).fetchall()
    print(f"baostock_5min_freeze: {len(rows)} rows", flush=True)

    obs = []
    for date, code, bars_json in rows:
        seal_time, bucket = parse_seal_time(bars_json)
        if not seal_time:
            continue
        bars = load_kline_bars(code)
        idx = next((i for i, b in enumerate(bars) if b["date"] == date), None)
        if idx is None or idx + 1 >= len(bars):
            continue
        d_open = bars[idx]["open"]
        d1_open = bars[idx + 1]["open"]
        if d_open <= 0 or d1_open <= 0:
            continue
        edge = (d1_open - d_open) / d_open
        obs.append(
            {
                "date": date,
                "code": code,
                "edge": edge,
                "win": 1 if edge > 0 else 0,
                "bucket": bucket,
                "seal_time": seal_time,
            }
        )

    n = len(obs)
    days = len(set(o["date"] for o in obs))
    print(f"obs={n} days={days}（封板成功识别）")
    if n < 30:
        print(f"n={n}<30 → underpowered")
        return

    rets = [o["edge"] for o in obs]
    wr = sum(o["win"] for o in obs) / n
    print(f"\n=== 涨停股 T+1 edge（全样本，entry=当日 open→exit=次日 open）===")
    print(f"n={n} days={days} net_mean={statistics.mean(rets) * 100:.2f}% WR={wr * 100:.2f}%")

    # 按封板时机分组
    print(f"\n=== 按封板时机分组（5min 粒度）===")
    for bucket in ["秒板(≤9:40)", "早盘(9:40-10:30)", "盘中(10:30-13:00)", "尾板(>13:00)"]:
        g = [o for o in obs if o["bucket"] == bucket]
        if not g:
            continue
        gr = [o["edge"] for o in g]
        gwr = sum(o["win"] for o in g) / len(g)
        print(f"  {bucket}: n={len(g)} net_mean={statistics.mean(gr) * 100:.2f}% WR={gwr * 100:.2f}%")

    # §44 v3 R4 survivorship 标注（全涨停股——无未涨停对照）
    print(f"\n=== §44 v3 审 ===")
    print(f"  ⚠ 全样本为涨停股（baostock_5min_freeze 只存涨停股）→ 无未涨停对照组")
    print(f"  ⚠ R4 survivorship：涨停股 T+1 edge = 涨停封板溢价 + momentum（和 seal_timing edge 同类）")
    print(f"  ⚠ days={days}<60 → exploratory only")
    print(f"  ⚠ entry=当日 open（涨停股开盘买）≠ 市场价 close——封板时机 edge 是涨停股次日溢价 momentum 假 edge")

    # 和 seal_timing edge 对比（已知 +10% WR 98% 假 edge）
    print(f"\n=== 对比 seal_timing edge（已知假 edge +10% WR 98%）===")
    print(f"  本 edge net_mean={statistics.mean(rets) * 100:.2f}% WR={wr * 100:.2f}%")
    if statistics.mean(rets) > 0.05 and wr > 0.9:
        print(f"  ✓ 与 seal_timing 一致——涨停股 momentum survivorship 假 edge（5min 粒度不改变结论）")


if __name__ == "__main__":
    main()
