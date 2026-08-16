#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S066 Q16 回填：clist f100 → code_industry → gene_scores.industry + backtest_samples.json。

§5.3 实现路径 step 1（grill Q16 实测验证后的修正路径）。一次性脚本，幂等可重跑。

合规（CLAUDE.md §1.2 工程底线）：
- 走 em_get（eastmoney_get）限流/熔断/代理回退，不裸调 requests（防封 IP）；
- industry 全来自东财 clist f100 实测字段，不臆造、不心算；
- 只写 .vibe-research/ 内的私有库（gene_scores.db / backtest_samples.json），不进 git。

用法：cd backend && ../.venv/bin/python tools/backfill_industry.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# 脚本在 backend/tools/，直接跑时 backend/ 不在 sys.path——手动注入以 import config/data
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import GENE_SCORES_DB_PATH
from data.sources.eastmoney import UA
from data.transport import eastmoney_get as em_get  # 防封底线：走限流/熔断/代理

# 沪深京 A 股段（同 market_turnover_rank，全市场覆盖）
_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
_FIELDS = "f12,f14,f100"  # code / name / industry —— 只取回填所需字段，控 payload
# 实测（2026-08-16）：push2 当前 RemoteDisconnected 不可用；push2delay 可用但**每页封顶 100**
# （pz>100 仍只返 100）、且**必须带 np=1**（不带则返异常结构）。total=5896 → 59 页×0.15s。
# 注：§5.3 原记"约 12 页"系 push2 大页估计；push2 不可用时按 100/页分页。
_HOSTS = ("push2delay.eastmoney.com", "push2.eastmoney.com")  # delay 优先（push2 当前断连）
_PZ = 100  # push2delay 每页封顶 100
_PAGE_SLEEP = 0.15  # 限流友好
_MAX_PAGES = 65  # 5896/100≈59 + 兜底

_SAMPLES_JSON = Path(GENE_SCORES_DB_PATH).parent / "backtest_samples.json"


def _fetch_page(pn: int) -> list[dict]:
    """拉一页 clist，push2→push2delay 回退；返 diff list（空则 []）。"""
    params = {"pn": pn, "pz": _PZ, "po": 1, "np": 1, "fltt": 2, "invt": 2,
              "fid": "f6", "fs": _FS, "fields": _FIELDS}
    for host in _HOSTS:
        try:
            r = em_get(f"https://{host}/api/qt/clist/get", params=params,
                       headers={"User-Agent": UA}, timeout=12)
            diff = (r.json().get("data") or {}).get("diff") or []
            if diff:
                return diff
        except Exception:
            continue
    return []


def fetch_all_industries() -> list[dict]:
    """分页拉全市场 code→industry，去重。"""
    out: list[dict] = []
    seen: set[str] = set()
    for pn in range(1, _MAX_PAGES + 1):
        diff = _fetch_page(pn)
        if not diff:
            break
        for d in diff:
            code = str(d.get("f12", "")).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({"code": code, "name": d.get("f14", ""),
                        "industry": d.get("f100", "") or ""})
        if len(diff) < _PZ:
            break
        time.sleep(_PAGE_SLEEP)
    return out


def upsert_code_industry(conn: sqlite3.Connection, rows: list[dict]) -> int:
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO code_industry (code, name, industry, updated_at) VALUES (?,?,?,?)",
        [(r["code"], r["name"], r["industry"], now) for r in rows],
    )
    return len(rows)


def backfill_gene_scores(conn: sqlite3.Connection) -> tuple[int, int]:
    """用 code_industry 回填 gene_scores.industry。返 (总行, 命中行)。"""
    total = conn.execute("SELECT COUNT(*) FROM gene_scores").fetchone()[0]
    conn.execute("""
        UPDATE gene_scores SET industry = COALESCE(
            (SELECT ci.industry FROM code_industry ci WHERE ci.code = gene_scores.code),
            ''
        )
    """)
    hit = conn.execute(
        "SELECT COUNT(*) FROM gene_scores WHERE industry IS NOT NULL AND industry != ''"
    ).fetchone()[0]
    return total, hit


def backfill_samples_json(code2industry: dict[str, str]) -> int:
    """backtest_samples.json 的 samples[] 按 code 补 industry 字段。返补条数。"""
    if not _SAMPLES_JSON.exists():
        return 0
    data = json.loads(_SAMPLES_JSON.read_text(encoding="utf-8"))
    samples = data.get("samples") or []
    n = 0
    for s in samples:
        ind = code2industry.get(s.get("code", ""))
        if ind:
            s["industry"] = ind
            n += 1
    _SAMPLES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="S066 Q16 板块 industry 回填")
    ap.add_argument("--dry-run", action="store_true", help="只拉 clist 不写库（验网络+覆盖")
    args = ap.parse_args()

    rows = fetch_all_industries()
    hit = sum(1 for r in rows if r["industry"])
    print(f"clist 拉到 {len(rows)} 只，industry 非空 {hit}/{len(rows)}")
    if not rows:
        print("⚠️ 未拉到任何数据——em_get 网络/限流问题，库未改动。")
        return
    if args.dry_run:
        return

    code2industry = {r["code"]: r["industry"] for r in rows}
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        n_ci = upsert_code_industry(conn, rows)
        conn.commit()
        total, hit_gs = backfill_gene_scores(conn)
        conn.commit()
        print(f"code_industry 写 {n_ci} 条；gene_scores 回填 {hit_gs}/{total} 行命中 industry")
    finally:
        conn.close()
    ns = backfill_samples_json(code2industry)
    print(f"backtest_samples.json samples[] 补 {ns} 条 industry")
    print("✓ 回填完成。板块阶段计算（§5.3 step 3 / tasks 032-039）为下游任务。")


if __name__ == "__main__":
    main()
