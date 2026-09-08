// S171 MOCK fixture——价值因子月度验证 bundle（canonical 场景：双角度矛盾→不能定论）。
// 数据来源：specs/S171-长线价值/ui-contract.md §6 canonical mock 场景（非真实 verdict）。
// 真实 verdict 由 backend/tools/long_value_run.py 跑出后落 Recorder，UI 经
// /api/verifier/records 读真实值替换（params.experiment_id==='S171' 过滤）。
// 当前 long_value_run.py 未实现，前端先用此 mock 落地页面（UI 先行，memory ui-first-implementation-order）。
//
// 场景设计（代表性，非任意）：
//  -0.5 档（退市亏一半）：① 弱正信号 ② 弱信号 → 综合"不能定论"
//  -1.0 档（退市归零）  ：① 证否        ② 证否   → 综合"证否"
//  → 退市档翻结论 = 第二关不过 = 综合降级"不能定论"（不是证否，是"依赖退市假设，不可信为稳"）
import type { S171ValueBundle, RecorderRecord } from "@/lib/verifier-contract";

const FROZEN = "822db17"; // S171 spec 定稿 commit

// 角度① 对冲版（做多低 PE + 做空高 PE，看价差收益）—— event edge，用平均收益+显著性
function p1(tier: -0.5 | -1.0): RecorderRecord {
  const is05 = tier === -0.5;
  return {
    recorder_id: `rec_s171_p1_${is05 ? "t1" : "t2"}`,
    data_snapshot_id: `s171:q1q5_spread:${is05 ? "delist05" : "delist10"}`,
    input_snapshot_hash: `sha256:s171p1${is05 ? "05" : "10"}...`,
    params: {
      experiment_id: "S171",
      co_primary_role: "primary_1",
      delisting_return: tier,
      event_materiality_floor: 0.001,
      round_trip_cost: 0.0025,
      walk_train: 36,
      walk_test: 12,
      step: 12,
      holding_horizon: "1m",
      n_comparisons: 4,
    },
    n_trials: 4,
    verdict: {
      status: is05 ? "exploratory" : "falsified",
      lift: null,
      ci_low: null,
      ci_high: null,
      p_bonferroni: is05 ? 0.136 : 0.681,
      dsr: null, pbo: null, haircut: null, min_trl: null,
      days_robust: 87,
      n: 87,
      n_effective: 87,
      edge_type: "event",
      tradeable: false, // 对冲版做空 A 股受限，不能直接交易
      event_metrics: {
        mean_return: is05 ? 0.0031 : 0.00085,  // +0.31% / +0.085% 月
        net_mean: is05 ? 0.0018 : -0.00066,    // +0.18% / -0.066% 月（扣成本后）
        win_rate: is05 ? 0.52 : 0.49,
        t_stat_day_clustered: is05 ? 1.82 : 0.41,
        n_event: 87,
        base_rate: 0.50,
      },
      event_status: is05 ? "event_thin_positive" : "event_falsified",
      dsr_method: "lenient_single_estimate",
      frozen_commit: FROZEN,
      updated_commit: null,
      updated_at: null,
      data_snapshot_id: null,
      note: is05
        ? "弱正信号：价差月均 +0.18%（扣成本后），但 t=1.82 没到显著线。价值溢价方向对、不够强。"
        : "退市按归零算后价差转负，证否。结论依赖退市损失假设，不可信为稳。",
    },
    timestamp: "2026-09-08T20:00:00Z",
  };
}

