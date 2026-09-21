# C5' §44 core guard 防回归 test（agent T4：evaluation.py/verifier.py §44 core 无测试）
# 覆盖 _x1dot0_upgrade_permitted——×1.0 verdict 落地关键函数（guard 读 env 解锁 freeze gate）


def test_x1dot0_upgrade_permitted_env_set(monkeypatch):
    """env VR_ALLOW_X1DOT0=1 → guard True（×1.0 解锁，freeze gate 开）"""
    monkeypatch.setenv("VR_ALLOW_X1DOT0", "1")
    from candidate_funnel.evaluation import _x1dot0_upgrade_permitted
    assert _x1dot0_upgrade_permitted() is True


def test_x1dot0_upgrade_permitted_env_unset_defaults_false(monkeypatch):
    """env 未设 → guard = _FRESH_HARNESS_VERDICT（默认 False，×1.0 freeze-gated）"""
    monkeypatch.delenv("VR_ALLOW_X1DOT0", raising=False)
    from candidate_funnel.evaluation import (
        _x1dot0_upgrade_permitted,
        _FRESH_HARNESS_VERDICT,
    )
    assert _x1dot0_upgrade_permitted() is _FRESH_HARNESS_VERDICT
    assert _FRESH_HARNESS_VERDICT is False, "默认须 False——×1.0 unlock 须 env=1，非代码永久许可"
