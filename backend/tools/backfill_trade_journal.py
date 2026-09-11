"""回补历史 trade_journal——遍历历史交易日调 _process_*（不 settle，避免重算旧 hold 慢）。

快速验证 S183 曲线（替代日后积累）。用历史 bars（cache + baostock fallback）回填
breakout/floor/trend 记录 + net_pnl。确定性 signal_id（arm_date_code）INSERT OR REPLACE 幂等。

用法：python tools/backfill_trade_journal.py [start_date] [end_date]
默认 2026-09-01 ~ 2026-09-10。
"""
import sys
sys.path.insert(0, ".")
from strategies.journal_recorder import JournalRecorder
from engine.bars_provider import KlineCacheBarsProvider
from vr_paths import is_trading_day
from datetime import date, timedelta

start_str = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
end_str = sys.argv[2] if len(sys.argv) > 2 else "2026-09-10"
start = date.fromisoformat(start_str)
end = date.fromisoformat(end_str)

bp = KlineCacheBarsProvider()
rec = JournalRecorder(bars_provider=bp)

d = start
total = 0
while d <= end:
    if is_trading_day(d):
        ds = d.isoformat()
        try:
            r_b = rec._process_breakout(ds)
            r_f = rec._process_floor(ds)
            r_t = rec._process_trend(ds)
            print(f"{ds}: breakout buyable={r_b.get('n_buyable')} unbuyable={r_b.get('n_unbuyable')} | floor buyable={r_f.get('n_buyable')} | trend buyable={r_t.get('n_buyable')}", flush=True)
            total += 1
        except Exception as e:  # noqa: BLE001
            print(f"{ds} FAIL: {type(e).__name__}: {e}", flush=True)
    d += timedelta(days=1)
print(f"回补 {total} 天 done", flush=True)
