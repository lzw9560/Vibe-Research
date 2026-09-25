# -*- coding: utf-8 -*-
"""S088 Q2/Q3 secid 探测——验证外围指数 secid 在 push2 stock/get 或 datacenter 端点返数据。

防封底线（CLAUDE.md §1.2 + 记忆 eastmoney-push2-ut-token）：
- 全走 astock.em_get（data.transport.eastmoney_get，限流+熔断+代理探测），不裸调 requests。
- push2 单股 stock/get 指数通道实测不需 ut（gstock 生产每次请求打 7 次），但探测间隔 2s 谨慎。
- push2 失败降级 push2delay（gstock._push2_stock_get 自带 _gs_host latch）。
- datacenter 不需 ut（与个股 push2 需 ut 不同）。
不臆造：返空就标空，不猜。结果落 .vibe-research/s088-secid-probe/matrix.json。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import astock  # noqa: E402
import gstock  # noqa: E402

PUSH2_CANDIDATES = [
    ("n225", "100.N225", "日经225（Q2 已加，验证 stock/get 是否真返）"),
    ("kospi", "100.KS11", "KOSPI（Q3 高置信，akshare cons.py+index_global_em.py 双重佐证）"),
    ("ndxt", "100.NDXT", "纳指科技（Q3 规律猜，未验证）"),
]
FIELDS = "f43,f57,f58,f59,f60,f170"


def probe_push2() -> list[dict]:
    out: list[dict] = []
    for key, secid, note in PUSH2_CANDIDATES:
        t0 = time.time()
        try:
            d = gstock._push2_stock_get(secid, FIELDS)
            lat = round(time.time() - t0, 2)
            if d:
                chg = d.get("f170")
                out.append({
                    "secid": secid, "key": key, "note": note,
                    "raw_non_empty": True, "name": d.get("f58"),
                    "price": gstock._price(d, "f43"),
                    "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
                    "latency_s": lat, "host_index": gstock._gs_host[0],
                })
            else:
                out.append({
                    "secid": secid, "key": key, "note": note,
                    "raw_non_empty": False, "latency_s": lat,
                    "host_index": gstock._gs_host[0],
                })
        except Exception as e:  # noqa: BLE001
            out.append({
                "secid": secid, "key": key, "note": note,
                "raw_non_empty": False, "error": repr(e),
                "latency_s": round(time.time() - t0, 2),
            })
        time.sleep(2)  # push2 探测间隔（谨慎防限流）
    return out


def probe_sox_datacenter() -> dict:
    """SOX 费城半导体走 datacenter RPT_INDUSTRY_INDEX/EMI00055562（非 push2 secid）。

    返回是日频行业指标报告（REPORT_DATE/INDICATOR_VALUE/CHANGE_RATE），非实时行情，
    shape 跟 _quote_from 不兼容——本探测只验端点可达 + 字段，实际接入需独立解析。
    """
    t0 = time.time()
    try:
        rows = astock.eastmoney_datacenter(
            "RPT_INDUSTRY_INDEX",
            filter_str='(INDICATOR_ID="EMI00055562")',
            page_size=5, sort_columns="REPORT_DATE", sort_types="-1",
        )
        lat = round(time.time() - t0, 2)
        if rows:
            r = rows[0]
            return {
                "route": "datacenter:RPT_INDUSTRY_INDEX/EMI00055562", "key": "sox",
                "note": "费城半导体 datacenter 路线（非 push2 secid）",
                "raw_non_empty": True, "fields_sample": list(r.keys())[:12],
                "report_date": str(r.get("REPORT_DATE", ""))[:10],
                "indicator_value": r.get("INDICATOR_VALUE"),
                "change_rate": r.get("CHANGE_RATE"),
                "latency_s": lat,
            }
        return {
            "route": "datacenter:RPT_INDUSTRY_INDEX/EMI00055562", "key": "sox",
            "note": "费城半导体 datacenter 路线", "raw_non_empty": False, "latency_s": lat,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "route": "datacenter:RPT_INDUSTRY_INDEX/EMI00055562", "key": "sox",
            "note": "费城半导体 datacenter 路线",
            "raw_non_empty": False, "error": repr(e), "latency_s": round(time.time() - t0, 2),
        }


if __name__ == "__main__":
    print("=== push2 stock/get 探测（N225 / KS11 / NDXT）===")
    push2 = probe_push2()
    for r in push2:
        print(json.dumps(r, ensure_ascii=False))
    print("\n=== SOX datacenter 探测 ===")
    sox = probe_sox_datacenter()
    print(json.dumps(sox, ensure_ascii=False))

    out_dir = ROOT / ".vibe-research" / "s088-secid-probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = out_dir / "matrix.json"
    matrix_path.write_text(
        json.dumps({"push2": push2, "sox_datacenter": sox}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nmatrix 落盘: {matrix_path}")
