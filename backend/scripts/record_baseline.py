# -*- coding: utf-8 -*-
"""S016 R4：IO 基线录制脚本（live 门控，非交易时段跳过）。

用法：
    cd backend && ../.venv/bin/python -m pytest scripts/record_baseline.py -m live -s

产出：tests/contract/baseline/{code}_{endpoint}.json
- A 股 6 只：600519/000858/300750/688981/000001/002594
- 端点：quote / capital_flow / dragon_tiger

港股/美股 code 无数据则跳过（诚实标注，不臆造）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASELINE_DIR = Path(__file__).parent.parent / "tests" / "contract" / "baseline"
A_STOCKS = ["600519", "000858", "300750", "688981", "000001", "002594"]


@pytest.mark.live
def test_record_quote_baseline():
    """录制 quote 端点基线（live，非交易时段可能返空→跳过）。"""
    import astock
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for code in A_STOCKS:
        try:
            q = astock.tencent_quote([code]) or {}
            data = q.get(code)
            if not data:
                continue  # 跳过无数据 code
            out = BASELINE_DIR / f"{code}_quote.json"
            out.write_text(json.dumps({"code": code, "data": data}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[record] {code} quote 失败：{exc}", file=sys.stderr)


@pytest.mark.live
def test_record_capital_flow_baseline():
    """录制 capital_flow 端点基线（live）。"""
    import astock
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for code in A_STOCKS:
        try:
            raw = astock.em_get("capital_flow", {"code": code, "days": 30})
            if not raw:
                continue
            out = BASELINE_DIR / f"{code}_capital_flow.json"
            out.write_text(json.dumps({"code": code, "data": raw}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[record] {code} capital_flow 失败：{exc}", file=sys.stderr)


@pytest.mark.live
def test_record_dragon_tiger_baseline():
    """录制 dragon_tiger 端点基线（live）。"""
    import astock
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for code in A_STOCKS:
        try:
            raw = astock.em_get("dragon_tiger", {"code": code})
            if not raw:
                continue
            out = BASELINE_DIR / f"{code}_dragon_tiger.json"
            out.write_text(json.dumps({"code": code, "data": raw}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[record] {code} dragon_tiger 失败：{exc}", file=sys.stderr)


if __name__ == "__main__":
    # 直接运行：python scripts/record_baseline.py
    sys.exit(pytest.main([__file__, "-m", "live", "-s"]))
