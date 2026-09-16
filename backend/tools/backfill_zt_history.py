"""回补 zt_history 历史缺日——遍历 zt_history.db 已有日范围找 gap（非周末非节假日缺日），
对 gap 日调 snapshot_zt_pool（fallback 链 em→ths→hithink 自动回补）。

S184 w3pvh9q8f P0-2：em 不可回补（~14 天 rolling），ths/hithink 可（~380 天/2024-06）。
snapshot_zt_pool 已加 fallback，此脚本遍历缺日调它回补。

用法：python tools/backfill_zt_history.py [start_date] [end_date]
默认 zt_history.db 已有日范围（MIN~MAX date）。
"""
import sys
sys.path.insert(0, ".")
from data.zt_history_store import snapshot_zt_pool
from vr_paths import is_trading_day, resolve_data_dir
from datetime import date, timedelta
import sqlite3

db = resolve_data_dir() / "zt_history.db"
conn = sqlite3.connect(str(db), timeout=10)
rows = conn.execute("SELECT MIN(date), MAX(date) FROM zt_history").fetchone()
existing = {r[0] for r in conn.execute("SELECT DISTINCT date FROM zt_history")}
conn.close()

if not rows or not rows[0]:
    print("zt_history.db 空，无回补范围")
    sys.exit(0)

start_str = sys.argv[1] if len(sys.argv) > 1 else rows[0]
end_str = sys.argv[2] if len(sys.argv) > 2 else rows[1]
start = date.fromisoformat(start_str)
end = date.fromisoformat(end_str)

d = start
filled = 0
while d <= end:
    ds = d.isoformat()
    if is_trading_day(d) and ds not in existing:
        print(f"回补 {ds}...", flush=True)
        try:
            n = snapshot_zt_pool(date=ds, is_final=True)  # 历史日终盘稳定（T6 查 is_final=1，fallback 链 em→ths→hithink）
            if n > 0:
                filled += 1
                print(f"  {ds}: {n} 条", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {ds} FAIL: {type(e).__name__}: {e}", flush=True)
    d += timedelta(days=1)
print(f"回补 {filled} 天 done", flush=True)
