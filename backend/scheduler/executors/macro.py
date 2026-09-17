# -*- coding: utf-8 -*-
"""S216 macro_fetch executor——FRED 8 因子每日刷新 → .vibe-research/macro_snapshot.json cache。

06:35 盘前跑（FRED T+1 数据更新后 + A 股盘前 09:30 前）。
前端 MacroPanel（/api/macro/snapshot）+ storm_predictor 读 cache。
FRED 走 get_fred_api_key（.vibe-research/fred_api_key）+ fetch_fred_series，不裸调 requests（防封底线）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def macro_fetch(payload: Dict[str, Any]) -> Dict[str, Any]:
    """FRED 8 因子每日刷新 → macro_snapshot.json cache。

    调 macro.py fetch_fred_series 取 8 因子最新值（DGS10/DTWEXBGS/DFF/T10Y2Y/DEXCHUS/
    DCOILWTICO/PCOPPUSDM/VIXCLS）写 .vibe-research/macro_snapshot.json。
    前端 MacroPanel（/api/macro/snapshot）+ storm_predictor 读 cache。
    """
    from pathlib import Path  # noqa: PLC0415
    from predict.features.macro import (  # noqa: PLC0415
        MACRO_SPECS, FRED_SERIES, get_fred_api_key,
        fetch_fred_series, parse_fred_observations,
    )
    from vr_paths import resolve_data_dir  # noqa: PLC0415

    key = get_fred_api_key()
    if not key:
        logger.warning("[macro_fetch] FRED key 缺失（.vibe-research/fred_api_key），跳过")
        return {"status": "error: no FRED key"}

    snapshot: dict = {
        "factors": {},
        "fetched_at": datetime.now().isoformat(),
        "n_factors": len(MACRO_SPECS),
    }
    n_ok = 0
    for spec in MACRO_SPECS:
        sid = FRED_SERIES.get(spec.name)
        if not sid:
            continue
        try:
            data = fetch_fred_series(sid, key)
            obs = parse_fred_observations(data) if data else []
            if obs:
                snapshot["factors"][spec.name] = {
                    "value": obs[-1].get("value"),
                    "date": obs[-1].get("date"),
                    "series_id": sid,
                    "description": spec.description,
                }
                n_ok += 1
            else:
                snapshot["factors"][spec.name] = {"error": "no observations", "series_id": sid}
        except Exception as e:  # noqa: BLE001
            logger.warning("[macro_fetch] %s (%s) 失败: %s", spec.name, sid, e)
            snapshot["factors"][spec.name] = {"error": str(e), "series_id": sid}

    snapshot["n_ok"] = n_ok
    out = resolve_data_dir() / "macro_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    logger.info("[macro_fetch] 刷 cache ok: %s/%s 因子 → %s", n_ok, len(MACRO_SPECS), out)
    return {"status": "ok", "n_ok": n_ok, "n_factors": len(MACRO_SPECS)}
