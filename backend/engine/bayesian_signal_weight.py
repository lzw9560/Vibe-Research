# -*- coding: utf-8 -*-
"""S194 R3 · 贝叶斯信号权重（FS2，可 OOS）——每信号 Beta-Bernoulli 先验→后验权重。

延伸 S180 bayesian_arm_size 的 Beta-Bernoulli 模式（spec §2.1 FS2 + §3 R3 + §8 关联）：
- bayesian_arm_size 用交易胜负 + 后验下 5% 分位 ppf(0.05) → 保守仓位 sizing（risk-averse）；
- signal_weight 用信号历史命中率 + 后验**均值** → 融合权重（expected reliability，central）。
  权重用均值而非 ppf：融合权重表「该信号多可信」，中心估计自然；ppf 保守下界用于仓位决策
  （bayesian_arm_size 场景），语义不同。均值闭式 = (α+s)/(α+β+s+f)，无 scipy 依赖（ppf 需 scipy，
  可选 conservative 模式后续按需加）。FS2 可 OOS = 后验是 (先验+计数) 确定函数无随机性，walk-forward
  可重放（spec §2.1「FS2 后验是确定性函数，可 walk-forward OOS」）。

少样本先验主导（spec §6 风险「贝叶斯先验设定靠专家判断，少样本下影响大，须标先验驱动非数据驱动」）：
Beta(1,1) 无信息先验 + 0 数据 → 均值 0.5（中性），数据增后验自适应。ofi/fund_flow 无 trade_journal
arm 历史（不是 arm），权重长期靠先验 → 标先验驱动；gap/breakout/trend 有 arm reliability 数据时
后验自适应（但当前 underpowered，仍先验主导）。

underpowered 分级（reliability_tier，复刻 §44v2 应用规约 + query_winrate_trends label 语义）：
n_total<30 → insufficient（先验主导不出权重结论）/ n_days<60 → underpowered（探索性不判冗余，
复刻 §44v1 假阴性纠错）/ ≥60 → robust。R3 给权重时同款 tier gating——小样本标 underpowered 不判
reliability 高低，R5 F1 消融同款（spec §3 R5 + §6 风险）。
"""
from __future__ import annotations

# ── 默认专家先验（spec T3.2）─────────────────────────────────────────────────
# 5 融合信号的初始 Beta 先验。Beta(1,1)=无信息（均匀），均值 0.5 中性——不预置未经证实的 edge 假设。
# 诚实基线：所有信号默认 Beta(1,1)，数据稀缺时权重=0.5（先验驱动非数据驱动，spec §6 风险）。
# breakout（§44 naive lift=1.36x<2x 弱信号，Wilson CI 不重叠故非纯噪声）+ trend_arm（§44 exploratory
# 未验，0 signals）可由用户调保守先验（如 Beta(1,2)），但默认非信息避免注入未证实偏见。
# gap/ofi/fund_flow 无独立 §44 verdict → Beta(1,1) 中性。
DEFAULT_SIGNAL_PRIORS: dict[str, tuple[float, float]] = {
    "gap": (1.0, 1.0),
    "ofi": (1.0, 1.0),
    "breakout": (1.0, 1.0),
    "fund_flow": (1.0, 1.0),
    "trend_arm": (1.0, 1.0),
}


def beta_bernoulli_weight(
    n_success: int,
    n_fail: int,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> float:
    """Beta-Bernoulli 共轭后验均值 = 信号 reliability 权重。

    后验 Beta(prior_alpha + n_success, prior_beta + n_fail)，均值 = (a+s)/(a+b+s+f)。
    闭式无 scipy（ppf 保守下界用于仓位 sizing，见 bayesian_arm_size；权重用均值，语义不同）。

    Args:
        n_success: 信号历史命中次数（方向对）。
        n_fail: 信号历史失误次数（方向错）。
        prior_alpha/prior_beta: Beta 先验参数（默认 (1,1) 无信息；专家可设保守先验）。

    Returns:
        后验均值 ∈ (0,1)——信号 reliability 权重。少样本先验主导（Beta(1,1)+0 数据→0.5），
        数据增后验自适应。
    """
    a = prior_alpha + n_success
    b = prior_beta + n_fail
    return a / (a + b)


def reliability_tier(n_total: int, n_days: int) -> str:
    """§44v2 underpowered 分级（复刻 trade_journal.query_winrate_trends label 语义）。

    - n_total<30 → "insufficient"（样本太少先验主导，不出 reliability 结论）；
    - n_total≥30 且 n_days<60 → "underpowered"（探索性不判冗余，复刻 §44v1 假阴性纠错）；
    - n_total≥30 且 n_days≥60 → "robust"（可判）。

    n_total 短路：样本不够时不管 n_days 多大都 insufficient（先验主导）。
    R3 给权重 + R5 F1 消融 verdict 同款 tier gating（spec §3 R5 + §6 风险）。
    """
    if n_total < 30:
        return "insufficient"
    if n_days < 60:
        return "underpowered"
    return "robust"


class BayesianSignalWeight:
    """每信号 Beta-Bernoulli 先验→后验权重（FS2，spec §3 R3）。

    延伸 S180 bayesian_arm_size：arm_size 用交易胜负+ppf(0.05) 保守仓位；signal_weight 用信号
    历史命中率+后验均值作融合权重。少样本先验主导（Beta(1,1) 无信息），数据增后验自适应。

    per-signal 先验：priors={signal_name: (alpha, beta)}，缺省 Beta(1,1)。可靠性数据（n_success/n_fail）
    由调用方从 trade_journal.aggregate_by_arm(arm) 取 execution_winrate*n_picks 作 wins/losses
    （arm 5 粗粒度：gap/breakout/trend 有 arm 历史；ofi/fund_flow 不是 arm → 0/0 先验驱动）。
    """

    def __init__(self, priors: dict[str, tuple[float, float]] | None = None) -> None:
        """初始化 per-signal 先验。无 priors → 全部默认 Beta(1,1) 无信息。"""
        self._priors: dict[str, tuple[float, float]] = dict(priors) if priors else {}

    def weight(self, signal_name: str, n_success: int, n_fail: int) -> float:
        """单信号后验权重。未配先验的信号用默认 Beta(1,1)。"""
        a0, b0 = self._priors.get(signal_name, (1.0, 1.0))
        return beta_bernoulli_weight(n_success, n_fail, a0, b0)

    def weights(self, reliability: dict[str, tuple[int, int]]) -> dict[str, float]:
        """批量：reliability={signal: (n_success, n_fail)} → {signal: weight}（spec §3 R3 输出）。"""
        return {name: self.weight(name, s, f) for name, (s, f) in reliability.items()}