// 角度② 只做多版（低 PE 跑赢全市场）—— selection edge，用选股准不准倍数（lift）
function p2(tier: -0.5 | -1.0): RecorderRecord {
  const is05 = tier === -0.5;
  return {
    recorder_id: `rec_s171_p2_${is05 ? "t1" : "t2"}`,
    data_snapshot_id: `s171:q1_excess_universe:${is05 ? "delist05" : "delist10"}`,
    input_snapshot_hash: `sha256:s171p2${is05 ? "05" : "10"}...`,
    params: {
      experiment_id: "S171",
      co_primary_role: "primary_2",
      delisting_return: tier,
      event_materiality_floor: 0.001,
      round_trip_cost: 0.0025,
      walk_train: 36,
      walk_test: 12,
      step: 12,
      purged_kfold_lift: is05 ? 1.04 : 0.91,
      walk_forward_lift: is05 ? 1.06 : 0.89,
      holding_horizon: "1m",
      n_comparisons: 4,
    },
    n_trials: 4,
    verdict: {
      status: is05 ? "not_validated" : "falsified",
      lift: is05 ? 1.18 : 0.94,  // 选股准不准倍数，>2 才算稳
      ci_low: is05 ? 0.97 : 0.76,
      ci_high: is05 ? 1.42 : 1.18,
      p_bonferroni: is05 ? 0.136 : 0.681,
      dsr: null, pbo: null, haircut: null, min_trl: null,
      days_robust: 87,
      n: 87,
      n_effective: 87,
      edge_type: "selection",
      tradeable: true, // 只做多，可以实际交易
      event_metrics: null,
      event_status: null,
      dsr_method: "N/A",
      frozen_commit: FROZEN,
      updated_commit: null,
      updated_at: null,
      data_snapshot_id: null,
      note: is05
        ? "弱信号：选股倍数 1.18（>1 但远没到 2.0 稳线）。样本外 lift 衰减到 1.04，接近随机。"
        : "退市按归零算后选股倍数跌破 1.0（不如全市场），证否。",
    },
    timestamp: "2026-09-08T20:00:00Z",
  };
}

// 角度③ 跑赢沪深 300（size-confounded，大盘对比）
const secondary: RecorderRecord = {
  recorder_id: "rec_s171_secondary_hs300",
  data_snapshot_id: "s171:q1_excess_hs300",
  input_snapshot_hash: "sha256:s171sec...",
  params: {
    experiment_id: "S171",
    co_primary_role: "secondary",
    delisting_return: -0.5,
    round_trip_cost: 0.0025,
    n_comparisons: 1,
  },
  n_trials: 1,
  verdict: {
    status: "not_validated",
    lift: null,
    ci_low: null, ci_high: null,
    p_bonferroni: null,
    dsr: null, pbo: null, haircut: null, min_trl: null,
    days_robust: 87,
    n: 87,
    n_effective: 87,
    edge_type: "event",
    tradeable: true,
    event_metrics: {
      mean_return: 0.004, net_mean: 0.0028, win_rate: 0.55,
      t_stat_day_clustered: 1.4, n_event: 87, base_rate: 0.50,
    },
    event_status: "event_thin_positive",
    dsr_method: "N/A",
    frozen_commit: FROZEN,
    updated_commit: null, updated_at: null, data_snapshot_id: null,
    note: "跑赢沪深 300 月均 +0.28%，但沪深 300 偏大盘，价值股偏中小盘，不是纯价值效果（size 混淆）。",
  },
  timestamp: "2026-09-08T20:00:00Z",
};

