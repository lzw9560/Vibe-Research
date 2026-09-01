"""审计修复回归测（2026-07-05，全部离线）：
鉴权中间件 / 持仓 CRUD 与坏文件降级 / 估值脏数据防护 / 涨停池脏数值 /
空结果不缓存 / akshare 缺失降级 / 无 index 工具调用归位 / CLI 流式超时。
"""
import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import chat
import cli_runtime
import market
import portfolio as pf

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _clear_market_cache():
    """S133 后 _emotion date-keyed 缓存壳跨用例污染——每用例前清 _CACHE。"""
    market._CACHE.clear()
    yield
    market._CACHE.clear()


# ── VR_API_KEY 鉴权中间件 ───────────────────────────────────────────

def test_api_key_auth(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "sekret")
    assert client.get("/api/health").status_code == 200  # health 豁免
    assert client.get("/api/quote?codes=abc").status_code == 401  # 缺头
    assert client.get("/api/quote?codes=abc", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # 正确 key → 通过鉴权、走到参数校验层（400 而非 401，不联网）
    assert client.get("/api/quote?codes=abc", headers={"Authorization": "Bearer sekret"}).status_code == 400


# ── 持仓：本地 JSON CRUD（不联网，行情打桩） ────────────────────────

@pytest.fixture()
def tmp_pf(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {c: {"name": f"股{c}", "price": 10.0} for c in codes})
    return tmp_path


def test_portfolio_crud_roundtrip(tmp_pf):
    assert client.get("/api/portfolio").json()["data"]["holdings"] == []

    r = client.post("/api/portfolio/holding", json={"code": "600519", "shares": 100, "cost": 8.0})
    assert r.status_code == 200
    h = r.json()["data"]["holdings"][0]
    assert h["code"] == "600519"
    assert h["pnl"] == pytest.approx((10.0 - 8.0) * 100)

    # 同代码加仓 → 加权平均成本
    client.post("/api/portfolio/holding", json={"code": "600519", "shares": 100, "cost": 12.0})
    h = client.get("/api/portfolio").json()["data"]["holdings"][0]
    assert h["shares"] == 200
    assert h["cost"] == pytest.approx(10.0)

    r = client.post("/api/portfolio/close", json={"code": "600519", "date": "2026-07-05", "price": 11.0, "shares": 200, "cost": 10.0})
    assert r.status_code == 200
    assert r.json()["data"]["closed"][0]["pnl"] == pytest.approx(200.0)

    assert client.delete("/api/portfolio/holding?code=600519").json()["data"]["holdings"] == []
    assert client.delete("/api/portfolio/close?index=0").json()["data"]["closed"] == []
    assert client.post("/api/portfolio/refresh").status_code == 200


def test_portfolio_add_validation(tmp_pf):
    assert client.post("/api/portfolio/holding", json={"code": "abc", "shares": 1, "cost": 1}).status_code == 400
    assert client.post("/api/portfolio/holding", json={"code": "600519", "shares": 0, "cost": 1}).status_code == 400


def test_portfolio_corrupt_file_returns_empty(tmp_pf):
    (tmp_pf / "portfolio.json").write_text("{broken json", encoding="utf-8")
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    assert r.json()["data"]["holdings"] == []


# ── issue #13：加仓合并成本保留 4 位小数（ETF/基金成本常见 3-4 位） ──

def test_portfolio_merge_cost_keeps_4_decimals(tmp_pf):
    client.post("/api/portfolio/holding", json={"code": "510300", "shares": 100, "cost": 1.0001})
    client.post("/api/portfolio/holding", json={"code": "510300", "shares": 100, "cost": 1.0003})
    h = client.get("/api/portfolio").json()["data"]["holdings"][0]
    assert h["cost"] == pytest.approx(1.0002, abs=1e-9)


# ── issue #12：旧版数据在仓库内 .cache/，重下载会丢 → 自动迁到用户目录 ──

def test_portfolio_legacy_migration(tmp_path, monkeypatch):
    old = tmp_path / "repo-cache" / "portfolio.json"
    old.parent.mkdir()
    old.write_text('{"holdings": [{"code": "600519", "shares": 100, "cost": 8.0}]}', encoding="utf-8")
    monkeypatch.setattr(pf, "_OLD_PF_FILE", str(old))
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path / "userdata"))
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "userdata" / "portfolio.json"))
    pf._migrate_legacy()
    assert pf._load()["holdings"][0]["code"] == "600519"
    # 新位置已有数据 → 再跑迁移不覆盖
    pf._save({"holdings": []})
    pf._migrate_legacy()
    assert pf._load()["holdings"] == []


