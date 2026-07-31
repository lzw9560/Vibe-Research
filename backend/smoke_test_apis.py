# -*- coding: utf-8 -*-
"""Vibe-Research 全 API 冒烟测试（live HTTP）。
逐个调用后端端点，记录 HTTP 状态码与错误片段。
不执行破坏性写操作（持仓增删/研报上传/定时任务增删/熔断赦免等），仅测只读 + 幂等触发类。
"""
from __future__ import annotations

import json
import time

import requests

BASE = "http://127.0.0.1:8900"
TIMEOUT = 35
CODE = "600519"  # 贵州茅台

GET = "GET"
POST = "POST"
ENDPOINTS: list[tuple[str, str, str, object | None]] = [
    (GET, "/api/health", "health", None),
    (GET, "/", "root", None),
    (GET, "/docs", "docs", None),
    (GET, "/api/settings/llm-env-status", "settings/llm-env-status", None),
    (POST, "/api/chat", "chat(已知bug)", {"messages": [{"role": "user", "content": "你好"}], "model": "test", "stream": False}),
    (GET, "/api/portfolio", "portfolio", None),
    (POST, "/api/portfolio/refresh", "portfolio/refresh", None),
    (GET, "/api/watchlist", "watchlist", None),
    (GET, "/api/myreports", "myreports", None),
    (GET, "/api/radar", "radar", None),
    (GET, "/api/market/overview", "market/overview", None),
    (GET, "/api/market/emotion", "market/emotion", None),
    (GET, "/api/market/turnover-top", "market/turnover-top", None),
    (GET, "/api/global/indices", "global/indices", None),
    (GET, "/api/global/stock?symbol=AAPL", "global/stock", None),
    (GET, "/api/market/extreme", "market/extreme", None),
    (GET, "/api/indices", "indices", None),
    (GET, f"/api/quote?codes={CODE}", "quote", None),
    (GET, f"/api/valuation/percentile?code={CODE}", "valuation/percentile", None),
    (GET, f"/api/announcements?code={CODE}", "announcements", None),
    (GET, f"/api/financials?code={CODE}", "financials", None),
    (GET, f"/api/valuation?code={CODE}", "valuation", None),
    (GET, f"/api/reports?code={CODE}", "reports", None),
    (GET, f"/api/news?code={CODE}", "news", None),
    (GET, f"/api/info?code={CODE}", "info", None),
    (GET, f"/api/disclosure?code={CODE}", "disclosure", None),
    (GET, f"/api/kline?code={CODE}", "kline", None),
    (GET, f"/api/finance?code={CODE}", "finance", None),
    (GET, f"/api/stock/{CODE}/deep", "stock/deep", None),
    (GET, f"/api/margin?code={CODE}", "margin", None),
    (GET, f"/api/block-trade?code={CODE}", "block-trade", None),
    (GET, f"/api/holders?code={CODE}", "holders", None),
    (GET, f"/api/dividend?code={CODE}", "dividend", None),
    (GET, f"/api/fund-flow?code={CODE}", "fund-flow", None),
    (GET, f"/api/dragon-tiger?code={CODE}", "dragon-tiger", None),
    (GET, f"/api/lockup?code={CODE}", "lockup", None),
    (GET, f"/api/blocks?code={CODE}", "blocks", None),
    (GET, f"/api/hot-concepts?code={CODE}", "hot-concepts", None),
    (GET, f"/api/investor-qa?code={CODE}", "investor-qa", None),
    (GET, "/api/industry?top=20", "industry", None),
    (GET, "/api/limitup/metrics", "limitup/metrics", None),
    (GET, "/api/limitup/screener", "limitup/screener", None),
    (GET, "/api/limitup/screener/params", "limitup/screener/params", None),
    (GET, "/api/limitup/seats/profiles", "limitup/seats/profiles", None),
    (GET, f"/api/limitup/seats/consensus?stock_code={CODE}", "limitup/seats/consensus", None),
    (GET, "/api/limitup/auction/top", "limitup/auction/top", None),
    (GET, "/api/limitup/auction/params", "limitup/auction/params", None),
    (GET, f"/api/limitup/analysis/{CODE}", "limitup/analysis", None),
    (GET, "/api/review/daily", "review/daily", None),
    (GET, "/api/review/daily/backfill", "review/daily/backfill", None),
    (GET, "/api/review/params", "review/params", None),
    (GET, "/api/market/sti/latest", "market/sti/latest", None),
    (GET, "/api/market/sti/timeline?days=30", "market/sti/timeline", None),
    (GET, "/api/metrics/data_fetch", "metrics/data_fetch", None),
    (GET, "/api/metrics/compute", "metrics/compute", None),
    (GET, "/api/metrics/api_response", "metrics/api_response", None),
    (GET, "/api/metrics/breakdown", "metrics/breakdown", None),
    (GET, "/api/recommendation/today", "recommendation/today", None),
    (GET, f"/api/recommendation/{CODE}", "recommendation/stock", None),
    (GET, "/api/winrate/stats", "winrate/stats", None),
    (GET, "/api/winrate/adjustments", "winrate/adjustments", None),
    (GET, "/api/winrate/trends", "winrate/trends", None),
    (GET, "/api/winrate/sector/银行", "winrate/sector", None),
    (GET, "/api/winrate/strategy/打板", "winrate/strategy", None),
    (GET, "/api/backtest/scatter?start=2026-06-01&end=2026-07-29", "backtest/scatter", None),
    (GET, "/api/backtest/result?start=2026-06-01&end=2026-07-29", "backtest/result", None),
    (GET, "/api/auction/monitor", "auction/monitor", None),
    (GET, "/api/auction/watchlist", "auction/watchlist", None),
    (GET, f"/api/strategy/signals/{CODE}", "strategy/signals", None),
    (GET, "/api/strategy/registry", "strategy/registry", None),
    (GET, "/api/sector/divergence", "sector/divergence", None),
    (GET, "/api/sector/divergence/history?days=30", "sector/divergence/history", None),
    (GET, "/api/sector/rotation", "sector/rotation", None),
    (GET, "/api/risk/dashboard", "risk/dashboard", None),
    (GET, "/api/risk/oneday/list", "risk/oneday/list", None),
    (GET, "/api/risk/seats", "risk/seats", None),
    (GET, f"/api/risk/stock/{CODE}", "risk/stock", None),
    (GET, "/api/sentiment/weather/latest", "weather/latest", None),
    (GET, "/api/sentiment/weather/factors", "weather/factors", None),
    (GET, "/api/sentiment/weather/strategy", "weather/strategy", None),
    (GET, "/api/sentiment/weather/fuse", "weather/fuse", None),
    (GET, "/api/sentiment/weather/fuse/history", "weather/fuse/history", None),
    (GET, "/api/sentiment/weather/timeline?days=30", "weather/timeline", None),
    (GET, "/api/sentiment/weather/events?days=30", "weather/events", None),
    (GET, "/api/sentiment/weather/auction", "weather/auction", None),
    (GET, "/api/sentiment/weather/seal-risk", "weather/seal-risk", None),
    (GET, "/api/sentiment/weather/pardon", "weather/pardon", None),
    (GET, "/api/workflow/status", "workflow/status", None),
    (GET, "/api/workflow/pre-market", "workflow/pre-market", None),
    (GET, "/api/workflow/realtime", "workflow/realtime", None),
    (GET, "/api/workflow/intraday", "workflow/intraday", None),
    (GET, "/api/workflow/post-market", "workflow/post-market", None),
    (GET, "/api/workflow/signals", "workflow/signals", None),
    (GET, "/api/workflow/alerts", "workflow/alerts", None),
    (GET, "/api/workflow/strategies", "workflow/strategies", None),
    (GET, "/api/workflow/win-rate", "workflow/win-rate", None),
    (GET, "/api/workflow/adjustments", "workflow/adjustments", None),
    (GET, "/api/workflow/candidates", "workflow/candidates", None),
    (GET, "/api/workflow/funnel/layers", "workflow/funnel/layers", None),
    (GET, "/api/workflow/funnel/config", "workflow/funnel/config", None),
    (GET, f"/api/workflow/candidates/{CODE}/diagnosis", "workflow/candidates/diagnosis", None),
    (GET, "/api/scheduled-tasks", "scheduled-tasks", None),
    (GET, "/api/scheduled-tasks/types", "scheduled-tasks/types", None),
    (GET, "/api/kline-history/stats", "kline-history/stats", None),
    (GET, f"/api/kline-history/{CODE}", "kline-history/code", None),
]


