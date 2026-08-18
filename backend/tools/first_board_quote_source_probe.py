# -*- coding: utf-8 -*-
"""S076 首板流盘中多源行情实测探查脚本。

三源（tencent / mootdx / 东财 push2 via em_get）在盘中关键时点
（9:20-9:30 集合竞价 + 9:31-9:35 开盘采样 + 9:36 对照）的返回可用性矩阵。

零生产改动：纯探查，只读，输出 `.scratch/s076-quote-probe/matrix_{date}.json`。
spec: `specs/S076-首板流盘中多源行情实测/spec.md`

设计：
- 每源探查返回结构化 dict（raw/non_empty/sane/latency_ms/error），**记录实际返回而非假定成功**。
- mootdx 源模块（`data/sources/mootdx_src.py`）只暴露 kline/finance，不暴露实时 quote——
  本探查**直调** `mootdx.quotes.Quotes` client 的 `quotes`/`bids` 测实时；不可用即记"需接线"。
- 东财 push2 走 `em_get` 限流（不裸调），个股实时用 push2 stock/get + `_PUSH2_UT`；
  另用 `em_zt_topic_pool`（push2ex，已知可用）作 push2 通道连通性探活。
- sweep 模式：东财 push2 探测间隔 ≥10min（R6 限流约束），tencent/mootdx 每分钟。

用法：
  python -m tools.first_board_quote_source_probe --once 600127 001358
  python -m tools.first_board_quote_source_probe --sweep 600127 001358
  python -m tools.first_board_quote_source_probe --sweep-until 09:36 600127 001358
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# backend/ 加入 sys.path（astock/data import 用）
ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

REPO = Path(__file__).resolve().parents[2]  # 仓库根
OUT_DIR = REPO / ".scratch" / "s076-quote-probe"

_logger = logging.getLogger("s076_probe")

# 默认探查代码（scheduler _execute fallback；跨 4 市场：沪/深主板/创业板/科创板，测 secid + 源覆盖）
DEFAULT_CODES = ["600519", "000001", "300750", "688981"]

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# confirm 模块所需字段（探查靶子）：①竞价高开(open+last_close) ②量比 ③5分钟price采样
TENCENT_FIELDS = ["open", "last_close", "vol_ratio", "amount_wan", "price", "name", "change_pct"]

# sanity 阈值（超出标记 insane，但仍记录原值）
SANE_OPEN_PCT = (-11.0, 11.0)   # 高开 -11%~+11% 合理（涨停 +10%）
SANE_VOL_RATIO = (0.0, 30.0)     # 量比 0-30 合理（首板可高）

# 东财 push2 个股实时字段：f43=最新价 f46=开盘 f60=昨收 f50=量比 f47=成交量 f48=成交额 f57=code f58=name
EM_PUSH2_FIELDS = "f43,f46,f60,f50,f47,f48,f57,f58"
EM_PUSH2_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# 东财 push2 探测最小间隔（秒）——R6 限流约束 ≥10min
EM_PUSH2_MIN_INTERVAL_S = 600


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v) -> float | None:
    """raw 字段归一 float 或 None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _secid(code: str) -> str | None:
    """东财 secid：1.{code} 沪（60/68/9 开头）/ 0.{code} 深（00/30/12/15）。无法判定 → None。"""
    c = str(code).strip()
    if not c or not c.isdigit() or len(c) != 6:
        return None
    if c.startswith(("60", "68", "9")):
        return f"1.{c}"
    if c.startswith(("00", "30", "12", "15")):
        return f"0.{c}"
    return None


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _matrix_path() -> Path:
    return OUT_DIR / f"matrix_{_today_str()}.json"


def _truncate(s, n: int = 300) -> str:
    """raw 返回截断展示，避免巨大 JSON 污染矩阵。"""
    try:
        text = json.dumps(s, ensure_ascii=False, default=str)
    except Exception:
        text = str(s)
    return text if len(text) <= n else text[:n] + "...(truncated)"


# ─────────────────────────────────────────────────────────────────────────────
# 源探查
# ─────────────────────────────────────────────────────────────────────────────

