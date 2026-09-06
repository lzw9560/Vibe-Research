// S165 R1/R5/R6: 维度验证卡——§44 verdict 字段 + 三窗口对比 + overfit 占位 + 诚实标注。
// 匹配 S161 v2 Verdict dataclass（contract-first 双向锁）。
// 数据来源：S151 DIMENSION_LIFT_REGISTRY → dimension-validation.mock.ts（MOCK，待 wire /api/verifier/records）。
// v2: 5-value enum + edge_type 主标签 + event verdict gap-marking (edge_type=event) + PBO distinct states + field source map。
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import type {
  DimensionValidationRecord,
  VerifierStatus,
  EdgeType,
  LayerType,
  WindowStats,
} from "@/lib/verifier-contract";

// R5: status 色码——robust_edge=绿 / underpowered=黄 / falsified=红 / not_validated=灰"弱信号非欠样本" / exploratory=灰
const STATUS_STYLE: Record<
  VerifierStatus,
  { pill: string; label: string }
> = {
  robust_edge: {
    pill: "bg-emerald-500/10 text-emerald-600",
    label: "robust edge（≥2x + DSR>0 + Bonferroni 全过 + days≥60）",
  },
  underpowered: {
    pill: "bg-amber-500/10 text-amber-600",
    label: "待 live 60 天复验",
  },
  falsified: {
    pill: "bg-red-500/10 text-red-600",
    label: "证否（劣于随机）",
  },
  not_validated: {
    pill: "bg-gray-400/10 text-gray-400",
    label: "弱信号非欠样本",
  },
  exploratory: {
    pill: "bg-gray-400/10 text-gray-400",
    label: "探索性",
  },
};

// R6: 三层 reframe（grill #5）— selection 展示终态 / direction deferred / infra built
const LAYER_LABEL: Record<LayerType, string> = {
  selection: "展示终态",
  direction: "deferred 未建",
  infra: "built",
};

// R5: edge_type 主 scoping 标签旁 status
const EDGE_TYPE_LABEL: Record<EdgeType, string> = {
  selection: "selection",
  event: "event",
  population: "population",
};

const HONEST_LABEL = "选股层无 validated 维度, edge 待盘中验证";

// R7: selection-falsified 防外推 note
const SELECTION_FALSIFIED_NOTE =
  "selection falsified; population event edge may exist (see event verdict)";

// R5: gap is §3 event verdict (edge_type=event), NOT a REGISTRY dim
// Card's gap-marking triggers on event verdict injection, not REGISTRY row string match
function isEventVerdict(record: DimensionValidationRecord): boolean {
  return record.edge_type === "event";
}

// R7: selection-falsified 须带防外推 note
function isSelectionFalsified(record: DimensionValidationRecord): boolean {
  return record.edge_type === "selection" && record.status === "falsified";
}

function fmt(v: number | null | undefined, digits = 3, unit = ""): string {
  if (v == null) return "—";
  return `${v.toFixed(digits)}${unit}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v > 1 ? v : v * 100).toFixed(1)}%`;
}

function WindowRow({ label, stats }: { label: string; stats: WindowStats }) {
  return (
    <tr className="text-xs">
      <td className="py-0.5 pr-2 text-muted-foreground">{label}</td>
      <td className="py-0.5 px-2 text-right">{fmt(stats.mean, 4)}</td>
      <td className="py-0.5 px-2 text-right">{fmt(stats.median, 4)}</td>
      <td className="py-0.5 px-2 text-right">{fmtPct(stats.win_rate)}</td>
      <td className="py-0.5 pl-2 text-right">{fmtPct(stats.base_rate)}</td>
    </tr>
  );
}

// R7: PBO distinct states — N/A (single-strategy) for event, 待建 for selection
function pboDisplay(record: DimensionValidationRecord): string {
  const pbo = record.overfit_stats.pbo;
  if (pbo != null) return pbo.toFixed(3);
  // event/single-strategy: PBO structurally N/A (N<2 trials_matrix)
  if (record.edge_type === "event") return "N/A (single-strategy)";
  // selection: not yet wired
  return "待建 (not-yet-wired)";
}