def test_myreports_legacy_migration(tmp_path, monkeypatch):
    import myreports as mr

    old = tmp_path / "repo-cache" / "myreports"
    old.mkdir(parents=True)
    (old / "index.json").write_text("[]", encoding="utf-8")
    monkeypatch.delenv("VR_REPORTS_DIR", raising=False)
    monkeypatch.setattr(mr, "_OLD_DEFAULT_DIR", old)
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "userdata" / "myreports")
    # 上次复制中断留下的半截临时目录，不该挡住这次迁移
    stale = tmp_path / "userdata" / "myreports.migrate.tmp"
    stale.mkdir(parents=True)
    (stale / "partial.bin").write_text("x", encoding="utf-8")
    mr._migrate_legacy()
    dst = tmp_path / "userdata" / "myreports"
    assert (dst / "index.json").exists()
    assert not (dst / "partial.bin").exists()  # 半截内容没混进正式目录


# ── full_valuation：一致预期缺「均值」/ '-' 占位不再 502 ─────────────

_QUOTE = {"600519": {"name": "贵州茅台", "price": 100.0, "mcap_yi": 1000, "pe_ttm": 20.0, "pb": 5.0}}


def test_full_valuation_dirty_forecast(monkeypatch):
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _QUOTE)
    monkeypatch.setattr(astock, "profit_forecast", lambda code: [
        {"年度": "2026", "预测机构数": "-"},  # 缺「均值」+ 脏机构数
        {"年度": "2027", "均值": "-"},        # '-' 占位
    ])
    out = astock.full_valuation("600519")
    assert out["eps_26e"] is None
    assert out["eps_27e"] is None
    assert out["pe_26e"] is None


def test_full_valuation_string_numbers(monkeypatch):
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _QUOTE)
    monkeypatch.setattr(astock, "profit_forecast", lambda code: [
        {"年度": "2026年", "均值": "2.0", "预测机构数": "12"},
        {"年度": "2027年", "均值": 2.4},
    ])
    out = astock.full_valuation("600519")
    assert out["eps_26e"] == 2.0
    assert out["analyst_count"] == 12
    assert out["pe_26e"] == 50.0


# ── 短线情绪：涨停池脏数值（'-' 占位）不再让排序崩溃 ────────────────

def test_emotion_dirty_amount(monkeypatch):
    pools = {
        "getTopicZTPool": [
            {"c": "600001", "n": "甲", "lbc": 3, "p": 10000, "zdp": 10.0, "amount": "-", "ltsz": None, "hybk": "X"},
            {"c": "600002", "n": "乙", "lbc": 2, "p": "-", "zdp": None, "amount": 5e8, "ltsz": 1e9, "hybk": "Y"},
        ],
        "getTopicZBPool": [],
        "getTopicDTPool": [],
        "getYesterdayZTPool": [{}],
    }
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda ep, d, sort="", raise_on_failure=False: pools.get(ep, []))
    out = market._emotion()
    stocks = out["lianban_stocks"]
    assert [s["code"] for s in stocks] == ["600001", "600002"]  # 排序没崩、按连板数降序
    assert stocks[0]["amount"] is None    # '-' 归一为 None
    assert stocks[1]["price"] is None     # p='-' 归一为 None（S130 R2: 0→None，'-'=缺失非 0）
    assert stocks[1]["amount"] == 5e8


# ── S122：market._emotion(date=None) 周末交易日历门控 ────────────────────

def _fake_datetime(now_val):
    """datetime 替身（对齐 test_s056 _FakeDateTime / test_s052 type("DT",...) 范式）。
    now() 返固定值控制周末/盘前/盘后；strptime 等委托真 datetime。"""
    from datetime import datetime as real_dt

    class _DT:
        @staticmethod
        def now(tz=None):
            return now_val

        def __getattr__(self, name):
            return getattr(real_dt, name)

    return _DT()


def test_emotion_weekend_resolves_to_friday_not_saturday(monkeypatch):
    """S122 A1：周末（今天=周六）_emotion(None) → date=周五（非周六）。

    em_zt_topic_pool 非交易日查询静默回退返最近交易日池（实测 08-21/22/23 三天字节级
    相同的周五 54 条）；无 is_trading_day 守卫则 back=0 命中周五池 → resolved=周六 →
    周五池标成周六实时情绪撒谎。守卫跳过周末落到周五，date 与池数据一致。
    """
    from datetime import datetime as real_dt
    import vr_paths

    # 今天=2026-08-15（周六，weekday=5）10:00
    sat = real_dt(2026, 8, 15, 10, 0, tzinfo=market.BEIJING)
    monkeypatch.setattr(market, "datetime", _fake_datetime(sat))
    # is_trading_day：Mon-Fri True（decouple 交易日历）
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: d is not None and d.weekday() < 5)
    # em 对任意日返池（模拟静默回退——周六查也返周五池）；守卫已跳过周六直落到周五
    pool = [{"c": "600001", "n": "甲", "lbc": 3, "p": 10000, "zdp": 10.0,
             "amount": 5e8, "ltsz": 1e9, "hybk": "X"}]
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda ep, d, sort="", raise_on_failure=False: pool)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {})

    out = market._emotion(None)
    assert out["date"] == "2026-08-14"  # 周五，非周六 2026-08-15


