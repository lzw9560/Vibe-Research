"""Vibe-Research 后端 —— A股数据层 HTTP 接口（FastAPI）。

端点全部在 /api 下，前端 vite 代理 /api → localhost:8900。
只读、无状态、按用户传入代码返回客观数据。不预置标的、不建议。

启动：
    uvicorn app:app --host 127.0.0.1 --port 8900
"""

from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv
# 仓库根 .env 统一收拢 env（VR_DATA_DIR/VR_LLM_*/飞书 key）——import 前读，让 vr_paths.resolve_data_dir() 能用 VR_DATA_DIR
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import astock
import chat as chat_layer
import cli_runtime
import debate as debate_layer
import gstock
import newsradar
import portfolio as pf
import scheduled_tasks as _st
import limitup_screener as ls
import limitup_strategy as lstrat
import limitup_sti as ls_sti
import auction_screener as asc
from auction_screener import AUCTION_TOP_N
import daily_review as dr
import market
import myreports as mr
import reflection as reflect_layer

# Router imports
from routers import health, chat, portfolio, watchlist, myreports as myreports_router, radar, market as market_router, stock_data, stock_financial, limitup, review, sti, metrics, kline_history
from routers import recommendation, win_rate, feishu, backtest, bidding, strategy as strategy_router, sector_divergence, risk as risk_router, extreme_market, sentiment_weather, workflow, scheduled_tasks, prediction, advisory
from routers import intraday_sentiment as intraday_sentiment_router  # S063：盘中情绪辅助决策
from routers import coach as coach_router  # S064：盯盘教练
from routers import debate as debate_router  # main：多空辩论 + 反思审计
from routers import prediction_ledger_router as prediction_ledger_router_mod
from routers import premarket as premarket_router  # S071：盘前选股（breakout 弱信号+风控）
from routers import notes as notes_router  # 投研记录笔记（后端 SQLite 落盘，全局可见）
try:
    from routers import value_funnel as value_funnel_router
except Exception as _vf_err:  # noqa: BLE001 — value_funnel 半成品/缺 quality.py 时不挡 app 启动
    logging.warning("value_funnel 路由不可用，已跳过: %s", _vf_err)
    value_funnel_router = None

# 版本号从 package.json 单一来源读取（S020/main：不再三处硬编码）
from version import read_version

__version__ = read_version()

# S032 R6：两个后台周期任务（CronScheduler ticker + 持仓刷新）统一挂 FastAPI 主循环，
# 废除 daemon 线程 + 线程内 asyncio.run 桥接；shutdown 依次 stop/cancel。

async def _warmup_advisory_backtest() -> None:
    """S067 P0-1：advisory 回测预热。

    后台预跑 run_strategy_backtest(90) → 写 _WIN_RATE_CACHE（5min TTL）+ 回测 12h 缓存。
    首冷请求 >40s → ~0s（缓存命中）。失败不影响服务（catch + warning）。
    """
    try:
        import anyio
        from strategies.position_advisor_v2 import _win_rate_map
        await anyio.to_thread.run_sync(_win_rate_map)
        logging.info("[S067] advisory 回测预热完成")
    except Exception as _we:  # noqa: BLE001 — 预热失败不阻断启动
        logging.warning("[S067] advisory 回测预热失败（不影响服务）: %s", _we)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # startup
    await _st.start_scheduler()  # CronScheduler 主循环 ticker + seed 默认任务（R13）
    _pf_refresh_task = await pf.start_scheduler(1800)  # 持仓后台刷新 task
    # S052 D4：启动缺口补跑——回测快照缺失日后台排队回填
    from backfill_snapshots import startup_backfill_gap_check  # noqa: PLC0415
    # verification_card 表迁移（启动时一次，不在请求路径上）
    # 旧实现每次请求调 run_migrations → 并发锁异常 → 路由 502；移到 startup 幂等执行。
    # 迁移失败不阻塞 startup（verification_card 是辅助功能）
    try:
        from workflow.verification_card import ensure_migrations  # noqa: PLC0415
        ensure_migrations()
    except Exception as _vc_err:  # noqa: BLE001 — 辅助功能失败不阻断启动
        logger.warning("verification_card migration failed: %s", _vc_err)
    # S063：盘中情绪采样 task（仅交易日 09:25-15:00 运行）
    await intraday_sentiment_router.start_sampler()
    # grill：缺口补跑 + advisory 预热改为后台 fire-and-forget，不阻塞 startup
    # 保存引用防 GC 回收 + 加异常回调防静默崩溃
    _bg_tasks: set[asyncio.Task] = set()
    def _spawn(coro):
        t = asyncio.create_task(coro)
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)
        return t
    _spawn(startup_backfill_gap_check())
    _spawn(_warmup_advisory_backtest())
    # S088 Q1：storm-daemon 接入 lifespan——每 30min 存外围+新闻快照，
    # predict_storm 读前一交易日夜间快照。模块级 start() 幂等，VR_STORM_DAEMON=0 禁（conftest）。
    # 不接入则冷启动当日无快照必 fallback、首次 fetch 被动等 30min。
    try:
        import strategies.storm_daemon as _storm_daemon  # noqa: PLC0415
        _storm_daemon.start()
    except Exception as _e:  # noqa: BLE001 — daemon 启动失败不阻断服务
        logger.warning("[S088] storm_daemon 启动失败（不影响服务）: %s", _e)
    yield
    # shutdown
    await intraday_sentiment_router.stop_sampler()
    await _st.get_scheduler().stop()
    _pf_refresh_task.cancel()
    try:
        await _pf_refresh_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Vibe-Research API", version=__version__, lifespan=lifespan)

