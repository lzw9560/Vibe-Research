# -*- coding: utf-8 -*-
"""S088 Q1 daemon：定时（30min）统一存外围+新闻快照，不阻塞主流程。

修历史 bug：get_global_indices 返当前不是 T-1 夜间（0819 预测取了 0820 外围没预警）。
daemon 每 30min 存外围快照（get_global_indices）+ 新闻（fetch_radar），predict_storm 读 T-1 夜间快照。

不碰 scheduled_tasks（并发编辑器在改，独立 daemon 避免冲突）。
测试禁：VR_STORM_DAEMON=0（conftest 设）。刷新语境 tab：前端 useQuery refetchInterval 轮询。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime as _dt
from pathlib import Path

from vr_paths import resolve_data_dir

_logger = logging.getLogger("vibe-research")

_SNAP_DIR = resolve_data_dir() / "storm_snapshots"
_STOP = threading.Event()
_ENABLED = os.environ.get("VR_STORM_DAEMON", "1") != "0"
_INTERVAL = 1800  # 30min
_KEEP = 20  # 每日保留最近 20 个快照


def fetch_snapshot() -> dict:
    """存外围+新闻快照（date+time → JSON，每日一文件，保留最近 20 个快照）。

    S116 provenance：global_indices 失败/空→fetch_ok=False/is_degraded=True 落盘，
    供 get_t1_global_snapshot 过滤 last-write-wins 遮蔽坏快照（非撒谎修复，是可用性）。
    """
    now = _dt.now()
    snap: dict = {"ts": now.isoformat(), "date": now.strftime("%Y-%m-%d")}

    # 外围指数（provenance 主体：fetch_ok/is_degraded 据此判定，非新闻——新闻有独立 fallback）
    global_fetch_ok = False
    try:
        import market  # noqa: PLC0415

        snap["global_indices"] = market.get_global_indices() or []
        global_fetch_ok = bool(snap["global_indices"])
        if not global_fetch_ok:
            _logger.debug("[storm-daemon] 外围快照空")
    except Exception as exc:  # noqa: BLE001
        snap["global_indices"] = []
        # 真 exception（非空结果正常抖动）升 warning——daemon 连续多日 fetch 失败
        # 运维侧可见（provenance 落盘已是数据管道诚实信号，此为运维可见性补）
        _logger.warning("[storm-daemon] 外围快照失败: %s", exc)
    # S116 provenance 落盘（成功→fetch_ok=True/is_degraded=False；空/失败→False/True）
    snap["fetch_ok"] = global_fetch_ok
    snap["is_degraded"] = not global_fetch_ok

    # 新闻（fetch_radar 同步阻塞 10-30s，但在 daemon 线程不阻塞主流程）
    # S123：mirror global_indices provenance——news_fetch_ok 据此落盘，供 _collect_news_factor
    # 区分"T-1 快照 news 采集失败"与"无 T-1 快照"（原 news 无 provenance 致两者不可区分）
    news_fetch_ok = False
    try:
        import newsradar  # noqa: PLC0415

        radar = newsradar.fetch_radar() or {}
        # S088 grill Q5：fetch_radar 顶层无 items 键，是 industries 嵌套 items，须扁平化
        snap["news_items"] = (
            [it for ind in (radar.get("industries", []) or [])
             for it in (ind.get("items", []) or [])]
            if isinstance(radar, dict) else []
        )
        news_fetch_ok = bool(snap["news_items"])
        if not news_fetch_ok:
            _logger.debug("[storm-daemon] 新闻快照空")
    except Exception as exc:  # noqa: BLE001
        snap["news_items"] = []
        # S123：mirror global_indices(53)——真 exception 升 warning（运维可见，
        # provenance 落盘已是数据管道诚实信号，此为运维可见性补，非 debug 静默吞）
        _logger.warning("[storm-daemon] 新闻快照失败: %s", exc)
    # S123 provenance 落盘（mirror global_indices:55-56；成功→news_fetch_ok=True/
    # news_is_degraded=False；空/失败→False/True）
    snap["news_fetch_ok"] = news_fetch_ok
    snap["news_is_degraded"] = not news_fetch_ok

    # 存（每日一文件，追加快照，保留最近 _KEEP 个）
    _SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = _SNAP_DIR / f"{now.strftime('%Y-%m-%d')}.json"
    snaps: list = []
    if path.exists():
        try:
            snaps = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(snaps, list):
                snaps = []
        except Exception:  # noqa: BLE001 — 损坏快照重置
            snaps = []
    snaps.append(snap)
    snaps = snaps[-_KEEP:]
    path.write_text(json.dumps(snaps, ensure_ascii=False), encoding="utf-8")
    return snap


def get_t1_global_snapshot(date: str) -> dict | None:
    """读前一交易日（T-1）夜间外围快照（predict_storm 用，替代 get_global_indices 当前）。

    S116 last-write-wins 修：不再盲返 snaps[-1]——过滤 empty/degraded 快照
    （global_indices==[] 或 fetch_ok==False），取最近非空夜间好快照；全坏→返最近坏 +
    标 is_degraded（供 storm_predictor 据 provenance 诚实标 degraded/fallback）。无快照返 None。
    S088 grill Q1 修：原 last_trading_date(d) 在交易日返回 d 本身，读当日快照而非前日夜间；
    改用 prev_trading_date（先退一日再回退）。
    """
    try:
        from vr_paths import prev_trading_date  # noqa: PLC0415

        d = _dt.strptime(date, "%Y-%m-%d") if "-" in date else _dt.strptime(date, "%Y%m%d")
        t1 = prev_trading_date(d).strftime("%Y-%m-%d")
        path = _SNAP_DIR / f"{t1}.json"
        if not path.exists():
            return None
        snaps = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(snaps, list) or not snaps:
            return None
        # S116：过滤遮蔽坏快照，取最近非空夜间好快照（fetch_ok 缺省 True 兼容旧无 provenance 快照）
        good = [
            s for s in snaps
            if isinstance(s, dict) and s.get("global_indices") and s.get("fetch_ok", True)
        ]
        if good:
            return good[-1]
        # 全坏→返最近坏 + 标 degraded（不可变拷贝，不污染落盘；供 storm_predictor 诚实标）
        for s in reversed(snaps):
            if isinstance(s, dict):
                return {**s, "is_degraded": True}
        return None
    except Exception:  # noqa: BLE001
        return None


def _loop() -> None:
    """daemon 循环：每 _INTERVAL 存快照。"""
    while not _STOP.wait(_INTERVAL):
        try:
            fetch_snapshot()
        except Exception as exc:  # noqa: BLE001
            _logger.debug("[storm-daemon] 快照循环失败: %s", exc)


def start() -> None:
    """启动 daemon 线程（幂等，VR_STORM_DAEMON=0 禁用）。"""
    if not _ENABLED:
        return
    if any(t.name == "storm-daemon" for t in threading.enumerate()):
        return
    t = threading.Thread(target=_loop, name="storm-daemon", daemon=True)
    t.start()
    _logger.info("[storm-daemon] 启动，间隔 %ds，快照目录 %s", _INTERVAL, _SNAP_DIR)


def stop() -> None:
    """停止 daemon（测试用）。"""
    _STOP.set()


# 模块级启动（import 时，VR_STORM_DAEMON=0 禁用——conftest 设）
start()
