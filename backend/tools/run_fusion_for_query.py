#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4.2 全链路 demo：给 stock+date 跑信号融合 → fusion_output + context 文本。

实际逻辑在 engine/fusion_pipeline.py（feishu_bot 生产也用同一函数）。
本脚本仅 demo 验证链路 + 打印 context 文本。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.fusion_pipeline import compute_fusion_for_query  # noqa: E402
from engine.fusion_layer import build_fusion_context  # noqa: E402


def main() -> None:
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    date = sys.argv[2] if len(sys.argv) > 2 else None  # None → 最新交易日
    out = compute_fusion_for_query(stock, date)
    import json
    print(f"=== {stock} @ {date or '最新日'} fusion_output ===")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"\n=== build_fusion_context（注入 chat.run_chat 的 system prompt）===")
    print(build_fusion_context(out))


if __name__ == "__main__":
    main()