def _probe_tencent(codes: list[str]) -> dict:
    """探查 tencent_quote。"""
    out: dict = {"source": "tencent", "ok": False, "latency_ms": None, "per_code": {}, "error": None}
    t0 = time.monotonic()
    try:
        from astock import tencent_quote
        q = tencent_quote(codes)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"tencent_quote 调用失败: {e!r}"
        return out
    out["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    out["ok"] = bool(q) and isinstance(q, dict)
    for code in codes:
        item = q.get(code) if isinstance(q, dict) else None
        if not isinstance(item, dict):
            out["per_code"][code] = {"non_empty": False}
            continue
        fields: dict = {}
        for f in TENCENT_FIELDS:
            v = item.get(f)
            fields[f] = {"val": v, "non_empty": v is not None and v != ""}
        # sanity：高开幅度 + 量比
        o = _to_float(item.get("open"))
        lc = _to_float(item.get("last_close"))
        if o is not None and lc is not None and lc > 0:
            pct = round((o - lc) / lc * 100, 2)
            fields["open_pct"] = {"val": pct, "sane": SANE_OPEN_PCT[0] <= pct <= SANE_OPEN_PCT[1]}
        vr = _to_float(item.get("vol_ratio"))
        if vr is not None:
            fields["vol_ratio"]["sane"] = SANE_VOL_RATIO[0] <= vr <= SANE_VOL_RATIO[1]
        out["per_code"][code] = fields
    return out


def _probe_mootdx(codes: list[str]) -> dict:
    """探查 mootdx 实时（直调 Quotes client quotes/bids）。

    源模块 mootdx_src 仅暴露 kline/finance，不暴露实时——本探查直调 client 测实时能力。
    API 形状不确定，故防御性：记录 raw + non_empty + error，失败即记"需接线"。
    """
    out: dict = {
        "source": "mootdx", "ok": False, "latency_ms": None, "per_code": {}, "error": None,
        "note": "源模块仅暴露 kline/finance；本探查直调 Quotes.quotes/bids 测实时",
    }
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
    except Exception as e:  # noqa: BLE001  mootdx 未装/连不上
        out["error"] = f"mootdx 不可用（未安装/连不上）: {e!r}"
        return out

    for code in codes:
        per: dict = {"quotes": {}, "bids": {}}
        # 实时 quotes
        t0 = time.monotonic()
        try:
            qt = client.quotes(symbol=code)
            per["quotes"] = {
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "raw": _truncate(qt),
                "non_empty": bool(qt) and not (hasattr(qt, "empty") and qt.empty),
            }
        except Exception as e:  # noqa: BLE001
            per["quotes"] = {"error": f"quotes 失败: {e!r}", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
        # 五档 bids
        t1 = time.monotonic()
        try:
            bd = client.bids(symbol=code)
            per["bids"] = {
                "latency_ms": round((time.monotonic() - t1) * 1000, 1),
                "raw": _truncate(bd),
                "non_empty": bool(bd) and not (hasattr(bd, "empty") and bd.empty),
            }
        except Exception as e:  # noqa: BLE001
            per["bids"] = {"error": f"bids 失败: {e!r}", "latency_ms": round((time.monotonic() - t1) * 1000, 1)}
        out["per_code"][code] = per

    out["ok"] = any(p.get("quotes", {}).get("non_empty") or p.get("bids", {}).get("non_empty")
                   for p in out["per_code"].values())
    return out


def _probe_em_push2(codes: list[str]) -> dict:
    """探查东财 push2 个股实时（via em_get 限流）+ push2ex 通道连通性。

    个股 stock/get 用 _PUSH2_UT；缺 ut 则记"ut 不可用"。
    另调 em_zt_topic_pool（push2ex，已知可用）作通道探活。
    """
    out: dict = {"source": "em_push2", "ok": False, "latency_ms": None, "per_code": {}, "channel": {}, "error": None}
    try:
        from data.transport import eastmoney_get as em_get
    except Exception as e:  # noqa: BLE001
        out["error"] = f"em_get 导入失败: {e!r}"
        return out
    try:
        from data.sources.eastmoney import _PUSH2_UT, em_zt_topic_pool
    except Exception as e:  # noqa: BLE001
        _PUSH2_UT = None  # type: ignore[assignment]
        em_zt_topic_pool = None  # type: ignore[assignment]
        out["error"] = f"_PUSH2_UT/em_zt_topic_pool 导入失败: {e!r}（个股 push2 将缺 ut）"

    headers = {"User-Agent": "Mozilla/5.0"}

    # 个股 stock/get
    t_all = time.monotonic()
    for code in codes:
        secid = _secid(code)
        per: dict = {}
        if not secid:
            out["per_code"][code] = {"error": f"无法判定 secid（code={code}）"}
            continue
        if _PUSH2_UT is None:
            out["per_code"][code] = {"error": "ut 不可用（_PUSH2_UT 缺），push2 个股实时返空/拒绝"}
            continue
        params = {
            "secid": secid, "fields": EM_PUSH2_FIELDS, "fltt": "2", "invt": "2", "ut": _PUSH2_UT,
        }
        t0 = time.monotonic()
        try:
            resp = em_get(EM_PUSH2_URL, params=params, headers=headers, timeout=10)
            data = resp.json() if resp is not None else None
            per = {
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "non_empty": bool(data),
                "raw": _truncate(data),
                # 东财 stock/get 返回 {rc, rt, data:{f43,f46,...}}；data 非空且有 f43 算可用
                "has_price": bool(data and isinstance(data, dict)
                                  and data.get("data") and isinstance(data["data"], dict)
                                  and data["data"].get("f43") is not None),
            }
        except Exception as e:  # noqa: BLE001
            per = {"error": f"push2 stock/get 失败: {e!r}", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
        out["per_code"][code] = per
    out["latency_ms"] = round((time.monotonic() - t_all) * 1000, 1)

    # push2ex 通道连通性（em_zt_topic_pool 已知可用，测 9:25 时点是否响应）
    if em_zt_topic_pool is not None:
        today = _today_str()
        t1 = time.monotonic()
        try:
            pool = em_zt_topic_pool("getTopicZTPool", today, "fbt:asc")
            out["channel"] = {
                "endpoint": "push2ex/getTopicZTPool",
                "latency_ms": round((time.monotonic() - t1) * 1000, 1),
                "non_empty": bool(pool),
                "count": len(pool) if isinstance(pool, list) else 0,
                "note": "9:25 盘前涨停池可能为空（当日未生成），count=0 不代表通道宕",
            }
        except Exception as e:  # noqa: BLE001
            out["channel"] = {"endpoint": "push2ex/getTopicZTPool", "error": f"通道探活失败: {e!r}"}

    out["ok"] = any(p.get("has_price") for p in out["per_code"].values()) or out["channel"].get("non_empty", False)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 聚合 + 落盘
# ─────────────────────────────────────────────────────────────────────────────

def probe_once(codes: list[str], sources: list[str] | None = None) -> dict:
    """一次探查所有源，返回一行 {timestamp, time, sources...}。"""
    srcs = sources or ["tencent", "mootdx", "em_push2"]
    row: dict = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "time": _now_str(),
    }
    if "tencent" in srcs:
        row["tencent"] = _probe_tencent(codes)
    if "mootdx" in srcs:
        row["mootdx"] = _probe_mootdx(codes)
    if "em_push2" in srcs:
        row["em_push2"] = _probe_em_push2(codes)
    return row


def _load_matrix() -> dict:
    """读现有矩阵（append 模式）；不存在返新壳。"""
    p = _matrix_path()
    if not p.exists():
        return {"date": _today_str(), "rows": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        _logger.warning("矩阵读取失败（将重建）: %s", e)
        return {"date": _today_str(), "rows": []}


def _append_row(row: dict) -> Path:
    """追加一行到矩阵 JSON（immutable：读全量→append→写全量）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matrix = _load_matrix()
    matrix["date"] = _today_str()
    matrix.setdefault("rows", []).append(row)
    path = _matrix_path()
    path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def sweep(codes: list[str], until_hhmm: str | None = None) -> None:
    """循环探查至 until_hhmm（HH:MM）或 Ctrl-C。

    tencent/mootdx 每 60s；东财 push2 间隔 ≥ EM_PUSH2_MIN_INTERVAL_S（R6 限流）。
    """
    last_push2_ts: float = 0.0
    _logger.info("sweep 开始 codes=%s until=%s", codes, until_hhmm or "Ctrl-C")
    try:
        while True:
            now = datetime.now()
            if until_hhmm:
                try:
                    hh, mm = (int(x) for x in until_hhmm.split(":"))
                    if now.hour > hh or (now.hour == hh and now.minute >= mm):
                        _logger.info("到达 %s，sweep 结束", until_hhmm)
                        break
                except (ValueError, AttributeError):
                    _logger.warning("until_hhmm 格式错（应为 HH:MM），忽略: %s", until_hhmm)

            srcs = ["tencent", "mootdx"]
            if time.monotonic() - last_push2_ts >= EM_PUSH2_MIN_INTERVAL_S:
                srcs.append("em_push2")
                last_push2_ts = time.monotonic()

            row = probe_once(codes, sources=srcs)
            path = _append_row(row)
            _logger.info("[%s] 探查完成 srcs=%s → %s", row["time"], srcs, path.name)

            # 下一次：对齐到下一整分钟
            time.sleep(max(0.0, 60 - now.second))
    except KeyboardInterrupt:
        _logger.info("Ctrl-C，sweep 退出")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="S076 首板流盘中多源行情实测探查")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="探查一次（当前时点，所有源）")
    g.add_argument("--sweep", action="store_true", help="循环探查至 Ctrl-C（东财 push2 ≥10min）")
    g.add_argument("--sweep-until", metavar="HH:MM", help="循环探查至 HH:MM（东财 push2 ≥10min）")
    p.add_argument("codes", nargs="+", help="6 位股票代码（空格分隔）")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    codes = [c.strip() for c in args.codes if c.strip()]
    if args.once:
        row = probe_once(codes)
        path = _append_row(row)
        _logger.info("[once][%s] 完成 → %s", row["time"], path)
        _logger.info("摘要: %s", json.dumps({
            "tencent_ok": row["tencent"].get("ok"),
            "mootdx_ok": row["mootdx"].get("ok"),
            "em_push2_ok": row["em_push2"].get("ok"),
        }, ensure_ascii=False))
    elif args.sweep or args.sweep_until:
        sweep(codes, args.sweep_until)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
