// S165 R4: UI 契约先行——类型匹配 S161 v2 §2 Verdict dataclass + Recorder schema EXACTLY。
// 后端实现这些 schema（UI 驱动，非反之）。改 S161 Verdict 字段须同步改本文件（双向锁）。
// Anchor: S161 v2 Verdict dataclass + Recorder schema ONLY（drop evaluation_lifts.db phantom—undefined）。
// MOCK: 尚未接线后端 /api/verifier/records，当前仅 frontend mock fixture 使用。
// v2: 加 not_validated(第5态) + edge_type/tradeable/event_metrics/event_status/dsr_method/n_effective/updated_*/data_snapshot_id;
//     三窗口表去 IC/lift（S159 §5A: mean+中位+胜率+base_rate only）。

// S161 R1: Verdict dataclass — verify() 纯函数返回值，不可变。
export interface Verdict {
  status: VerifierStatus;
  lift: number | null;
  ci_low: number | null;
  ci_high: number | null;
  p_bonferroni: number | null;
  dsr: number | null;
  pbo: number | null;
  haircut: number | null;
  min_trl: number | null;
  days_robust: number;
  n: number;
  n_effective: number | null; // v2: day_paired effective n（derived，非 Verdict.n）
  edge_type: EdgeType; // v2: selection|event|population，治外推
  tradeable: boolean; // v2: 机器可读"不可交易"，区别"无 edge"
  event_metrics: EventMetrics | null; // v2: event edge 用 t-test/二项非 lift
  event_status: EventStatus | null; // v2: event 子结论独立于 selection status
  dsr_method: DsrMethod; // v2: 透明标 lenient 降级
  frozen_commit: string;
  updated_commit: string | null; // v2: 回溯后覆盖
  updated_at: string | null; // v2: 回溯后覆盖
  data_snapshot_id: string | null; // v2: as_of/PIT bundle-id
  note: string;
}

// S161 R4: RecorderRecord — qlib Recorder 模式实验追踪，一条 recorder_id 可复现。
export interface RecorderRecord {
  recorder_id: string;
  data_snapshot_id: string | null; // v2: as_of/PIT bundle-id（接 S162 pit_store）
  input_snapshot_hash: string;
  params: Record<string, unknown>;
  n_trials: number;
  verdict: Verdict;
  timestamp: string; // ISO 8601
}

// S165 R1: 前置窗口 sanity（S159 §5A authoritative）— 三窗口对比，定位优势窗口。
// v2: 去 IC/lift — window sanity 是轻定位非 lift/IC 计算；IC 属 post-sanity verifier 步。
export interface WindowStats {
  mean: number | null;
  median: number | null;
  win_rate: number | null;
  base_rate: number | null;
}

export interface ThreeWindowCompare {
  overnight_gap: WindowStats; // 隔夜 gap（D 收盘→D+1 开盘）
  d1_intraday: WindowStats; // D+1 日内（开→收）
  path: WindowStats; // path（D+1 开→exit，§44 v1 框架口径）
}

// S165 R1: overfit 统计占位——PBO/CSCV/DSR/Haircut/MinTRL，S161 wire 后填实。
export interface OverfitStats {
  pbo: number | null; // Probability of Backtest Overfitting
  cscv: number | null; // Combinatorially Symmetric Cross-Validation
  dsr: number | null; // Deflated Sharpe Ratio
  haircut: number | null; // 多重检验 haircut（Bonferroni/Holm/BHY）
  min_trl: number | null; // Minimum Track Record Length
}

// S161 R1: Verdict.status 五态枚举（v2 加 not_validated）
export type VerifierStatus =
  | "robust_edge"
  | "underpowered"
  | "falsified"
  | "not_validated"
  | "exploratory";

// S161 R1 v2: edge_type — 区分 selection vs event/population edge，治外推
export type EdgeType = "selection" | "event" | "population";

// S161 R1 v2: event_metrics — event edge 用 t-test/二项非 lift
export interface EventMetrics {
  mean_return: number | null;
  net_mean: number | null;
  win_rate: number | null;
  t_stat_day_clustered: number | null;
  n_event: number | null;
  base_rate: number | null;
}

// S161 R1 v2: event_status — event 子结论独立于 selection status
export type EventStatus =
  | "event_robust"
  | "event_thin_positive"
  | "event_falsified"
  | "event_not_tested";

// S161 R1 v2: dsr_method — 透明标 lenient 降级
export type DsrMethod =
  | "cross_trial_variance"
  | "lenient_single_estimate"
  | "N/A";

// S165 R6: 三层 reframe（grill #5）— selection 展示终态 / direction deferred / infra built
export type LayerType = "selection" | "direction" | "infra";

// S165 R1: DimensionValidationCard 字段（扩展 S151 DimensionValidation + S161 v2 Verdict 字段）
export interface DimensionValidationRecord {
  dimension_id: string;
  label: string;
  lift: number | null;
  ci_low: number | null;
  ci_high: number | null;
  n: number;
  n_effective: number | null; // v2: day_paired effective n
  days_robust: number;
  status: VerifierStatus;
  edge_type: EdgeType; // v2: 主 scoping 标签
  tradeable: boolean; // v2
  event_metrics: EventMetrics | null; // v2
  event_status: EventStatus | null; // v2
  weight_multiplier: number;
  source_script: string;
  note: string;
  dsr_method: DsrMethod; // v2
  three_window_compare: ThreeWindowCompare;
  overfit_stats: OverfitStats;
  frozen_commit: string;
  updated_commit: string | null; // v2
  updated_at: string | null; // v2
  data_snapshot_id: string | null; // v2
  layer: LayerType; // R6 三层 reframe
}

// S151 validation_status（中文）→ S161 Verdict.status（英文）映射。
// 纯函数，不可变。后端 REGISTRY 存中文，UI 契约用英文枚举。
// v2: "未validated"→not_validated（非 underpowered——breakout n=43691 是 lift 弱非 n 小）;
//     "待复验"→underpowered（days_robust<60）。
//     子串陷阱修复："未validated".includes("validated")→true，须 exact match 且先判。
export function statusFromChinese(chinese: string): VerifierStatus {
  if (chinese.includes("劣于随机")) return "falsified";
  if (chinese.includes("探索")) return "exploratory";
  // "未validated" exact match FIRST — substring trap: "未validated".includes("validated") → true
  if (chinese === "未validated") return "not_validated";
  if (chinese.includes("待复验")) return "underpowered";
  if (chinese === "validated") return "robust_edge";
  return "exploratory"; // 兜底：未知状态标探索性（不夸大）
}