@app.get("/")
async def root():
    """API 根路径：返回基本信息，避免 404。"""
    return {
        "name": "Vibe-Research API",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
    }

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vibe-research")

# CORS：默认放开（本地自托管友好）；公网部署时用 VR_ALLOW_ORIGINS 收紧成白名单。
#   例：VR_ALLOW_ORIGINS="https://myhost"  （逗号分隔多个）
_ORIGINS = [o.strip() for o in os.environ.get("VR_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 可选鉴权：设了 VR_API_KEY 就要求所有 /api/* 带 `Authorization: Bearer <key>`
#   （本地自托管不设=开放；公网部署务必设，否则别人能读你的持仓/调你的后端）。
_API_KEY = os.environ.get("VR_API_KEY", "").strip()
@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if (
        _API_KEY
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/health"
    ):
        if request.headers.get("authorization", "") != f"Bearer {_API_KEY}":
            return JSONResponse({"detail": "未授权：缺少或错误的 API Key（VR_API_KEY）"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    """性能指标采集中间件：记录每次请求耗时。"""
    from metrics_collector import collector
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration = time.perf_counter() - start
        # 按路径前缀分层
        path = request.url.path
        if path.startswith("/api/limitup") or path.startswith("/api/recommendation") or path.startswith("/api/strategy"):
            tier = "compute"
        elif path.startswith("/api/metrics"):
            tier = "api_response"
        else:
            tier = "data_fetch"
        collector.record(duration, path, tier)
        return response
    except Exception:
        duration = time.perf_counter() - start
        collector.record(duration, request.url.path, "api_response")
        raise

_CODE_RE = r"^\d{6}$"
def _validate(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code
# ============ Router Registration ============

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(myreports_router.router)
app.include_router(radar.router)
app.include_router(market_router.router)
app.include_router(stock_data.router)
app.include_router(stock_financial.router)
app.include_router(limitup.router)
app.include_router(review.router)
app.include_router(sti.router)
app.include_router(metrics.router)
app.include_router(recommendation.router)
app.include_router(win_rate.router)
app.include_router(feishu.router)
app.include_router(backtest.router)
app.include_router(bidding.router)
app.include_router(strategy_router.router)
app.include_router(premarket_router.router)  # S071：盘前选股
app.include_router(sector_divergence.router)
app.include_router(risk_router.router)
app.include_router(extreme_market.router)
app.include_router(sentiment_weather.router)
app.include_router(workflow.router)
app.include_router(scheduled_tasks.router)
app.include_router(prediction.router)
app.include_router(prediction_ledger_router_mod.router)  # S061：预测账本
app.include_router(kline_history.router)
app.include_router(advisory.router)
app.include_router(intraday_sentiment_router.router)  # S063：盘中情绪辅助决策
app.include_router(coach_router.router)  # S064：盯盘教练
app.include_router(debate_router.router)  # main：多空辩论 + 反思审计
app.include_router(notes_router.router)  # 投研记录笔记（CRUD + SQLite 落盘）
if value_funnel_router is not None:
    app.include_router(value_funnel_router.router)

# ============ Unified error handling ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
    )
# ============ Route-level cache decorator ===========

import functools
import time as _time
from typing import Any, Callable, Dict, Tuple

_MAX_CACHE_SIZE = 1024
_RESPONSE_CACHE: Dict[str, Tuple[float, Any]] = {}


def _cache_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """构建响应缓存键：含 path + query params（若有 Request）+ 函数名 + 参数。

    修复点：旧实现 ``f"{func.__name__}:{...kwargs...}"`` 未含 args 与 query
    params，不同 code 在某些调用路径下可能撞缓存。现以稳定 JSON 序列化
    args + kwargs（FastAPI 将 path/query 参数以 kwargs 注入，故不同 code →
    不同 key）；若被装饰端点声明了 ``request: Request``，则进一步用 path +
    sorted query params 参与键，覆盖未声明在签名里的额外 query 串。
    """
    request = kwargs.get("request")
    if isinstance(request, Request):
        payload = {
            "path": request.url.path,
            "params": sorted(request.query_params.multi_items()),
        }
    else:
        payload = {
            "module": func.__module__,
            "name": func.__name__,
            "args": list(args),
            "kwargs": {k: v for k, v in sorted(kwargs.items())},
        }
    try:
        raw = json.dumps(payload, default=str, sort_keys=True)
    except TypeError:
        # 不可序列化对象退化为 repr，仍保留 args/kwargs 区分
        raw = f"{func.__module__}:{func.__name__}:{args!r}:{sorted(kwargs.items(), key=lambda kv: kv[0])}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def cache_response(ttl: int = 300):
    """Route-level cache decorator for GET endpoints."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _cache_key(func, args, kwargs)
            now = _time.time()
            hit = _RESPONSE_CACHE.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
            result = await func(*args, **kwargs)
            _RESPONSE_CACHE[key] = (now, result)
            # 简单大小限制：超出时清空一半
            if len(_RESPONSE_CACHE) > _MAX_CACHE_SIZE:
                keys = list(_RESPONSE_CACHE.keys())
                for k in keys[: len(keys) // 2]:
                    _RESPONSE_CACHE.pop(k, None)
            return result
        return wrapper
    return decorator


# 候选池漏斗 + 诊断卡路由（S002）；需在 cache_response 定义后注册
from routers import candidates as candidates_router  # noqa: E402

app.include_router(candidates_router.router)

# 拓扑展示路由（S024）：关系网 + 连板梯队树；需在 cache_response 定义后注册
from routers import topology as topology_router  # noqa: E402

app.include_router(topology_router.router)