export const s171ValueMock: S171ValueBundle = {
  co_primary_1_tier1: p1(-0.5),
  co_primary_2_tier1: p2(-0.5),
  co_primary_1_tier2: p1(-1.0),
  co_primary_2_tier2: p2(-1.0),
  auxiliary: null, // F2 PE+ROE 待数据够再跑
  secondary,

  gates: {
    cross_check: {
      passed: true,
      label: "方向一致",
      detail: "两个角度都说「没到稳线」——① 价差弱正、② 选股弱信号，方向不矛盾。但一致≠稳，只是没打架。",
      severity: "good",
    },
    sensitivity: {
      passed: false,
      label: "退市一翻结论",
      detail: "退市亏一半→「不能定论」，退市归零→「证否」。结论依赖「退市亏多少」这个假设，不能当稳的用。",
      severity: "critical",
    },
    coverage: {
      passed: true,
      label: "退市数据够（勉强）",
      detail: "严格覆盖 58%（过 50% 线），但 0 根 K 线的退市股占 12%——这些 value trap 缺失，方向是高估价值。",
      severity: "warning",
    },
  },
  combined_status: "exploratory", // 互验过 + 退市关不过 + 覆盖关过 = 没全过 → 降级

  coverage_audit: {
    lenient_pct: 0.88,   // 88% 退市股至少有 K 线
    strict_pct: 0.58,    // 58% 完整覆盖（过 50% 线但不到 80%）
    zero_bars_count: 40, // 40 只退市股一根 K 线都没有
    total_delisted: 295,
    bias_direction: "favors_value",
  },
  sensitivity_rows: [
    { delisting_return: -0.5, primary_1_event_status: "event_thin_positive", primary_2_status: "not_validated", primary_2_lift: 1.18, combined: "exploratory" },
    { delisting_return: -1.0, primary_1_event_status: "event_falsified", primary_2_status: "falsified", primary_2_lift: 0.94, combined: "falsified" },
  ],

  bug_fixes: [
    { id: 1, title: "前复权 PE 虚低", detail: "前复权价调到当前股本，但盈利是原始股本，PE 算出来偏低", fix: "PE 用不复权价算，收益仍用前复权（含送转分红）", severity: "critical", status: "fixed" },
    { id: 2, title: "历史股票池是否真·当时", detail: "baostock query_all_stock 返回的是当时点还是当前快照，没验", fix: "已抽查 3 个月末含即将退市股→确认是当时点，但已退市股覆盖不全，harness 兜底重建", severity: "critical", status: "pending" },
    { id: 3, title: "退市日期空着两种意思", detail: "outDate 为空可能是「还活着」也可能是「漏标了退市」", fix: "K 线最后一条远早于现在（>6 月无更新）标「疑似漏标退市」踢出股票池", severity: "high", status: "fixed" },
    { id: 4, title: "退市股没 K 线补不回来", detail: "有些退市股一根 K 线都没有，无法知道它哪个月还活着，无法注入亏损", fix: "计入分母算 0% 覆盖，>5% 标「不可恢复偏差」降级", severity: "critical", status: "annotated" },
    { id: 5, title: "多重检验校正 K=1 失效", detail: "只有 1 个对比时 BH 校正等于没校正（潜在，当前 K=1 无害）", fix: "扩到 K≥2 时 harness 层强制 Bonferroni，不依赖 stats 自动校正", severity: "latent", status: "annotated" },
    { id: 6, title: "月频收益门槛没存", detail: "月频用的 0.1% 门槛没存进 Recorder，复算会用日频默认 0.3%→结论翻转", fix: "event_materiality_floor=0.001 存进 Recorder params，复算一致", severity: "high", status: "fixed" },
    { id: 7, title: "财报当天用盘后数据", detail: "pubDate ≤ D 允许当天用盘后财报配盘前价=未来信息", fix: "改 pubDate < D 严格小于（约 25% 月份受影响）", severity: "critical", status: "fixed" },
    { id: 8, title: "同日财报取错季度", detail: "同一天披露多个季度时，按字典顺序取到 Q4 而非最新 Q1", fix: "加 (pubDate, quarter_key) 二级排序，quarter_key 解析成(年,季)数字降序", severity: "high", status: "fixed" },
    { id: 9, title: "停牌股用旧价算 PE", detail: "停牌股当日无成交，close 是几天前的旧价，PE 偏低误入价值股", fix: "当日 volume=0 或无 K 线的停牌股，从股票池和 Q1/Q5 候选双重踢出", severity: "high", status: "fixed" },
  ],

  extrapolation_warnings: [
    "月频不是长线结论——从月频外推到年频是错窗口镜像，3/6/12 月因样本不够不出正式结论",
    "这段周期（2018-2026）偏成长股行情（2019-2021 成长 rally），证否只是这段的结论不是全周期",
    "改了两个变量（窗口 3 天→1 月 + 股票池 涨停→全 A），分不清是哪个让结论变",
    "对冲版（角度①）不能直接交易——A 股做空难又贵，只有只做多版（角度②）能实际做",
    "月末最后交易日买入，月底资金面紧张可能系统性污染买入价",
  ],
  st_separation: {
    verification: "验证层保留 *ST（保守，不删 value trap 尾部，保「不剔退市」一致）",
    capture: "实盘层避开 *ST（涨跌停 ±5%+流动性差+退市风险，不买）",
  },
  deferred_factors: [
    "F2 PE+ROE 复合因子——数据够再跑（Family C K=1）",
    "F3 低 PB——用盈利/ROE 反推账面价值在 3/4 季度失效（口径不匹配），只有年报 Q4 能用",
    "PE 是务实代理不是正宗 B/M（Fama-French 用账面市值比，baostock 没有账面价值字段）",
  ],
  caveats: [
    "财报重述风险——baostock 可能存修正后的盈利但保留原始披露日，披露日早≠值是原始值",
    "换手率敏感度——月度调仓换手 20-50%+，成本拖累年化可能 3% 非 1.5%，首跑后实测加敏感度",
    "月度自相关——价值组合慢变，同股连续月在低 PE，跨月自相关违反独立假设，t 值偏高",
    "Newey-West HAC 标准误留待（处理自相关的正宗方法，当前用 day-clustered t 近似）",
  ],
};
