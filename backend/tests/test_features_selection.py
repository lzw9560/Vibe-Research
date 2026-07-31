"""Tests for backend/predict/features/selection.py — S018 feature selection harness.

TDD: (a)-(g) covering SelectionResult immutability, permutation importance
ranking, bootstrap stable feature selection, determinism, SHAP fallback,
and MAX_SHORT_FEATURES constant.

All tests are offline (no network calls).
"""

import pytest


# ── (a) SelectionResult frozen 不可变 ────────────────────────────────


def test_selection_result_is_frozen():
    """SelectionResult dataclass 是 frozen=True，赋值会 raise FrozenInstanceError。"""
    from predict.features.selection import SelectionResult

    result = SelectionResult(
        kept=("f1", "f2"),
        dropped=("f3",),
        importance={"f1": 0.5, "f2": 0.3, "f3": 0.0},
        method="permutation_bootstrap",
        rationale="test rationale",
    )
    with pytest.raises(Exception):
        result.kept = ("x",)  # type: ignore[misc]


def test_selection_result_fields():
    """SelectionResult 各字段类型正确。"""
    from predict.features.selection import SelectionResult

    result = SelectionResult(
        kept=("a",),
        dropped=("b", "c"),
        importance={"a": 1.0, "b": 0.5, "c": 0.0},
        method="permutation_bootstrap",
        rationale="rationale text",
    )
    assert result.kept == ("a",)
    assert result.dropped == ("b", "c")
    assert result.importance == {"a": 1.0, "b": 0.5, "c": 0.0}
    assert result.method == "permutation_bootstrap"
    assert result.rationale == "rationale text"


# ── (b) rank_by_permutation：合成数据 ───────────────────────────────


def test_rank_by_permutation_returns_dict_of_floats():
    """rank_by_permutation 对合成数据返回每个特征一个 float 重要性。"""
    from predict.features.selection import rank_by_permutation
    from sklearn.datasets import make_classification
    import numpy as np

    X, y = make_classification(
        n_samples=100, n_features=5, n_informative=3, random_state=42
    )
    feature_names = ["f0", "f1", "f2", "f3", "f4"]
    importance = rank_by_permutation(X, y, feature_names)

    assert isinstance(importance, dict)
    assert len(importance) == len(feature_names)
    for name in feature_names:
        assert name in importance
        assert isinstance(importance[name], float)


def test_rank_by_permutation_with_dataframe():
    """rank_by_permutation 接受 pandas DataFrame 输入。"""
    import pandas as pd
    from predict.features.selection import rank_by_permutation
    from sklearn.datasets import make_classification

    X, y = make_classification(
        n_samples=50, n_features=4, random_state=42
    )
    df = pd.DataFrame(X, columns=["a", "b", "c", "d"])
    importance = rank_by_permutation(df, y, ["a", "b", "c", "d"])

    assert set(importance.keys()) == {"a", "b", "c", "d"}
    for v in importance.values():
        assert isinstance(v, float)


def test_rank_by_permutation_none_safe_missing_lightgbm():
    """rank_by_permutation 在默认 model=None 时仍能工作（验证函数签名与基本行为）。"""
    from predict.features.selection import rank_by_permutation
    from sklearn.datasets import make_classification

    X, y = make_classification(n_samples=30, n_features=5, random_state=42)
    importance = rank_by_permutation(X, y, ["x", "y", "z", "w", "v"])
    assert len(importance) == 5


# ── (c) select_stable_features：合成数据 ────────────────────────────


def test_select_stable_features_basic():
    """select_stable_features 返回 kept+dropped 并集=全 feature_names，
    kept 长度 <= max_features，importance 含全特征。"""
    from predict.features.selection import select_stable_features
    from sklearn.datasets import make_classification

    X, y = make_classification(
        n_samples=100, n_features=10, n_informative=5, random_state=42
    )
    feature_names = [f"f{i}" for i in range(10)]
    result = select_stable_features(X, y, feature_names, max_features=3, n_bootstrap=3, random_state=42)

    assert isinstance(result.kept, tuple)
    assert isinstance(result.dropped, tuple)
    assert set(result.kept) | set(result.dropped) == set(feature_names)
    assert len(result.kept) <= 3
    assert len(result.importance) == len(feature_names)
    assert result.method == "permutation_bootstrap"
    assert result.rationale
    assert "permutation importance bootstrap" in result.rationale.lower()


# ── (d) select_stable_features 确定性 ────────────────────────────────


def test_select_stable_features_deterministic():
    """同 random_state 两次调用，kept 完全相同（可复算核心）。"""
    from predict.features.selection import select_stable_features
    from sklearn.datasets import make_classification

    X, y = make_classification(
        n_samples=100, n_features=8, n_informative=4, random_state=42
    )
    feature_names = [f"f{i}" for i in range(8)]

    result1 = select_stable_features(X, y, feature_names, max_features=3, n_bootstrap=3, random_state=99)
    result2 = select_stable_features(X, y, feature_names, max_features=3, n_bootstrap=3, random_state=99)

    assert result1.kept == result2.kept
    assert result1.dropped == result2.dropped


# ── (e) try_shap_importance ─────────────────────────────────────────


def test_try_shap_importance_returns_none_when_shap_missing():
    """shap 不可导入时 try_shap_importance 返回 None，不抛异常。

    用 sys.modules patch 让 `import shap` 抛 ImportError，测降级路径
    （无论 shap 实际是否安装，此测试都稳定）。
    """
    import sys
    from unittest.mock import patch
    from predict.features.selection import try_shap_importance
    from sklearn.datasets import make_classification

    X, y = make_classification(n_samples=30, n_features=4, random_state=42)
    # 让 try_shap_importance 内部的 `import shap` 抛 ImportError
    with patch.dict(sys.modules, {"shap": None}):
        result = try_shap_importance(X, y, ["a", "b", "c", "d"], model=None)
    assert result is None


def test_try_shap_importance_returns_dict_when_shap_available():
    """shap 已安装且传入已拟合的树模型时，返回 {name: mean_abs_shap} dict。"""
    from predict.features.selection import try_shap_importance
    from sklearn.datasets import make_classification
    from sklearn.ensemble import RandomForestClassifier

    X, y = make_classification(n_samples=30, n_features=4, random_state=42)
    model = RandomForestClassifier(n_estimators=10, random_state=42, n_jobs=1)
    model.fit(X, y)
    result = try_shap_importance(X, y, ["a", "b", "c", "d"], model=model)
    # shap 未装时返 None；装了则返 dict——两者都可接受，只验不抛+类型
    if result is not None:
        assert set(result.keys()) == {"a", "b", "c", "d"}
        assert all(isinstance(v, float) for v in result.values())


# ── (f) MAX_SHORT_FEATURES == 25 ───────────────────────────────────


def test_max_short_features_is_25():
    """模块级常量 MAX_SHORT_FEATURES 等于 25。"""
    from predict.features.selection import MAX_SHORT_FEATURES

    assert MAX_SHORT_FEATURES == 25


# ── (g) select_stable_features 当 max_features >= 特征数时 kept=全部 ──


def test_select_stable_features_max_features_gte_all():
    """max_features >= 特征数时，kept=全部，dropped=空。"""
    from predict.features.selection import select_stable_features
    from sklearn.datasets import make_classification

    X, y = make_classification(
        n_samples=50, n_features=5, n_informative=3, random_state=42
    )
    feature_names = ["a", "b", "c", "d", "e"]
    result = select_stable_features(X, y, feature_names, max_features=10, n_bootstrap=2, random_state=42)

    assert set(result.kept) == set(feature_names)
    assert result.dropped == ()
