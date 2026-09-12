# -*- coding: utf-8 -*-
"""stoke skill 调用 wrapper（不重启 CC 激活 stoke 的方式）。

stoke skill 装在 ~/stoke（symlink ~/.claude/skills/stoke），但当前会话未加载。
通过设 STOKE_HOME + 走 ~/stoke/.venv/bin/python 直接调，等效激活。

用法（项目/会话直接调）：
  STOKE_HOME=~/stoke ~/stoke/.venv/bin/python -c "from stoke.sources.mootdx_source import MootdxSource; ..."
  或本 wrapper：python tools/stoke_wrapper.py --realtime 000001,600000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 设 STOKE_HOME + 用 stoke venv（本脚本需 ~/stoke/.venv/bin/python 跑）
os.environ.setdefault("STOKE_HOME", str(Path.home() / "stoke"))


def _mootdx_realtime(codes: list[str]) -> dict:
    """实时五档盘口（mootdx TCP，交易日盘中有效，盘后/非交易日返空）。"""
    from stoke.sources.mootdx_source import MootdxSource  # noqa: PLC0415
    m = MootdxSource()
    if not m.health_check():
        return {"note": "mootdx 连通失败（盘后/非交易日/服务器配置），实时五档需交易日盘中测"}
    df = m.get_realtime(codes)
    return {"codes": codes, "data": df.to_dict(orient="records") if len(df) else []}


def _mootdx_kline(code: str) -> dict:
    """日 K 线（800 条）。"""
    from stoke.sources.mootdx_source import MootdxSource  # noqa: PLC0415
    m = MootdxSource()
    df = m.get_kline(code)
    return {"code": code, "n_bars": len(df), "data": df.to_dict(orient="records") if len(df) else []}


def main() -> None:
    p = argparse.ArgumentParser(description="stoke skill wrapper（不重启激活）")
    p.add_argument("--realtime", default=None, help="实时五档，codes 逗号分隔")
    p.add_argument("--kline", default=None, help="日 K，单 code")
    args = p.parse_args()

    if args.realtime:
        codes = [c.strip() for c in args.realtime.split(",") if c.strip()]
        print(json.dumps(_mootdx_realtime(codes), indent=2, ensure_ascii=False, default=str))
    elif args.kline:
        print(json.dumps(_mootdx_kline(args.kline), indent=2, ensure_ascii=False, default=str))
    else:
        p.error("需 --realtime 或 --kline")


if __name__ == "__main__":
    main()
