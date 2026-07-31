"""持仓数据层 —— 用户自己录入的持仓 + 实时行情叠加浮动盈亏。

合规：持仓是用户主动录入的自己的标的（存本地 ~/.vibe-research/portfolio.json，
不上传、不进仓库），不预置任何标的、不含 _SEED 兜底、不做推荐。
盈亏红涨绿跌（A股口径）。含每半小时后台定时刷新 + 手动刷新。

存储位置：默认用户目录 ~/.vibe-research/（可用 VR_DATA_DIR 覆盖）——
放仓库外，重新下载/覆盖项目文件夹不会丢数据（issue #12）。
≤v0.1.1 存在 backend/.cache/ 仓库内，首次启动自动迁移（复制，旧文件保留作备份）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

import astock
from data.mappers import quote_from_tencent

HERE = os.path.dirname(os.path.abspath(__file__))
_OLD_PF_FILE = os.path.join(HERE, ".cache", "portfolio.json")  # ≤v0.1.1 旧位置
# CACHE_DIR 名字保留（测试/外部按此名 monkeypatch），实际已是用户数据目录。
# 默认项目内 .vibe-research/（gitignored，vr_paths；旧版用 ~/.vibe-research/）
from vr_paths import resolve_data_dir  # noqa: E402

CACHE_DIR = str(resolve_data_dir())
PF_FILE = os.path.join(CACHE_DIR, "portfolio.json")
BEIJING = timezone(timedelta(hours=8))
_LOCK = asyncio.Lock()


def _migrate_legacy() -> None:
    """旧版持仓在仓库内 .cache/ 里，重下载项目会丢；迁到用户目录（新位置已有则不动）。"""
    try:
        if not os.path.exists(PF_FILE) and os.path.exists(_OLD_PF_FILE):
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = PF_FILE + ".migrate.tmp"
            shutil.copy2(_OLD_PF_FILE, tmp)
            os.replace(tmp, PF_FILE)  # 原子落位：复制中断不会留半截 portfolio.json 挡住下次重试
    except OSError as e:
        # 迁移失败不阻塞启动，但要出声——旧数据原样保留在 _OLD_PF_FILE，可手工复制
        logging.getLogger("vibe-research").warning(
            "持仓数据迁移失败（旧数据仍在 %s）: %s", _OLD_PF_FILE, e
        )


_migrate_legacy()


def _now() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M")


def _load() -> dict:
    try:
        with open(PF_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"holdings": [], "last_refresh": None}


def _save(d: dict) -> None:
    # 先写临时文件再原子改名：并发读若撞上写中途的半截 JSON，会被 _load 静默当成空持仓
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = PF_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, PF_FILE)


async def add_holding(code: str, shares: float, cost: float) -> dict:
    """加一笔持仓；同代码则按加权平均成本合并（加仓）。"""
    async with _LOCK:
        d = await asyncio.to_thread(_load)
        for h in d["holdings"]:
            if h["code"] == code:
                total = h["shares"] + shares
                # 4 位小数：ETF/基金成本常见 3-4 位（issue #13），2-3 位会让市值/盈亏对不上账
                h["cost"] = round((h["shares"] * h["cost"] + shares * cost) / total, 4) if total else cost
                h["shares"] = total
                break
        else:
            d["holdings"].append({"code": code, "shares": shares, "cost": cost})
        await asyncio.to_thread(_save, d)
    return await get_portfolio()


async def remove_holding(code: str) -> dict:
    async with _LOCK:
        d = await asyncio.to_thread(_load)
        d["holdings"] = [h for h in d["holdings"] if h["code"] != code]
        await asyncio.to_thread(_save, d)
    return await get_portfolio()


async def close_position(code: str, date: str, price: float, shares: float, cost: float) -> dict:
    """记一笔已清仓：算已实现盈亏，存入 closed 列表，并从持仓中移除。"""
    pnl = (price - cost) * shares
    async with _LOCK:
        d = await asyncio.to_thread(_load)
        d.setdefault("closed", [])
        try:
            raw = astock.tencent_quote([code]) or {}
            name = quote_from_tencent(code, raw.get(code, {})).name or code
        except Exception:
            name = code
        d["closed"].append({
            "code": code, "name": name, "date": date, "price": price,
            "shares": shares, "cost": cost, "pnl": round(pnl, 2),
            "pnl_pct": round((price - cost) / cost * 100, 2) if cost else 0.0,
        })
        # 同步从持仓中移除该代码
        d["holdings"] = [h for h in d.get("holdings", []) if h["code"] != code]
        await asyncio.to_thread(_save, d)
    return await get_portfolio()


async def remove_closed(index: int) -> dict:
    async with _LOCK:
        d = await asyncio.to_thread(_load)
        cl = d.get("closed", [])
        if 0 <= index < len(cl):
            cl.pop(index)
            await asyncio.to_thread(_save, d)
    return await get_portfolio()


async def get_portfolio() -> dict:
    """读持仓 + 实时行情，算每笔与汇总的市值/浮动盈亏。"""
    async with _LOCK:
        d = await asyncio.to_thread(_load)
    hs = d.get("holdings", [])
    rows, tmv, tcost = [], 0.0, 0.0
    if hs:
        try:
            raw = astock.tencent_quote([h["code"] for h in hs]) or {}
        except Exception:
            raw = {}
        for h in hs:
            model = quote_from_tencent(h["code"], raw.get(h["code"], {}))
            price = model.price or 0.0
            mv = price * h["shares"]
            cv = h["cost"] * h["shares"]
            pnl = mv - cv
            rows.append({
                "code": h["code"], "name": model.name or h["code"],
                "price": price, "shares": h["shares"], "cost": h["cost"],
                "market_value": round(mv, 2), "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / cv * 100, 2) if cv else 0.0,
            })
            tmv += mv
            tcost += cv
    total_pnl = tmv - tcost
    closed = d.get("closed", [])
    return {
        "holdings": rows,
        "totals": {
            "market_value": round(tmv, 2), "cost": round(tcost, 2),
            "pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / tcost * 100, 2) if tcost else 0.0,
        },
        "closed": closed,
        "realized_pnl": round(sum(c.get("pnl", 0) for c in closed), 2),
        "updated": _now(),
        "last_refresh": d.get("last_refresh"),
    }


async def _refresh_snapshot() -> None:
    """后台定时任务：刷新时间戳（GET 本就实时算，这里记录后台刷新点）。"""
    async with _LOCK:
        d = await asyncio.to_thread(_load)
        d["last_refresh"] = _now()
        await asyncio.to_thread(_save, d)


def start_scheduler(interval: int = 1800) -> None:
    """每半小时后台刷新一次持仓数据（daemon 线程）。"""
    def loop() -> None:
        while True:
            time.sleep(interval)
            try:
                asyncio.run(_refresh_snapshot())
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True).start()