def test_emotion_trading_day_afterclose_resolves_today(monkeypatch):
    """S122 A3：交易日盘后（hour>=15）_emotion(None) → date=今日（非 T-1）。

    盘前(hour<15)当日池未生成 em 回退 T-1 误标今日（P0-3 同款）；盘后 hour>=15
    当日池已生成 → resolved=今日，date 与池数据一致（happy path）。
    """
    from datetime import datetime as real_dt
    import vr_paths

    # 今天=2026-08-14（周五，weekday=4）16:00（盘后）
    fri = real_dt(2026, 8, 14, 16, 0, tzinfo=market.BEIJING)
    monkeypatch.setattr(market, "datetime", _fake_datetime(fri))
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda d=None: d is not None and d.weekday() < 5)
    pool = [{"c": "600001", "n": "甲", "lbc": 3, "p": 10000, "zdp": 10.0,
             "amount": 5e8, "ltsz": 1e9, "hybk": "X"}]
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda ep, d, sort="", raise_on_failure=False: pool)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {})

    out = market._emotion(None)
    assert out["date"] == "2026-08-14"  # 今日（周五盘后）


# ── 缓存：数据源故障的空结果不缓存 5 分钟 ───────────────────────────

def test_cached_skips_empty():
    market._CACHE.pop("k_test", None)
    calls = []

    def flaky():
        calls.append(1)
        return {} if len(calls) == 1 else {"ok": 1}

    assert market._cached("k_test", flaky) == {}
    assert market._cached("k_test", flaky) == {"ok": 1}  # 空结果没被缓存 → 下次重试成功
    assert market._cached("k_test", flaky) == {"ok": 1}  # 非空已缓存，不再调用
    assert len(calls) == 2
    market._CACHE.pop("k_test", None)


# ── akshare 未安装：market 降级返回空，不挡服务 ─────────────────────

def test_market_degrades_without_akshare(monkeypatch):
    def boom():
        raise astock.DependencyMissing("akshare 未安装")

    monkeypatch.setattr(astock, "_akshare", boom)
    assert market._sentiment() == {}
    assert market._sectors() == []


# ── 流式工具调用：非标网关不带 index 时按 id 归位、不串参数 ──────────

def test_stream_tool_calls_without_index(monkeypatch):
    deltas_rounds = [
        [  # 第一轮：增量全部不带 index —— 续块无 id、新调用带新 id
            {"tool_calls": [{"id": "call_a", "function": {"name": "query_quote", "arguments": '{"codes":'}}]},
            {"tool_calls": [{"function": {"arguments": '["600519"]}'}}]},
            {"tool_calls": [{"id": "call_b", "function": {"name": "query_news", "arguments": '{"code":"600519"}'}}]},
        ],
        [{"content": "答案"}],  # 第二轮：纯文本收尾
    ]
    state = {"round": 0}
    monkeypatch.setattr(chat, "_call_llm_stream", lambda cfg, messages, use_tools: None)

    def fake_iter(_resp):
        i = state["round"]
        state["round"] += 1
        yield from deltas_rounds[i]

    monkeypatch.setattr(chat, "_iter_sse_deltas", fake_iter)
    executed = []
    monkeypatch.setattr(chat, "_exec_tool", lambda name, args: (executed.append((name, args)), {"ok": 1})[1])

    events = list(chat.run_chat_stream(
        {"baseURL": "http://x", "apiKey": "k", "model": "m"},
        [{"role": "user", "content": "q"}],
    ))
    assert ("query_quote", {"codes": ["600519"]}) in executed  # 参数没被串坏
    assert ("query_news", {"code": "600519"}) in executed      # 两个调用各归各槽
    assert events[-1]["type"] == "done"


# ── CLI 流式：子进程挂起时超时真正生效（不再无限期阻塞） ────────────

def test_run_cli_stream_timeout(monkeypatch):
    import sys

    # 用 sys.executable 而非 "python3"——后者在 Windows 上常解析到 Store 存根（无输出），
    # 导致本测试误报。超时预算 3s 留子进程 spawn 余量（仍 << 30s sleep，必触发超时）。
    monkeypatch.setattr(cli_runtime, "_CLI_TIMEOUT_S", 3)
    monkeypatch.setitem(cli_runtime._CLI_DEFS, "fake", {
        "bins": [sys.executable],
        "delivery": "stdin",
        "build_args": lambda _: ["-c", "import time\nprint('x', flush=True)\ntime.sleep(30)"],
        "env": {},
    })
    chunks = []
    with pytest.raises(RuntimeError, match="超时"):
        for line in cli_runtime.run_cli_stream("fake", "s", "u"):
            chunks.append(line)
    assert chunks and chunks[0].strip() == "x"  # 挂起前的输出已正常流出