def call(method: str, path: str, body: object | None) -> tuple[int, str, float]:
    url = BASE + path
    t0 = time.perf_counter()
    try:
        if method == GET:
            r = requests.get(url, timeout=TIMEOUT)
        else:
            r = requests.post(url, json=body, timeout=TIMEOUT)
        dt = time.perf_counter() - t0
        snippet = ""
        if not r.ok:
            try:
                snippet = str(r.json())[:200]
            except Exception:
                snippet = r.text[:200]
        return r.status_code, snippet, dt
    except requests.Timeout:
        return 0, "TIMEOUT", time.perf_counter() - t0
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"[:200], time.perf_counter() - t0


def main() -> None:
    results: list[dict] = []
    for method, path, label, body in ENDPOINTS:
        status, snippet, dt = call(method, path, body)
        ok = 200 <= status < 300
        results.append({"label": label, "method": method, "path": path,
                         "status": status, "ok": ok, "sec": round(dt, 2), "err": snippet})
        flag = "OK " if ok else "ERR"
        print(f"[{flag}] {status:>4} {method:4} {label:32} {dt:5.1f}s  {snippet[:120]}")

    total = len(results)
    ok_cnt = sum(1 for r in results if r["ok"])
    err = [r for r in results if not r["ok"]]
    print("\n" + "=" * 70)
    print(f"总计 {total} 个端点：成功 {ok_cnt}，失败/异常 {len(err)}")
    print("=" * 70)
    for r in err:
        print(f"  [{r['status']}] {r['method']} {r['label']} ({r['path']})  {r['err'][:140]}")

    with open("smoke_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n详细结果已写入 smoke_results.json")


if __name__ == "__main__":
    main()
