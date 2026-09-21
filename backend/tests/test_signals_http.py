# C5' signals prefix 防回归 test（a73ca87 教训：prefix='/signals' 漏 /api 致 6 端点全 404）
# test_s218 mock router（mock theater）没抓 prefix bug——本 test 直接核 router 配置 + HTTP 真返 200
from fastapi.testclient import TestClient


def test_signals_router_prefix_and_routes():
    """C5' 防回归：signals router prefix='/api/signals' + 6 endpoint 路径对。

    a73ca87 教训：prefix='/signals' 漏 /api 致 6 端点全 404，test_s218 mock router
    没抓（mock theater）。本 test 直接核 router 配置，prefix 改坏立即抓。
    """
    from routers.signals import router
    assert router.prefix == "/api/signals", f"prefix 改坏！a73ca87 重演：{router.prefix}"
    paths = {route.path for route in router.routes}
    expected = {
        "/api/signals/status",
        "/api/signals/daily",
        "/api/signals/daily-report",
        "/api/signals/manual-trade",
        "/api/signals/manual-trades",
        "/api/signals/weekly-review",
    }
    missing = expected - paths
    assert not missing, f"endpoint 路径缺失：{missing}"


def test_signals_status_endpoint_200():
    """C5' HTTP 覆盖：GET /api/signals/status 返 200 + regime + arms 结构（非 404）。

    防回归：prefix 改坏 → /api/signals/status 返 404，本 test 立即抓。
    """
    import app as appmod
    client = TestClient(appmod.app)
    r = client.get("/api/signals/status")
    assert r.status_code == 200, f"/api/signals/status 返 {r.status_code}（prefix 改坏？）"
    data = r.json()
    assert "regime" in data, f"缺 regime 字段：{data}"
    assert "arms" in data, f"缺 arms 字段：{data}"
