"""S185 P1-3：forward_test 历史回补 27 天（07-09~08-14）。

wvaq7kuod 调研：forward_test_records 320 行/18 天（09-08~09-11）。缺 27 天（07-09~08-14）。
补到 45+ 天解锁 r3-enforce 30 天阈值。

流程：遍历缺日 → run_daily_forward_test(date, None) 写 picks+universe（INSERT OR IGNORE 幂等）
→ forward_test_t1_settle({'bulk': True}) 批量结算 baostock 历史收益。

⚠️ 不要跑 tools/forward_test_backfill.py（会 DELETE 全表丢 19 天 + backtest_samples 只到 08-14）。

用法：cd backend && .venv/bin/python tools/backfill_forward_test.py [start] [end]
默认 2026-07-09 ~ 2026-08-14（27 缺日）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datetime import date, timedelta
from vr_paths import is_trading_day

start_str = sys.argv[1] if len(sys.argv) > 1 else "2026-07-09"
end_str = sys.argv[2] if len(sys.argv) > 2 else "2026-08-14"
start = date.fromisoformat(start_str)
end = date.fromisoformat(end_str)

from strategies.forward_test import run_daily_forward_test
from scheduler.executors.backtest import forward_test_t1_settle

d = start
total_picks = 0
total_days = 0
while d <= end:
    if is_trading_day(d):
        ds = d.isoformat()
        try:
            r = run_daily_forward_test(ds, weather_state=None)
            n = r.get("recommendations", 0)
            total_picks += n
            total_days += 1
            print(f"{ds}: {n} picks", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{ds} FAIL: {type(e).__name__}: {e}", flush=True)
    d += timedelta(days=1)

print(f"\n=== Phase 1 done: {total_days} days, {total_picks} picks ===\n", flush=True)

# Phase 2: 批量结算 T+1 收益（baostock 历史 bars）
print("=== Phase 2: forward_test_t1_settle bulk ===", flush=True)
settle_result = forward_test_t1_settle({"bulk": True})
print(f"settle: {settle_result}", flush=True)
print(f"\n=== backfill done: {total_days} days, {total_picks} picks + settle {settle_result} ===", flush=True)
