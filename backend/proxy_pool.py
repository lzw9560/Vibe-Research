# -*- coding: utf-8 -*-
"""S070/数据层加固：免费代理池（fetch + health-check + rotate）。

目的：绕过东财 push2his 的 IP-限流（限流是 IP 特定，代理是 fresh IP 可绕过）。
免费代理 flaky + 对东财（CN 站）多数不通——health-check 过滤能到 push2his 的。
验证可用后才接 transport.py em_get（池作 direct→系统代理 之后的 fallback）。

- fetch_free_proxies(): 从 proxyscrape 免费 API 拉 list。
- health_check_pool(): 测每个代理能否到 push2his（返 klines）——过滤可用的。
- get_proxy(): 轮换可用代理。
- 缓存可用池到 .vibe-research/proxy_pool.json（health-check 慢，缓存复用）。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

from config import GENE_SCORES_DB_PATH  # noqa: F401（仅确保 backend 在 path）
from vr_paths import resolve_data_dir

logger = logging.getLogger(__name__)
_POOL_CACHE = Path(resolve_data_dir()) / "proxy_pool.json"
_PUSH2HIS_TEST = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_TEST_PARAMS = {"secid": "1.600519", "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "lmt": "5", "ut": "fa5fd1943c7b386f172d6893dbbd1"}
_TEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def fetch_free_proxies(limit: int = 100) -> list[str]:
    """从 proxyscrape 免费 API 拉 http 代理列表（'ip:port'）。失败返空。"""
    try:
        r = requests.get(
            "https://api.proxyscrape.com/v2/",
            params={"request": "getproxies", "protocol": "http", "timeout": 5000,
                    "country": "all", "ssl": "all", "anonymity": "all"},
            timeout=15,
        )
        if r.status_code == 200 and r.text.strip():
            lst = [p.strip() for p in r.text.strip().splitlines() if p.strip()]
            return lst[:limit]
    except Exception as e:
        logger.warning("[proxy_pool] fetch 失败: %s", e)
    return []


def _proxy_ok(proxy: str, timeout: float = 8.0) -> bool:
    """测 proxy 能否到 push2his 并返 klines（非空）。"""
    try:
        r = requests.get(_PUSH2HIS_TEST, params=_TEST_PARAMS, headers=_TEST_HEADERS,
                         proxies={"http": f"http://{proxy}", "https": f"http://{proxy}"},
                         timeout=timeout)
        if r.status_code != 200:
            return False
        d = r.json()
        kl = (d.get("data") or {}).get("klines", [])
        return len(kl) > 0  # 能到 push2his 且返数据（代理 IP 未被东财封）
    except Exception:
        return False


def health_check_pool(proxies: list[str], sample: int = 30) -> list[str]:
    """health-check 一批代理（sample 降量），返能到 push2his 的。慢（每代理一次请求）。"""
    to_check = proxies[:sample] if len(proxies) > sample else proxies
    working = []
    for i, p in enumerate(to_check):
        if _proxy_ok(p):
            working.append(p)
            print(f"  [{i+1}/{len(to_check)}] ✓ {p}", flush=True)
        # 静默跳过失败的（多数会失败，不刷屏）
    return working


def build_pool(sample: int = 30) -> list[str]:
    """拉 + health-check + 缓存可用池。返可用代理 list（可能空——免费代理对东财多数不通）。"""
    print(f"[proxy_pool] 拉 free 代理...")
    proxies = fetch_free_proxies(limit=100)
    print(f"[proxy_pool] fetched {len(proxies)}，health-check sample {min(sample, len(proxies))}...")
    working = health_check_pool(proxies, sample=sample)
    print(f"[proxy_pool] working（能到 push2his）: {len(working)}")
    try:
        _POOL_CACHE.write_text(json.dumps(working, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return working


def load_pool() -> list[str]:
    """读缓存的可用池。"""
    try:
        return json.loads(_POOL_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_proxy() -> Optional[str]:
    """轮换取一个可用代理（round-robin，无则 None）。"""
    pool = load_pool()
    if not pool:
        return None
    # 简单 round-robin（用时间作 index，无状态）
    idx = int(time.time()) % len(pool)
    return pool[idx]


def fetch_fund_flow_via_pool(code: str, lmt: int = 120) -> list[dict]:
    """经代理池拉个股资金流（push2his fflow/daykline，lmt 日）。代理轮换 + 失败换下一个。

    返 [{date, main_net, small_net, mid_net, large_net, super_net}]（同 stock_fund_flow_120d 口径）。
    池空/全失败 → []（调用方降级）。绕本机 IP-限流（代理是 fresh IP）。
    """
    pool = load_pool()
    if not pool:
        return []
    market_code = 1 if code.startswith("6") else 0
    params = {"secid": f"{market_code}.{code}", "fields1": "f1,f2,f3,f7",
              "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
              "lmt": str(lmt), "ut": "fa5fd1943c7b386f172d6893dbbd1"}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    for p in pool:  # 轮换试每个代理
        try:
            r = requests.get(url, params=params, headers=headers,
                             proxies={"http": f"http://{p}", "https": f"http://{p}"},
                             timeout=12)
            if r.status_code != 200:
                continue
            d = r.json()
            kl = (d.get("data") or {}).get("klines", [])
            rows = []
            for line in kl:
                pp = line.split(",")
                if len(pp) >= 6:
                    def _f(x):
                        try:
                            return float(x) if x not in ("-", "") else 0.0
                        except ValueError:
                            return 0.0
                    rows.append({"date": pp[0], "main_net": _f(pp[1]), "small_net": _f(pp[2]),
                                 "mid_net": _f(pp[3]), "large_net": _f(pp[4]), "super_net": _f(pp[5])})
            if rows:
                return rows
        except Exception:
            continue  # 该代理失败，换下一个
    return []


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30, help="health-check 样本数")
    a = ap.parse_args()
    raise SystemExit(0 if build_pool(a.sample) else 1)
