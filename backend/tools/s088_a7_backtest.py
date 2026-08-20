# -*- coding: utf-8 -*-
"""S088 A7 0819 暴风雨回测——用 0818 真数据预测 0819，验证概率分高。

spec §6 A7 验收：用 0818 外围+内部数据预测 0819，概率分应高（事后验证）。

真数据源（走 em_get 防封，不裸连）：
- 外围 0818 涨跌：push2his 指数历史K线（道指/纳指/标普/恒生/恒生科技/A50/日经/KOSPI）
- SOX 0818：datacenter RPT_INDUSTRY_INDEX/EMI00055562（report_date=0818，不需 ut）
- 内部 0818：gene_scores DB + sti_timeline DB（STI_TIMELINE_DB_PATH）
- 日历：纯算
- 新闻 0818：cache 缺历史（fetch_radar 当前不含 0818 ts），_collect_news_factor 走 fallback
  当前 cache + 标 fallback_current（透明降级，口径不完美——这是已知裂缝，待 daemon 跨日积累）

修历史 bug（R10 分析挖出）：
- _collect_internal_factor sti_timeline 原调 gene_scores DB（无此表）→ 恒降级 0；已改 STI_TIMELINE_DB_PATH
- _collect_news_factor 原读当前 cache 非 T-1 快照（orphaned 死写）；已改读 get_t1 快照

流程：构造 0818 快照（push2his 外围 + datacenter SOX）→ 写 storm_snapshots/2026-08-18.json
→ predict_storm("2026-08-19") 读 0818 快照 → 概率分 + 因子明细。期望概率分高（0819 暴风雨前兆）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import astock  # noqa: E402
from vr_paths import resolve_data_dir  # noqa: E402

UA_H = {"User-Agent": getattr(astock, "UA", "Mozilla/5.0")}
SNAP_DIR = resolve_data_dir() / "storm_snapshots"

IDX_SECID = {
    "道琼斯": "100.DJIA", "标普500": "100.SPX", "纳斯达克": "100.NDX",
    "恒生指数": "100.HSI", "恒生科技": "124.HSTECH", "富时A50": "100.XIN9",
    "日经225": "100.N225", "韩国KOSPI": "100.KS11",
}


def fetch_idx_chg_0818(name: str, secid: str) -> dict | None:
    """push2his 取 0817+0818 close 算 0818 涨跌%（相对昨收，对齐 f170 语义）。"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid": secid, "klt": "101", "fqt": "0", "beg": "20260817", "end": "20260818",
              "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56"}
    try:
        r = astock.em_get(url, params=params, headers=UA_H, timeout=10)
        kl = (r.json().get("data") or {}).get("klines") or []
        rows = [k.split(",") for k in kl]  # date,open,close,high,low,volume
        d17 = next((x for x in rows if x[0] == "2026-08-17"), None)
        d18 = next((x for x in rows if x[0] == "2026-08-18"), None)
        if d17 and d18 and float(d17[2]) > 0:
            c17, c18 = float(d17[2]), float(d18[2])
            return {"name": name, "change_pct": round((c18 - c17) / c17 * 100, 2)}
        return None
    except Exception:  # noqa: BLE001
        return None


def fetch_sox_0818() -> dict | None:
    """datacenter SOX report_date=0818（不需 ut，走 em_get）。"""
    try:
        rows = astock.eastmoney_datacenter(
            "RPT_INDUSTRY_INDEX", filter_str='(INDICATOR_ID="EMI00055562")',
            page_size=10, sort_columns="REPORT_DATE", sort_types="-1")
        for r in rows:
            if str(r.get("REPORT_DATE", ""))[:10] == "2026-08-18":
                cr = r.get("CHANGE_RATE")
                return {"name": "费城半导体", "change_pct": round(float(cr), 2)} if isinstance(cr, (int, float)) else None
        return None
    except Exception:  # noqa: BLE001
        return None


def build_0818_snapshot() -> dict:
    indices: list[dict] = []
    for name, secid in IDX_SECID.items():
        r = fetch_idx_chg_0818(name, secid)
        if r:
            indices.append(r)
        time.sleep(1.5)  # push2his 间隔防限流
    sox = fetch_sox_0818()
    if sox:
        indices.append(sox)
    # news 0818 cache 缺历史，留空 → _collect_news_factor fallback 当前 cache + 标 fallback_current
    return {"date": "2026-08-18", "global_indices": indices, "news_items": []}


def main() -> None:
    print("=== 构造 0818 真数据快照（push2his 外围 + datacenter SOX）===")
    snap = build_0818_snapshot()
    print(f"外围: {[(i['name'], i.get('change_pct')) for i in snap['global_indices']]}")

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAP_DIR / "2026-08-18.json"
    # 0818 快照 daemon 未存（0820 才启），直接写（补历史，不影响生产 daemon）
    path.write_text(json.dumps([snap], ensure_ascii=False), encoding="utf-8")
    print(f"快照写: {path}\n")

    print("=== predict_storm('2026-08-19') 读 0818 快照 ===")
    from strategies.storm_predictor import predict_storm  # noqa: PLC0415
    p = predict_storm("2026-08-19")
    print(f"概率分: {p.probability} | 风险: {p.risk_level} | 建议仓位: {p.suggested_position}")
    for f in p.factors:
        print(f"  {f.name}: {f.score} ({f.data_status}) | {f.detail}")
    # A7 验收：0819 暴风雨前兆，概率分应高（≥50=高/极高）
    print(f"\nA7 验收: 概率分 {p.probability} {'✓ 高（暴风雨前兆命中）' if p.probability >= 50 else '✗ 偏低'}")


if __name__ == "__main__":
    main()
