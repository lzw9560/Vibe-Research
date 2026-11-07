"""ETF-specific: ETF-tradable signal, premium as predictor, broad vs sector divergence."""

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
import json
import sys
from pathlib import Path
from datetime import datetime
from statistics import mean, median, stdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

CACHE = str(resolve_data_dir())
with open(f"{CACHE}/index_ohlc_cache.json") as f:
    idx = json.load(f)
with open(f"{CACHE}/etf_premium_cache.json") as f:
    etf = json.load(f)
sh = idx["sh.000001"]
dates = [r["date"] for r in sh]
by_date = {r["date"]: r for r in sh}

holiday_gaps = []
for i in range(1, len(dates)):
    d0 = datetime.strptime(dates[i - 1], "%Y-%m-%d")
    d1 = datetime.strptime(dates[i], "%Y-%m-%d")
    if (d1 - d0).days >= 7:
        holiday_gaps.append({"last_pre": dates[i - 1], "first_post": dates[i], "i_last": i - 1, "year": d0.year})


def st(v):
    v = [x for x in v if x is not None]
    if not v:
        return "n=0"
    return {
        "n": len(v),
        "mean": round(mean(v), 4),
        "med": round(median(v), 4),
        "wr": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
    }


# ---------- 1. ETF-TRADABLE signal: buy ETF open(il-1) sell close(il) ----------
broad = {
    "510300": "沪深300ETF",
    "510050": "上证50ETF",
    "510500": "中证500ETF",
    "159901": "深证100",
    "512100": "中证1000",
    "588000": "科创50",
    "159915": "创业板ETF",
}
dividend = {"510880": "红利ETF", "512890": "红利低波"}
sector = {"512760": "芯片ETF", "159995": "芯片ETF2", "515790": "光伏ETF", "512660": "军工ETF"}


def etf_sig_ret(code, g):
    il = g["i_last"]
    d_buy = dates[il - 1] if il - 1 >= 0 else None
    d_sell = dates[il] if il < len(dates) else None
    if not d_buy or not d_sell:
        return None
    rb = etf.get(code, {}).get(d_buy)
    rs = etf.get(code, {}).get(d_sell)
    if not rb or not rs:
        return None
    bo = rb.get("open")
    sc = rs.get("close")
    if bo is None or sc is None or bo == 0:
        return None
    return (sc / bo - 1) * 100


print("=== ETF-tradable PRE-holiday signal (buy open(il-1) sell close(il)) ===")
print("--- Broad ETFs ---")
for code, name in broad.items():
    rs = [etf_sig_ret(code, g) for g in holiday_gaps]
    rs = [r for r in rs if r is not None]
    print(f"{code} {name:12}: {st(rs)}")
print("--- Dividend/low-vol ---")
for code, name in dividend.items():
    rs = [etf_sig_ret(code, g) for g in holiday_gaps]
    rs = [r for r in rs if r is not None]
    print(f"{code} {name:12}: {st(rs)}")
print("--- Sector ETFs ---")
for code, name in sector.items():
    rs = [etf_sig_ret(code, g) for g in holiday_gaps]
    rs = [r for r in rs if r is not None]
    print(f"{code} {name:12}: {st(rs)}")


# broad average vs sector average per holiday
def broad_avg(g):
    rs = [etf_sig_ret(c, g) for c in broad]
    rs = [r for r in rs if r is not None]
    return mean(rs) if rs else None


def sector_avg(g):
    rs = [etf_sig_ret(c, g) for c in sector]
    rs = [r for r in rs if r is not None]
    return mean(rs) if rs else None


ba = [broad_avg(g) for g in holiday_gaps]
sa = [sector_avg(g) for g in holiday_gaps]
print(f"\nBroad-avg signal: {st(ba)}")
print(f"Sector-avg signal: {st(sa)}")


# ---------- 2. ETF premium as predictor of index signal ----------
def idx_sig(g):
    il = g["i_last"]
    if il - 1 < 0 or il >= len(dates):
        return None
    bo = by_date[dates[il - 1]]["open"]
    sc = by_date[dates[il]]["close"]
    return (sc / bo - 1) * 100


def prem(code, d):
    r = etf.get(code, {}).get(d)
    if not r:
        return None
    nav = r.get("nav")
    cl = r.get("close")
    if not nav:
        return None
    return (cl / nav - 1) * 100


# premium on T-3 (3 days before last) as predictor
print("\n=== Premium at T-3 as predictor of index signal return ===")
for code, name in [("510300", "沪深300"), ("510050", "上证50"), ("512890", "红利低波"), ("159915", "创业板")]:
    pairs = []
    for g in holiday_gaps:
        il = g["i_last"]
        if il - 3 < 0:
            continue
        p = prem(code, dates[il - 3])
        s = idx_sig(g)
        if p is not None and s is not None:
            pairs.append((p, s))
    if len(pairs) < 5:
        print(f"{code}: n too small")
        continue
    hi = [s for p, s in pairs if p > 0]
    lo = [s for p, s in pairs if p <= 0]
    rs = [s for _, s in pairs]
    ps = [p for p, _ in pairs]
    mr = mean(rs)
    mp = mean(ps)
    cov = sum((s - mr) * (p - mp) for p, s in pairs) / len(pairs)
    vr = sum((s - mr) ** 2 for _, s in pairs) / len(pairs) or 1
    vm = sum((p - mp) ** 2 for _, p in pairs) / len(pairs) or 1
    corr = cov / (vr**0.5 * vm**0.5) if vr > 0 and vm > 0 else 0
    print(
        f"{code} {name}: corr(premT-3,sig)={corr:+.3f} | prem>0 n={len(hi)} sig={st(hi)} | prem<=0 n={len(lo)} sig={st(lo)}"
    )

# ---------- 3. broad vs sector premium divergence as risk-appetite regime ----------
print("\n=== Broad-sector premium divergence (risk appetite proxy) ===")
divs = []
for g in holiday_gaps:
    il = g["i_last"]
    if il - 3 < 0:
        continue
    bp = [prem(c, dates[il - 3]) for c in ["510300", "510050", "510500"]]
    sp = [prem(c, dates[il - 3]) for c in ["512760", "159995", "515790", "512660"]]
    bp = [x for x in bp if x is not None]
    sp = [x for x in sp if x is not None]
    if not bp or not sp:
        continue
    div = mean(bp) - mean(sp)
    s = idx_sig(g)
    if s is not None:
        divs.append((div, s))
print(f"n={len(divs)}")
rs = [s for _, s in divs]
ds = [d for d, _ in divs]
mr = mean(rs)
md = mean(ds)
cov = sum((s - mr) * (d - md) for d, s in divs) / len(divs)
vr = sum((s - mr) ** 2 for _, s in divs) / len(divs) or 1
vm = sum((d - md) ** 2 for _, d in divs) / len(divs) or 1
print(f"corr(divergence, signal)={cov / (vr**0.5 * vm**0.5) if vr > 0 and vm > 0 else 0:+.3f}")
hi = [s for d, s in divs if d > 0]
lo = [s for d, s in divs if d <= 0]
print(f"broad>sector (risk-on): n={len(hi)} sig={st(hi)}")
print(f"broad<=sector (risk-off): n={len(lo)} sig={st(lo)}")
