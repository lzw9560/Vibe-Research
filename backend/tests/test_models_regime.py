import numpy as np
import pytest


class TestGaussianMixtureRegimeSwitcher:
    """GaussianMixtureRegimeSwitcher unit tests (RED first, TDD)."""

    # ------------------------------------------------------------------
    # (a) fit 不抛，predict_state 返 shape (n,)，值∈{0,1,2}（n_components=3）
    # ------------------------------------------------------------------
    def test_fit_predict_shape_and_values(self):
        # Arrange
        np.random.seed(42)
        features = self._synthetic_data(n_samples=300, n_components=3)
        from predict.models.regime import GaussianMixtureRegimeSwitcher

        # Act
        model = GaussianMixtureRegimeSwitcher(n_components=3, random_state=42)
        model.fit(features)
        states = model.predict_state(features)

        # Assert
        assert states.shape == (300,)
        assert set(states.tolist()).issubset({0, 1, 2})

    # ------------------------------------------------------------------
    # (b) regime_labels() 返 dict，键 0/1/2，值∈{"牛","震荡","熊"}，
    #     且"牛"对应最高收益率均值成分
    # ------------------------------------------------------------------
    def test_regime_labels_three_components(self):
        # Arrange
        np.random.seed(42)
        features = self._synthetic_data(n_samples=300, n_components=3)
        from predict.models.regime import GaussianMixtureRegimeSwitcher

        model = GaussianMixtureRegimeSwitcher(n_components=3, random_state=42)
        model.fit(features)
        labels = model.regime_labels()

        # Assert structure
        assert isinstance(labels, dict)
        assert set(labels.keys()) == {0, 1, 2}
        assert set(labels.values()).issubset({"牛", "震荡", "熊"})

        # Assert "牛" corresponds to highest mean-return component
        means = model.model.means_[:, 0]
        sorted_idx = np.argsort(means)[::-1]
        bull_label = labels[sorted_idx[0]]
        assert bull_label == "牛", f"Expected '牛' for highest mean-return component, got {bull_label}"

    # ------------------------------------------------------------------
    # (c) 确定性：同 random_state 两次 fit+predict_state 结果完全相等
    # ------------------------------------------------------------------
    def test_determinism_with_fixed_random_state(self):
        # Arrange
        np.random.seed(42)
        features = self._synthetic_data(n_samples=300, n_components=3)
        from predict.models.regime import GaussianMixtureRegimeSwitcher

        # Act
        model1 = GaussianMixtureRegimeSwitcher(n_components=3, random_state=42)
        model1.fit(features)
        states1 = model1.predict_state(features)

        model2 = GaussianMixtureRegimeSwitcher(n_components=3, random_state=42)
        model2.fit(features)
        states2 = model2.predict_state(features)

        # Assert
        np.testing.assert_array_equal(states1, states2)

    # ------------------------------------------------------------------
    # (d) n_components=2 时 regime_labels 值{"牛","熊"}
    # ------------------------------------------------------------------
    def test_regime_labels_two_components(self):
        # Arrange
        np.random.seed(42)
        features = self._synthetic_data(n_samples=200, n_components=2)
        from predict.models.regime import GaussianMixtureRegimeSwitcher

        model = GaussianMixtureRegimeSwitcher(n_components=2, random_state=42)
        model.fit(features)
        labels = model.regime_labels()

        # Assert
        assert set(labels.keys()) == {0, 1}
        assert set(labels.values()).issubset({"牛", "熊"})

    # ------------------------------------------------------------------
    # (e) backends() == "gaussian_mixture"
    # ------------------------------------------------------------------
    def test_backend_returns_gaussian_mixture(self):
        from predict.models.regime import GaussianMixtureRegimeSwitcher

        model = GaussianMixtureRegimeSwitcher(n_components=3, random_state=42)
        assert model.backend() == "gaussian_mixture"

    # ------------------------------------------------------------------
    # (f) predict_state 单样本 (1, 2) 不抛
    # ------------------------------------------------------------------
    def test_predict_state_single_sample(self):
        # Arrange
        np.random.seed(42)
        features = self._synthetic_data(n_samples=300, n_components=3)
        from predict.models.regime import GaussianMixtureRegimeSwitcher

        model = GaussianMixtureRegimeSwitcher(n_components=3, random_state=42)
        model.fit(features)

        # Act & Assert (should not raise)
        single = np.array([[0.01, 0.02]])
        result = model.predict_state(single)
        assert result.shape == (1,)
        assert result[0] in {0, 1, 2}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _synthetic_data(self, n_samples: int, n_components: int) -> np.ndarray:
        """Generate synthetic [return, volatility] data with n_components clusters."""
        np.random.seed(42)
        if n_components == 3:
            # Bull: high return, low vol
            bull = np.random.multivariate_normal([0.03, 0.01], [[0.0004, 0.0], [0.0, 0.0001]], size=n_samples // 3)
            # Bear: low return, high vol
            bear = np.random.multivariate_normal([-0.02, 0.03], [[0.001, 0.0], [0.0, 0.0009]], size=n_samples // 3)
            # Neutral: mid return, mid vol
            neutral = np.random.multivariate_normal([0.005, 0.015], [[0.0006, 0.0], [0.0, 0.0004]], size=n_samples // 3)
            return np.vstack([bull, bear, neutral])
        elif n_components == 2:
            bull = np.random.multivariate_normal([0.03, 0.01], [[0.0004, 0.0], [0.0, 0.0001]], size=n_samples // 2)
            bear = np.random.multivariate_normal([-0.02, 0.03], [[0.001, 0.0], [0.0, 0.0009]], size=n_samples // 2)
            return np.vstack([bull, bear])
        else:
            raise ValueError(f"Unsupported n_components for synthetic data: {n_components}")
