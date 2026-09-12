# -*- coding: utf-8 -*-
"""S188 B2 · mootdx 历史分笔 → 主动买卖 OFI proxy（唯一免费历史 OFI 路径）。

调研结论（2026-09-12）：无免费源给历史五档 Level2 快照（交易所付费产品）。
mootdx Quotes.transactions(symbol, date) 能拉**历史分笔**（price/vol/buyorsell 主动买卖方向），
用 Cont OFI 变体——基于主动买卖方向（buyorsell 1=主动买/2=主动卖）建 OFI proxy：
  active_buy_vol = Σ vol where buyorsell==1
  active_sell_vol = Σ vol where buyorsell==2
  ofi_proxy = (active_buy - active_sell) / (active_buy + active_sell) ∈ [-1, 1]

精度低于真五档盘口 OFI（主动方向 ≠ 挂单深度变化），但能历史回测近似。
69 交易日回补 → OFI proxy 分布 + §44 lift 验证。

用法：
  python tools/mootdx_tick_ofi_proxy.py --code 000001 --date 20260910
  python tools/mootdx_tick_ofi_proxy.py --code 000001 --start 20260901 --end 20260910
  python tools/mootdx_tick_ofi_proxy.py --codes 000001,600000 --start 20260701 --end 20260910 --output ofi_proxy.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# mootdx 走 stoke venv（项目 venv 无 mootdx，用 ~/stoke 的 uv env 跑此脚本）
# 但此脚本设计为可独立跑：python tools/mootdx_tick_ofi_proxy.py（需 mootdx 在 PATH）


def _trading_days(start: str, end: str) -> list[str]:
    """枚举 [start, end] 交易日（跳周末；节假日由 mootdx 拉空兜底）。YYYYMMDD。"""
    out = []
    d = datetime.strptime(start, "%Y%m%d")
    end_d = datetime.strptime(end, "%Y%m%d")
    while d <= end_d:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def fetch_tick_ofi(code: str, date: str, page_size: int = 2000, max_pages: int = 20, return_raw: bool = False) -> dict | None:
    """拉某 code 某 date 全日分笔 → 算主动买卖 OFI proxy。

    mootdx transactions 分页：start=0,offset=2000 → 下一页 start+=offset。
    buyorsell: 1=主动买, 2=主动卖, 0=中性, 5/8=其他（不计入主动买卖）。
    返 {code, date, n_ticks, active_buy_vol, active_sell_vol, ofi_proxy, buy_sell_ratio}。
    return_raw=True 额外含 raw_ticks=[{time,price,vol,buyorsell,volume}]（供 save_ticks 落 datalake）。
    """
    try:
        from mootdx.quotes import Quotes  # noqa: PLC0415
    except ImportError:
        return {"error": "mootdx 未装（在 ~/stoke venv 跑：cd ~/stoke && uv run python 此脚本）"}
    q = Quotes.factory(market="std")
    all_ticks = []
    start = 0
    for _ in range(max_pages):
        try:
            df = q.transactions(symbol=code, date=date, start=start, offset=page_size)
        except Exception as e:  # noqa: BLE001
            return {"error": f"transactions 拉取失败 {code} {date}: {e}"}
        if df is None or len(df) == 0:
            break
        all_ticks.append(df)
        if len(df) < page_size:
            break  # 最后一页
        start += page_size
    if not all_ticks:
        return {"code": code, "date": date, "n_ticks": 0, "note": "无分笔数据（非交易日/停牌）"}
    import pandas as pd  # noqa: PLC0415
    df_all = pd.concat(all_ticks, ignore_index=True)
    active_buy = int(df_all[df_all["buyorsell"] == 1]["vol"].sum())
    active_sell = int(df_all[df_all["buyorsell"] == 2]["vol"].sum())
    total = active_buy + active_sell
    ofi_proxy = (active_buy - active_sell) / total if total > 0 else 0.0
    result = {
        "code": code,
        "date": date,
        "n_ticks": len(df_all),
        "active_buy_vol": active_buy,
        "active_sell_vol": active_sell,
        "ofi_proxy": round(ofi_proxy, 4),
        "buy_sell_ratio": round(active_buy / active_sell, 3) if active_sell > 0 else None,
    }
    if return_raw:
        # raw ticks 供 save_ticks 落 datalake（不经 stdout 大 JSON，避免 subprocess 传大 payload）
        df_all["volume"] = (df_all["price"].astype(float) * df_all["vol"].astype(int)).round(2)
        result["raw_ticks"] = df_all[["time", "price", "vol", "buyorsell", "volume"]].to_dict(orient="records")
    return result


def fetch_range(codes: list[str], start: str, end: str) -> dict:
    """多 code × 多日拉分笔 OFI proxy。返 {results: [...], summary}。"""
    days = _trading_days(start, end)
    results = []
    for code in codes:
        for date in days:
            r = fetch_tick_ofi(code, date)
            results.append(r)
            if "ofi_proxy" in r:
                print(f"[{code} {date}] ticks={r['n_ticks']} ofi={r['ofi_proxy']} buy/sell={r['buy_sell_ratio']}")
            else:
                print(f"[{code} {date}] {r.get('note') or r.get('error', '?')}")
    ofi_vals = [r["ofi_proxy"] for r in results if "ofi_proxy" in r]
    return {
        "codes": codes,
        "date_range": f"{start}~{end}",
        "results": results,
        "summary": {
            "n_valid": len(ofi_vals),
            "mean_ofi_proxy": round(sum(ofi_vals) / len(ofi_vals), 4) if ofi_vals else 0,
            "positive_days": sum(1 for v in ofi_vals if v > 0),
            "negative_days": sum(1 for v in ofi_vals if v < 0),
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description="S188 B2 · mootdx 历史分笔 → 主动买卖 OFI proxy")
    p.add_argument("--code", default=None, help="单只 code（YYYYMMDD 用 --date 或 --start/--end）")
    p.add_argument("--codes", default=None, help="多只逗号分隔")
    p.add_argument("--date", default=None, help="单日 YYYYMMDD")
    p.add_argument("--start", default=None, help="起始日 YYYYMMDD")
    p.add_argument("--end", default=None, help="结束日 YYYYMMDD")
    p.add_argument("--output", default=None, help="落盘 JSON 路径")
    p.add_argument("--save-datalake", action="store_true", help="直接拉 raw ticks 落 datalake/ticks_YYYYMM.db（不经 stdout，供 daily_full_pull 用）")
    args = p.parse_args()

    codes = []
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.code:
        codes = [args.code]
    if not codes:
        p.error("需 --code 或 --codes")

    if args.date:
        start = end = args.date
    elif args.start and args.end:
        start, end = args.start, args.end
    else:
        p.error("需 --date 或 --start/--end")

    # --save-datalake：拉 raw ticks 直接落 datalake（不经 stdout 大 JSON）
    if args.save_datalake:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from data.datalake.store import save_ticks  # noqa: PLC0415
        from vr_paths import resolve_data_dir  # noqa: PLC0415
        days = _trading_days(start, end)
        saved = 0
        for code in codes:
            for d_compact in days:
                r = fetch_tick_ofi(code, d_compact, return_raw=True)
                if "raw_ticks" in r and r["raw_ticks"]:
                    d_iso = f"{d_compact[:4]}-{d_compact[4:6]}-{d_compact[6:8]}"
                    save_ticks(d_iso, code, r["raw_ticks"])
                    saved += 1
                    print(f"[{code} {d_compact}] saved {len(r['raw_ticks'])} ticks to datalake", file=sys.stderr)
                else:
                    print(f"[{code} {d_compact}] {r.get('note') or r.get('error', '无 raw ticks')}", file=sys.stderr)
        print(json.dumps({"saved_codes_dates": saved}, ensure_ascii=False))
        return

    result = fetch_range(codes, start, end)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n落盘: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
