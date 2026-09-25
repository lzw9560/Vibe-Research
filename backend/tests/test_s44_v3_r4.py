# -*- coding: utf-8 -*-
"""S229 A5 回归测试（pytest 版）：§44 v3 R1/R3/R4 抓 consecutive_relay V1 假 edge。

从 s203_consecutive_relay_harness_v3.py 抽逻辑成 pytest，进 CI 防回归。
验收：R1 filter 掉 >70% picks（V1 假 edge 是涨停封板溢价）+ filter 后 edge <+0.3%。

跑：cd backend && .venv/bin/python -m pytest tests/test_s44_v3_r4.py -v
"""
import pytest

from tools.s203_consecutive_relay_harness_v3 import compute_obs_v3  # noqa: E402
from tools.s203_consecutive_relay_harness import _zt_history_picks_lbc2  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402


def _stats(obs):
    if not obs:
        return None
    rets = [o["edge"] for o in obs]
    wr = sum(o["win"] for o in obs) / len(obs)
    return {"n": len(obs), "mean": sum(rets) / len(rets) * 100, "wr": wr * 100}


@pytest.fixture(scope="module")
def v3_obs():
    """跑 compute_obs_v3 一次（真数据 505MB kline cache + picks），module scope 复用。"""
    cache = _load_kline_cache()
    picks = _zt_history_picks_lbc2()
    if not picks:
        pytest.skip("无 lbc>=2 picks（zt_history 数据未 backfill）")
    return compute_obs_v3(cache, picks)


def test_r1_filter_catches_v1_fake_edge(v3_obs):
    """R1 close 涨停价 filter 掉 >70% picks——V1 假 edge 是涨停封板溢价证据。"""
    s_all = _stats(v3_obs)
    obs_r1r3 = [o for o in v3_obs if not o["r1_close_limit"] and not o["r3_onesell"]]
    s_r1r3 = _stats(obs_r1r3)
    n_v1 = s_all["n"]
    n_r1r3 = s_r1r3["n"] if s_r1r3 else 0
    filter_pct = (n_v1 - n_r1r3) / n_v1 * 100 if n_v1 else 0
    assert filter_pct > 70, (
        f"R1 只 filter 掉 {filter_pct:.1f}% < 70%——V1 假 edge 非纯涨停封板溢价"
    )


def test_v1_edge_collapses_after_r1_filter(v3_obs):
    """R1+R3 filter 后 V1 edge <+0.3%——涨停封板溢价被 filter 后无 edge。"""
    obs_r1r3 = [o for o in v3_obs if not o["r1_close_limit"] and not o["r3_onesell"]]
    s_r1r3 = _stats(obs_r1r3)
    if not s_r1r3:
        pytest.skip("R1+R3 filter 后无 picks（V1 全假 edge——99.4% 涨停）")
    assert s_r1r3["mean"] < 0.3, (
        f"R1+R3 filter 后 edge {s_r1r3['mean']:.2f}% >= +0.3%——非 V1 假 edge"
    )


def test_r4_survivorship_flag_set(v3_obs):
    """R4 涨停股 flag（r4_zt）被正确标注——consecutive_relay 99.4% 涨停。"""
    obs_zt = [o for o in v3_obs if o["r4_zt"]]
    zt_pct = len(obs_zt) / len(v3_obs) * 100 if v3_obs else 0
    assert zt_pct > 70, (
        f"涨停股占 {zt_pct:.1f}% < 70%——consecutive_relay 应 99.4% 涨停"
    )
