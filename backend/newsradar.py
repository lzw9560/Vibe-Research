"""资讯雷达数据层 —— 移植自 investment-news。

抓 12 赛道 108 个公开 RSS 源 → 合规过滤（赌/预测市场/加密/色情）+ 最近 N 天
+ 按赛道分组、时间倒序。纯标准库 + 线程池，零 key、零个股字段。

AI「今日要点」不在此模块——复用 Vibe-Research 的可插拔 AI 层（前端调 /api/chat，
把某赛道资讯打包给用户自己的模型提炼）。本模块只出客观资讯。
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, "news_sources.json")
CACHE_DIR = os.path.join(HERE, ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "radar.json")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BEIJING = timezone(timedelta(hours=8))


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _parse_dt(s: str):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fetch_source(src: dict, per: int, cutoff, redline: list[str]):
    """抓单个 RSS 源；返回 items 列表，出错返回 None。"""
    try:
        req = urllib.request.Request(src["url"], headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=14) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        out = []
        for n in [e for e in root.iter() if _local(e.tag) in ("item", "entry")]:
            if len(out) >= per:
                break
            d = {"title": "", "url": "", "time": "", "ts": 0, "summary": "", "source": src["name"]}
            rawtime = ""
            for c in n:
                t = _local(c.tag)
                if t == "title" and not d["title"]:
                    d["title"] = (c.text or "").strip()
                elif t == "link" and not d["url"]:
                    d["url"] = c.get("href") or (c.text or "").strip()
                elif t in ("pubDate", "published", "updated", "date") and not rawtime:
                    rawtime = (c.text or "").strip()
                elif t in ("description", "summary", "content") and not d["summary"]:
                    d["summary"] = _strip_html(c.text or "")[:160]
            if not d["title"]:
                continue
            blob = (d["title"] + " " + d["summary"]).lower()
            if any(k in blob for k in redline):  # 合规红线过滤
                continue
            dt = _parse_dt(rawtime)
            if dt is not None:
                if cutoff and dt < cutoff:
                    continue
                d["time"] = dt.astimezone(BEIJING).strftime("%m-%d %H:%M")
                d["ts"] = int(dt.timestamp())
            else:
                d["time"] = "—"
            out.append(d)
        return out
    except Exception:
        return None


def _fetch_global_intel() -> list[dict]:
    """「全球情报」赛道：聚合 worldmonitor 资讯聚类 + GDELT 情报（S020 R4）。

    lazy import worldmonitor（避免 newsradar 顶层依赖 requests——保 stdlib-only 性质）。
    worldmonitor 不可达/无 key/超时 → 返空 list（赛道缺省，不抛、不臆造、不阻塞 RSS 抓取）。
    item 同构 RSS：``{title, summary, source:"worldmonitor", category, ts}``，**零个股字段**。
    AI 提炼仍走 ``/api/chat``（本模块只出客观资讯）。

    **非阻塞**：worldmonitor 调用在独立线程 + 8s 总超时内执行（grill #3 修复）。
    newsradar 原是 stdlib + 线程池快速模块，不得为空赛道阻塞 fetch_radar——
    worldmonitor 永久不可达时前 5 次各等满超时再短路会拖垮雷达刷新。
    """
    try:
        from data.sources import worldmonitor as wm
    except Exception:
        return []
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout

    def worker():
        out: list[dict] = []
        try:
            out.extend(wm.parse_news_clusters(wm.fetch_news_clusters()))
        except Exception:
            pass
        try:
            out.extend(wm.parse_news_intelligence(wm.fetch_news_intelligence()))
        except Exception:
            pass
        return out

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            items = ex.submit(worker).result(timeout=8)
    except FTimeout:
        return []  # worldmonitor 慢/不可达——不阻塞 fetch_radar
    except Exception:
        return []
    items.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return items


def fetch_radar() -> dict:
    """抓全部源，返回 12 赛道 + 全球情报赛道数据并落盘缓存。"""
    cfg = json.load(open(SOURCES_FILE, encoding="utf-8"))
    days = cfg.get("fetch", {}).get("recent_days", 7)
    per = cfg.get("fetch", {}).get("per_source", 6)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    redline = [k.lower() for k in cfg.get("redline_keywords", [])]

    byhint: dict[str, list] = {}
    for s in cfg["sources"]:
        byhint.setdefault(s["hint"], []).append(s)

    industries, tasks = [], []
    for i, ind in enumerate(cfg["industries"]):
        pool = byhint.get(ind["key"], [])
        industries.append({"key": ind["key"], "name": ind["name"], "accent": ind["accent"], "total": len(pool), "items": []})
        for s in pool:
            tasks.append((i, s))

    with ThreadPoolExecutor(max_workers=40) as ex:
        results = list(ex.map(lambda t: (t[0], _fetch_source(t[1], per, cutoff, redline)), tasks))

    failed = 0
    for idx, items in results:
        if items is None:
            failed += 1
            continue
        industries[idx]["items"].extend(items)
    # 「全球情报」赛道（worldmonitor，与 12 RSS 赛道同构并列；不可达则缺省）
    global_items = _fetch_global_intel()
    industries.append({
        "key": "global_intel", "name": "全球情报", "accent": "#6b7280",
        "total": len(global_items), "items": global_items,
    })
    for ind in industries:
        ind["items"].sort(key=lambda x: x.get("ts", 0), reverse=True)

    data = {
        "generated_at": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        "recent_days": days,
        "industries": industries,
        "stats": {"industries": len(industries), "total_sources": len(cfg["sources"]), "failed_sources": failed},
    }
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)  # 原子改名，防两次并发刷新交错写坏缓存
    return data


# S112 R8：缓存 TTL——过期返 None 让 get_radar 退回 skeleton（诚实空，对齐 fallback.py TTL 范式）。
# storm_daemon 每 30min fetch_radar 刷新；TTL 1h（=2 个 fetch 周期）容忍单次 fetch 抖动，
# daemon 挂掉 >1h 即过期退 skeleton，不拿旧缓存当新 radar（原仅判文件存在/JSON 合法）。
_RADAR_CACHE_TTL_SECONDS = 3600  # 1 小时（对齐 fallback._MEM_TTL）


def _cache_is_fresh(data) -> bool:
    """缓存是否在 TTL 内：generated_at 缺失/格式坏/过期 → False。"""
    if not isinstance(data, dict):
        return False
    generated_at = data.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        return False
    try:
        ts = datetime.strptime(generated_at, "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING)
    except (ValueError, TypeError):
        return False
    age = (datetime.now(BEIJING) - ts).total_seconds()
    return age <= _RADAR_CACHE_TTL_SECONDS


def load_cache():
    """读缓存并校验 TTL：过期/损坏返 None（让 get_radar 退回 skeleton 诚实空）。

    S112 R8：原仅 FileNotFoundError/JSONDecodeError→None 无 TTL/时间戳校验，
    调度 fetch 断/未跑时返上次成功写的旧缓存当新 radar。现加 TTL 比较——
    过期返 None（对齐 fallback.py TTL 范式），generated_at 缺失/格式坏也判过期。
    """
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        # S112 review fix：扩 except 防 UnicodeDecodeError/PermissionError 外泄
        # （S112 后 stale 即触发 skeleton，该路径触发面扩大，加固预存脆弱点）
        return None
    if not _cache_is_fresh(data):
        return None
    return data


def skeleton() -> dict:
    """无缓存时返回赛道骨架（空 items），前端提示点刷新。"""
    try:
        cfg = json.load(open(SOURCES_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        # S112 review fix：SOURCES_FILE 损坏/权限异常退最简骨架而非崩
        # （S112 后 stale 触发 skeleton 路径，加固预存脆弱点）
        return {"generated_at": None, "recent_days": 7, "industries": [], "stats": {"industries": 0, "total_sources": 0}}
    byhint: dict[str, int] = {}
    for s in cfg["sources"]:
        byhint[s["hint"]] = byhint.get(s["hint"], 0) + 1
    return {
        "generated_at": None,
        "recent_days": cfg.get("fetch", {}).get("recent_days", 7),
        "industries": [{"key": i["key"], "name": i["name"], "accent": i["accent"], "total": byhint.get(i["key"], 0), "items": []} for i in cfg["industries"]],
        "stats": {"industries": len(cfg["industries"]), "total_sources": len(cfg["sources"])},
    }


def get_radar(force: bool = False) -> dict:
    if force:
        return fetch_radar()
    return load_cache() or skeleton()
