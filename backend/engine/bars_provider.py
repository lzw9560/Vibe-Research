# -*- coding: utf-8 -*-
"""S175 R1 — composite bars_provider：A股 cache + ETF fetch_etf_hist 双源。

**grill C1 fix**：kline cache 是 stock-only（python 实测 5226 个 key 全 000xxx 股票，
512890/510300/510050/510310 全 False）→ floor 用 cache 取价返 [] → unrealized_pnl
恒 None。bars_provider composite dispatch by code 类型：

- A股 code（60/00/30/688 开头）→ 读 baostock_kline_cache.json（OHLC bars，breakout
  path_return 用 open/high/low/close）
- ETF code（51/15 开头）→ fetch_etf_hist（akshare qfq [{date,close,ret}]，floor
  MTM 用 close）

journal_recorder 注入此 provider 替代默认 `lambda _code: []`（BREAK-2 修复）。

**路径**：用 `vr_paths.resolve_data_dir()` 不硬编（premarket_selection.py:28 硬编
`ROOT.parent/.vibe-research/...` 忽略 VR_DATA_DIR，测试会写穿生产 cache；本模块
走 canonical resolve_data_dir 防 home 分裂 + 测试隔离）。

**重算范式（S088）**：模块级 _cache 懒加载，`reload()` 清 cache 供 kline_refresh
后重读。不读结果 cache（_CACHE 是 raw bars 缓存非聚合结果）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from vr_paths import resolve_data_dir

_logger = logging.getLogger(__name__)

#: 模块级 raw bars cache（懒加载，reload() 清空）
_CACHE: dict[str, list[dict]] | None = None


def _load_cache() -> dict[str, list[dict]]:
    """读 baostock_kline_cache.json（resolve_data_dir），缺失/损坏返空 dict 不崩。

    降级范式对齐 first_board_filter（memory fallback-empty-write-corrupts）：
    cache 缺失/损坏不阻塞生产，返空让 bars_provider 调用方（journal_recorder）
    跳过该 code（`if not bars: continue`，journal_recorder.py:137）。
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = resolve_data_dir() / "baostock_kline_cache.json"
    if not path.exists():
        _logger.warning("bars_provider: kline cache 缺失 path=%s，A股 bars 降级返空", path)
        _CACHE = {}
        return _CACHE
    try:
        data = json.loads(path.read_bytes())
        if not isinstance(data, dict):
            _logger.warning("bars_provider: kline cache 非 dict (%s)，降级返空", type(data).__name__)
            _CACHE = {}
        else:
            _CACHE = data
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("bars_provider: kline cache 损坏 %s，降级返空", e)
        _CACHE = {}
    return _CACHE


def _is_etf(code: str) -> bool:
    """ETF/基金代码：shanghai 51xxxx（510-519）/ shenzhen 159xxx-150xxx。

    A股股票代码 60xxxx（沪）/ 00xxxx·30xxxx·688xxx（深/创/科创）均不匹配。
    floor ETF 512890 命中 51 前缀走 fetch_etf_hist 分支。
    """
    return code.startswith(("51", "15"))


def _baostock_etf_hist(code: str) -> list[dict]:
    """baostock ETF 历史（sh.512890 / sz.159xxx）—— 东财 push2delay 历史端点挂时的备选源。

    baostock 不封 IP（vs 东财 push2delay 连接被拒），支持 ETF/fund 代码 + qfq 前复权。
    实测 512890 返 09-08/09-09 bar（kline cache stale 缺这两天时可用）。
    返 [{date, open, high, low, close}]；失败返 []。
    """
    try:
        import baostock as bs  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415
    except ImportError:
        _logger.warning("bars_provider: baostock 不可用，ETF %s baostock fallback 跳过", code)
        return []
    # code format: 51xxxx → sh.51xxxx, 15xxxx → sz.15xxxx
    prefix = "sh." if code.startswith("5") else "sz."
    bs_code = prefix + code
    try:
        bs.login()
        end = datetime.now().strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(
            bs_code, "date,open,high,low,close",
            start_date="2020-01-01", end_date=end,
            frequency="d", adjustflag="2",  # 2=qfq 前复权
        )
        if rs.error_code != "0":
            _logger.warning("bars_provider: baostock ETF %s query 失败: %s", code, rs.error_msg)
            return []
        rows: list[dict] = []
        while (rs.error_code == "0") and rs.next():
            d = rs.get_row_data()
            try:
                rows.append({
                    "date": str(d[0]),
                    "open": float(d[1]), "high": float(d[2]),
                    "low": float(d[3]), "close": float(d[4]),
                })
            except (TypeError, ValueError, IndexError):
                continue
        return rows
    except Exception as e:  # noqa: BLE001
        _logger.warning("bars_provider: baostock ETF %s 异常: %s", code, e)
        return []
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass


class KlineCacheBarsProvider:
    """composite bars_provider——journal_recorder 注入的生产 bars 源。

    调用签名 ``provider(code) -> list[dict]``，每 bar 至少含 ``close``
    （journal_recorder._latest_close 用）；A股 bar 另含 open/high/low
    （path_return stop/take gap-through 用）。

    用法（生产接线，scheduler/executors/journal.py）::

        from engine.bars_provider import KlineCacheBarsProvider
        recorder = JournalRecorder(bars_provider=KlineCacheBarsProvider())
    """

    def __call__(self, code: str) -> list[dict]:
        if _is_etf(code):
            return self._etf_bars(code)
        return _load_cache().get(code, [])

    @staticmethod
    def _etf_bars(code: str) -> list[dict]:
        """ETF 历史复权净值收益（akshare fund_etf_hist_em qfq）+ 规范化补 open/high/low。

        惰性导入 akshare（重依赖，不挡启动）。取数失败返 []（fetch_etf_hist
        内部已 try/except，此处再防 ImportError）。

        **baostock fallback（S175 live 验证发现东财 push2delay 历史端点 Connection aborted）**：
        fetch_etf_hist 返空时（东财端点挂/IP 封），fallback baostock（不封 IP，支持 ETF qfq）。

        **规范化（spec grill SH6）**：fetch_etf_hist 返 [{date, close, ret}] 无
        'open' 键——Executor T1OpenFill 读 bars[idx+1]['open']（fill_policies.py:78，
        _bar_get 默认返 0.0）→ entry_f=0.0 → 全 unbuyable → floor 拿不到 MTM 记录。
        ETF 净值口径四价相等（无日内波动，open=high=low=close），规范化补 open/high/low。
        baostock 已含 open/high/low，规范化只补缺失键。
        """
        raw: list[dict] = []
        try:
            from tools.fetch_etf_tracking import fetch_etf_hist  # noqa: PLC0415
            raw = fetch_etf_hist(code)
        except ImportError:
            _logger.warning("bars_provider: fetch_etf_hist 不可用，ETF %s 走 baostock fallback", code)
        # 东财 push2delay 历史端点挂 → baostock fallback（不封 IP）
        if not raw:
            raw = _baostock_etf_hist(code)
        # 规范化：补 open/high/low = close（ETF 净值口径四价相等），过滤 close 缺失/0 的坏 bar
        out: list[dict] = []
        for b in raw:
            close = b.get("close")
            if not close:
                continue
            if "open" not in b:
                b = {**b, "open": close, "high": close, "low": close}
            out.append(b)
        return out

    @classmethod
    def reload(cls) -> None:
        """清模块级 cache（kline_refresh 16:30 刷完 cache 后重读）。"""
        global _CACHE
        _CACHE = None


__all__ = ["KlineCacheBarsProvider"]
