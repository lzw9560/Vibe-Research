"""S073 §5.4 概念维度缓存构建——涨停股 × concept_blocks → concept_map_cache.json。

跑：.venv/bin/python tools/build_concept_map.py [date YYYY-MM-DD]
默认用最新交易日（gene_scores max date）。
build 后 multi_rotation 加维度3（概念，国产芯片/通信技术），不阻塞（用缓存）。
concept_blocks 走东财 slist（非 push2his，不 IP 限流），但 per 股慢（106 请求 ~2min）。
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vr_paths import resolve_data_dir
from astock import ths_limit_up_pool, concept_blocks

_DB = resolve_data_dir() / "gene_scores.db"
_CACHE = resolve_data_dir() / "concept_map_cache.json"


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else None
    if not date:
        conn = sqlite3.connect(str(_DB))
        date = conn.execute("SELECT max(date) FROM gene_scores").fetchone()[0]
        conn.close()
    print(f"=== build concept_map @ {date} ===")
    pool = ths_limit_up_pool(date.replace("-", ""))
    if not pool:
        print(f"❌ ths_limit_up_pool {date} 返空（同花顺源不可达）")
        return
    print(f"涨停股: {len(pool)}")

    concept_map: dict[str, list[str]] = {}
    # 保留旧缓存（concept 归属静态，涨停股每日变，合并）
    if _CACHE.exists():
        try:
            concept_map = json.loads(_CACHE.read_bytes())
        except Exception:
            concept_map = {}

    for i, item in enumerate(pool):
        code = item.get("code", "")
        if not code or code in concept_map:
            continue
        try:
            cb = concept_blocks(code)
            tags = cb.get("concept_tags") or []
            if tags:
                concept_map[code] = tags
        except Exception:
            continue
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(pool)}] {code}: {len(concept_map.get(code, []))} 概念")

    _CACHE.write_text(json.dumps(concept_map, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ concept_map 缓存: {len(concept_map)} 股 → {_CACHE}")
    print(f"multi_rotation 下次调用自动加载（维度3 概念）")


if __name__ == "__main__":
    main()
