"""版本号单一来源 + MCP stdout 洁净（#20 / codex 复审）。"""
import contextlib
import io

import version


def test_reads_version_from_package_json():
    assert version.read_version() != "unknown"


def test_missing_file_returns_unknown_not_a_stale_version(monkeypatch):
    """读不到就说 unknown，**绝不退回写死的旧版本号**——那正是 #20 的成因。"""
    monkeypatch.setattr(version, "_PACKAGE_JSON", "/nonexistent/package.json")
    assert version.read_version() == "unknown"


def test_warning_never_goes_to_stdout(monkeypatch):
    """🔴 本模块被 mcp_server 导入，MCP 的 stdout 专供 JSON-RPC。

    往 stdout 打一行警告会插在初始化响应之前，客户端可能直接拒收整条流。
    仅后端部署（没有 frontend/）时正好会走到这个分支。
    """
    monkeypatch.setattr(version, "_PACKAGE_JSON", "/nonexistent/package.json")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        version.read_version()
    assert out.getvalue() == ""
    assert "读不到版本号" in err.getvalue()


def test_mcp_server_reports_the_same_version():
    import mcp_server
    assert mcp_server.SERVER_INFO["version"] == version.read_version()


def test_turnover_projection_keeps_every_documented_field():
    """turnover 投影须保留 float_cap（流通市值）——codex 第四轮指出的丢字段隐患。

    原测试锁 tools._market 源码文本，已随 data/sources/mappers 重构失效
    （turnover 投影迁至 data.mappers.quote_from_turnover_rank）；改行为断言：
    喂含 float_cap 的 raw，断 Quote.float_market_cap 非空（比源码文本稳健）。
    注：industry 是源字段但 Quote 无此属性，新架构合法不投影，故不断言。
    """
    from data.mappers import quote_from_turnover_rank

    raw = {
        "code": "600519", "name": "贵州茅台",
        "price": 100.0, "pct": 1.5, "amount": 1000000,
        "mcap": 2000000000, "float_cap": 1500000000, "industry": "白酒",
    }
    q = quote_from_turnover_rank(raw)
    assert q.price == 100.0
    assert q.change_pct == 1.5
    assert q.turnover == 1000000
    assert q.market_cap == 2000000000
    assert q.float_market_cap == 1500000000  # float_cap 不得丢（codex 第四轮）