export function DimensionValidationCard({
  record,
}: {
  record: DimensionValidationRecord;
}) {
  const s = STATUS_STYLE[record.status];
  const layerLabel = LAYER_LABEL[record.layer];
  const edgeLabel = EDGE_TYPE_LABEL[record.edge_type];
  const isEvent = isEventVerdict(record);
  const isSelFalsified = isSelectionFalsified(record);

  return (
    <GlassCard className="space-y-3 p-4">
      {/* Header: label + edge_type scoping label + status pill */}
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium">
          {record.label}
          <span className="ml-1 text-xs text-muted-foreground">
            {record.dimension_id}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {/* R5: edge_type 主 scoping 标签旁 status */}
          <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-600">
            {edgeLabel}
          </span>
          <span
            className={cn(
              "rounded px-2 py-0.5 text-xs font-medium",
              s.pill,
            )}
          >
            {s.label}
          </span>
        </div>
      </div>

      {/* R6 三层 reframe + R5 event verdict hypothesis 标注 */}
      <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
        <span className="rounded bg-muted/50 px-1.5 py-0.5">
          {record.layer}层 · {layerLabel}
        </span>
        <span className="rounded bg-muted/50 px-1.5 py-0.5">
          ×{record.weight_multiplier}
        </span>
        {isEvent && (
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-600">
            hypothesis 非 verified
          </span>
        )}
      </div>

      {/* 核心字段：lift / CI / n / n_effective / days_robust / tradeable / dsr_method / source_script */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">lift</span>
          <span>{fmt(record.lift)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">CI</span>
          {/* R6 field source map: ci_low/ci_high → null + "待 v2 verifier 跑出"灰底（不臆造） */}
          <span className="text-muted-foreground">
            {record.ci_low != null && record.ci_high != null
              ? `[${fmt(record.ci_low)}, ${fmt(record.ci_high)}]`
              : "待 v2 verifier 跑出"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">n</span>
          <span>{record.n}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">n_effective</span>
          {/* R6: n_effective → null + "待 v2 (day_paired)"（derived by verifier） */}
          <span className="text-muted-foreground">
            {record.n_effective != null ? record.n_effective : "待 v2 (day_paired)"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">days_robust</span>
          <span>{record.days_robust}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">tradeable</span>
          <span className={record.tradeable ? "text-emerald-600" : "text-red-600"}>
            {record.tradeable ? "yes" : "no"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">dsr_method</span>
          <span className="text-xs">{record.dsr_method}</span>
        </div>
        <div className="col-span-2 flex justify-between">
          <span className="text-muted-foreground">source_script</span>
          <span className="text-xs">{record.source_script}</span>
        </div>
      </div>

      {/* R1 v2: event_metrics — event edge 子结论（edge_type=event 时显示） */}
      {record.event_metrics && (
        <div>
          <div className="mb-1 text-xs text-muted-foreground">
            event metrics（edge_type=event）
          </div>
          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-muted-foreground">mean</span>
              <span>{fmt(record.event_metrics.mean_return, 4)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">net</span>
              <span>{fmt(record.event_metrics.net_mean, 4)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">win rate</span>
              <span>{fmtPct(record.event_metrics.win_rate)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">t-stat</span>
              <span>{fmt(record.event_metrics.t_stat_day_clustered, 2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">n_event</span>
              <span>{record.event_metrics.n_event != null ? record.event_metrics.n_event : "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">base rate</span>
              <span>{fmtPct(record.event_metrics.base_rate)}</span>
            </div>
          </div>
          {record.event_status && (
            <div className="mt-1 text-[10px] text-muted-foreground">
              event_status: {record.event_status}
            </div>
          )}
        </div>
      )}

      {/* R7: selection-falsified 防外推 note */}
      {isSelFalsified && (
        <div className="rounded bg-blue-500/10 px-2 py-1 text-[10px] text-blue-600">
          {SELECTION_FALSIFIED_NOTE}
        </div>
      )}

      {/* S159 R1: 三窗口对比表（前置窗口 sanity）— v2 去 IC/lift */}
      <div>
        <div className="mb-1 text-xs text-muted-foreground">
          三窗口对比（S159 前置窗口 sanity）
        </div>
        <table className="w-full">
          <thead>
            <tr className="text-[10px] text-muted-foreground">
              <th className="pr-2 text-left font-normal">窗口</th>
              <th className="px-2 text-right font-normal">mean</th>
              <th className="px-2 text-right font-normal">中位</th>
              <th className="px-2 text-right font-normal">胜率</th>
              <th className="pl-2 text-right font-normal">base rate</th>
            </tr>
          </thead>
          <tbody>
            <WindowRow label="隔夜 gap" stats={record.three_window_compare.overnight_gap} />
            <WindowRow label="D+1 日内" stats={record.three_window_compare.d1_intraday} />
            <WindowRow label="path" stats={record.three_window_compare.path} />
          </tbody>
        </table>
      </div>

      {/* S161 R2: overfit 统计占位——PBO distinct states + 其余待建灰底 */}
      <div>
        <div className="mb-1 text-xs text-muted-foreground">
          overfit 统计（PBO/CSCV/DSR/Haircut/MinTRL）
        </div>
        <div className="flex flex-wrap gap-1.5">
          {/* PBO: distinct states — N/A (single-strategy) vs 待建 (not-yet-wired) */}
          <div
            className={cn(
              "rounded px-2 py-0.5 text-xs",
              record.overfit_stats.pbo != null
                ? "bg-emerald-500/10 text-emerald-600"
                : "bg-gray-200/50 text-gray-400",
            )}
          >
            PBO: {pboDisplay(record)}
          </div>
          {/* 其余 overfit stats: 待建 */}
          {(["cscv", "dsr", "haircut", "min_trl"] as const).map((key) => {
            const val = record.overfit_stats[key];
            return (
              <div
                key={key}
                className={cn(
                  "rounded px-2 py-0.5 text-xs",
                  val != null
                    ? "bg-emerald-500/10 text-emerald-600"
                    : "bg-gray-200/50 text-gray-400",
                )}
              >
                {key.toUpperCase()}: {val != null ? val.toFixed(3) : "待建"}
              </div>
            );
          })}
        </div>
      </div>

      {/* note */}
      <div className="text-xs text-muted-foreground">{record.note}</div>

      {/* commit 追溯 — R6 field source map: updated_commit/updated_at → null + "待回溯 task 填充"灰底 */}
      <div className="border-t border-border pt-2 text-[10px] text-muted-foreground">
        <div>frozen_commit={record.frozen_commit}</div>
        <div>
          updated_commit={record.updated_commit ?? "待回溯 task 填充"}
        </div>
        <div>
          updated_at={record.updated_at ?? "待回溯 task 填充"}
        </div>
      </div>

      {/* R5 honest_label */}
      <div className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-600">
        ⚠ {HONEST_LABEL}
        <div className="mt-0.5 text-[10px] text-amber-500/70">
          该窗口无 edge ≠ 无 edge（S159 外推禁令）
        </div>
      </div>
    </GlassCard>
  );
}
