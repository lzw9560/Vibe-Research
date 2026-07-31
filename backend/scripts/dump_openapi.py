# -*- coding: utf-8 -*-
"""S009 T2: dump FastAPI OpenAPI schema → frontend/openapi.json（免起 uvicorn）。

供 `npm run gen:api`（openapi-typescript）消费，生成 frontend/src/lib/api/types.ts。

副作用规避：app.py 在模块级调 start_portfolio_scheduler/start_limitup_scheduler
启动调度线程。本脚本在 import app **之前** monkeypatch scheduler 模块这两个
函数为 no-op，避免 dump 期间触发后台预计算/刷新（CI 友好、无副作用）。
"""
from __future__ import annotations

import json
import os
import sys

# backend 加入 sys.path（脚本可能在 frontend/ cwd 下被 `python ../backend/scripts/dump_openapi.py` 调用）
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

REPO = os.path.dirname(BACKEND)
OUT = os.path.join(REPO, "frontend", "openapi.json")


def main() -> int:
    # 在 import app 之前禁用调度器（app.py:71-72 模块级启动）
    try:
        import scheduler as _sched  # noqa: F401
        _sched.start_portfolio_scheduler = lambda *a, **k: None  # noqa: E731
        _sched.start_limitup_scheduler = lambda *a, **k: None  # noqa: E731
    except Exception:
        pass  # scheduler 模块缺失则跳过（app import 会自身处理）

    from app import app  # noqa: F401  — 调度器已禁用，import 无后台副作用

    schema = app.openapi()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    print(f"[dump_openapi] wrote {OUT} ({len(schema.get('paths', {}))} paths, "
          f"{len(schema.get('components', {}).get('schemas', {}))} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
