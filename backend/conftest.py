"""pytest 配置：把 backend 目录加进 sys.path，注册 live 标记，隔离用户数据目录。"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

# 用户数据隔离：portfolio / myreports 在 import 时按 VR_DATA_DIR / VR_REPORTS_DIR 固化路径，
# 必须赶在任何测试模块 import app 之前指到临时目录——否则持仓 CRUD 类测试会增删真实
# 项目内 .vibe-research/ 里的用户数据（比如把用户真实持有的 600519 合并后删掉）。
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="vr-test-data-")
os.environ["VR_DATA_DIR"] = _TEST_DATA_DIR
os.environ["VR_REPORTS_DIR"] = os.path.join(_TEST_DATA_DIR, "myreports")
# HistGradientBoosting 在 Windows 多进程残留时 OpenMP 易死锁；测试统一单线程防 hang
os.environ.setdefault("OMP_NUM_THREADS", "1")


@pytest.fixture
def isolated_market_db(tmp_path, monkeypatch):
    """把 scheduled_tasks._DB_PATH 重定向到 pytest 临时目录，隔离真实 backend/data/market_data.db。"""
    import scheduled_tasks as st

    db_path = tmp_path / "market_data.db"
    monkeypatch.setattr(st, "_DB_PATH", str(db_path))
    # 新库需先建表（模块 import 时的 _ensure_tables 只针对真实路径）
    st._ensure_tables()
    yield str(db_path)


@pytest.fixture
def cron_scheduler():
    """返回全新 CronScheduler 实例（_should_run 委托 cron_match 的单测用）。"""
    from scheduled_tasks import CronScheduler

    return CronScheduler()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: 打真实数据源的网络冒烟测（会联网、可能受上游/限流影响；默认可 -m 'not live' 跳过）",
    )
