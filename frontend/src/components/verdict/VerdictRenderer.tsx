// S179 P0.6 R0.6: per-type verdict 渲染分发（grill #15）
// F4: long_value 复用 S171ValueVerdict.tsx（非新建 LongValueVerdictCard，避免重复）
// F7: 数据源 = useVerifierRecords（GET /api/verifier/records, S165 已有 hook）
// verdict schema 异构（S168 selection / S169 event / S171 long_value 结构不同）
// → per-type 独立分发，不强拟合异构 schema 到同一组件
import type { ReactNode } from "react";
import { useVerifierRecords } from "@/lib/query";
import { DimensionValidationCard } from "@/components/DimensionValidationCard";
import { S171ValueVerdict } from "@/pages/S171ValueVerdict";
import { GlassCard } from "@/components/ui/GlassCard";
import type {
  RecorderRecord,
  DimensionValidationRecord,
  ThreeWindowCompare,
  OverfitStats,
  LayerType,
} from "@/lib/verifier-contract";

// ── Verdict type discrimination ──────────────────────────────────────────────
// S171 long_value: params.experiment_id === "S171"（S171ValueVerdict assembleBundle 以此过滤）
//   ⚠ 必须先查 experiment_id：S171 对冲版 edge_type=event，但属 long_value 非 S169 event
// S169 event: verdict.edge_type === "event"（gap/PEAD event edge，非 S171）
// S168 selection: verdict.edge_type === "selection"（12 harness selection verdict）
// population 或未分类 → unknown
type VerdictType = "selection" | "event" | "long_value" | "unknown";

const TYPE_LABEL: Record<VerdictType, string> = {
  selection: "短线选股（S168 selection）",
  event: "中线事件（S169 event）",
  long_value: "长线价值（S171 long_value）",
  unknown: "未分类 verdict",
};

function getVerdictType(record: RecorderRecord): VerdictType {
  const params = record.params as Record<string, unknown>;
  if (params?.experiment_id === "S171") return "long_value";
  const et = record.verdict.edge_type;
  if (et === "event") return "event";
  if (et === "selection") return "selection";
  return "unknown";
}

// ── Mapper: RecorderRecord → DimensionValidationRecord ────────────────────────
// DimensionValidationCard 接 DimensionValidationRecord，useVerifierRecords 返 RecorderRecord[]。
// 重叠字段从 verdict 取，额外字段（dimension_id / label / weight_multiplier /
// source_script / three_window_compare / layer）从 params 取，缺失给安全 fallback（不臆造）。
const EMPTY_WINDOW: ThreeWindowCompare = {
  overnight_gap: { mean: null, median: null, win_rate: null, base_rate: null },
  d1_intraday: { mean: null, median: null, win_rate: null, base_rate: null },
  path: { mean: null, median: null, win_rate: null, base_rate: null },
};

function toDimensionRecord(record: RecorderRecord): DimensionValidationRecord {
  const v = record.verdict;
  const p = record.params as Record<string, unknown>;
  const overfit: OverfitStats = {
    pbo: v.pbo,
    cscv: null, // Verdict 无 cscv 字段，CSCV 待 backtest-overfit wire
    dsr: v.dsr,
    haircut: v.haircut,
    min_trl: v.min_trl,
  };
  return {
    dimension_id: (p.dimension_id as string) ?? record.recorder_id,
    label:
      (p.label as string) ??
      (p.dimension_id as string) ??
      record.recorder_id,
    lift: v.lift,
    ci_low: v.ci_low,
    ci_high: v.ci_high,
    n: v.n,
    n_effective: v.n_effective,
    days_robust: v.days_robust,
    status: v.status,
    edge_type: v.edge_type,
    tradeable: v.tradeable,
    event_metrics: v.event_metrics,
    event_status: v.event_status,
    weight_multiplier:
      typeof p.weight_multiplier === "number" ? p.weight_multiplier : 1.0,
    source_script: (p.source_script as string) ?? "—",
    note: v.note,
    dsr_method: v.dsr_method,
    three_window_compare:
      (p.three_window_compare as ThreeWindowCompare) ?? EMPTY_WINDOW,
    overfit_stats: overfit,
    frozen_commit: v.frozen_commit,
    updated_commit: v.updated_commit,
    updated_at: v.updated_at,
    data_snapshot_id: v.data_snapshot_id ?? record.data_snapshot_id,
    layer: (p.layer as LayerType) ?? "selection",
  };
}

// ── VerdictRenderer（容器组件）─────────────────────────────────────────────────

interface VerdictRendererProps {
  /** 限定渲染某一 type（/multiline 三列各传 filterType；不传 = 全部 4 type） */
  filterType?: VerdictType;
}

export function VerdictRenderer({ filterType }: VerdictRendererProps) {
  const { data, isLoading, error } = useVerifierRecords();
  const records: readonly RecorderRecord[] = data ?? [];

  // 按类型分组（不可变：每次 push 到新数组）
  const grouped: Record<VerdictType, RecorderRecord[]> = {
    selection: [],
    event: [],
    long_value: [],
    unknown: [],
  };
  for (const r of records) {
    grouped[getVerdictType(r)].push(r);
  }

  const types: readonly VerdictType[] = filterType
    ? [filterType]
    : ["selection", "event", "long_value", "unknown"];

  return (
    <div className="space-y-4">
      {types.map((t) => (
        <VerdictTypeSection
          key={t}
          type={t}
          records={grouped[t]}
          isLoading={isLoading}
          error={error}
        />
      ))}
    </div>
  );
}

// ── per-type section ──────────────────────────────────────────────────────────

function VerdictTypeSection({
  type,
  records,
  isLoading,
  error,
}: {
  type: VerdictType;
  records: readonly RecorderRecord[];
  isLoading: boolean;
  error: Error | null;
}) {
  // unknown 无记录 → 不渲染整段（避免空 header）
  if (type === "unknown" && records.length === 0) return null;

  // F4: long_value 复用 S171ValueVerdict（非新建 LongValueVerdictCard）
  // S171ValueVerdict 自取 useVerifierRecords（同 queryKey 自动去重）+ 自带 mock/LIVE 徽标
  if (type === "long_value") {
    return (
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-muted-foreground">
          {TYPE_LABEL[type]}
        </h3>
        <S171ValueVerdict />
      </section>
    );
  }

  // selection / event / unknown：统一 loading → error → content 流
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground">
        {TYPE_LABEL[type]}
      </h3>
      {isLoading && records.length === 0 && (
        <p className="text-xs text-muted-foreground">加载 verdict 中…</p>
      )}
      {!isLoading && error && records.length === 0 && (
        <GlassCard className="p-3">
          <p className="text-xs text-red-400">
            后端未就绪（/api/verifier/records），{TYPE_LABEL[type]} 暂无数据
          </p>
        </GlassCard>
      )}
      {!isLoading && !error && renderTypeContent(type, records)}
    </section>
  );
}

// 穷举 switch（4 case 全覆盖，tsc 无 fallthrough 警告）
function renderTypeContent(
  type: VerdictType,
  records: readonly RecorderRecord[],
): ReactNode {
  switch (type) {
    case "selection":
      return <SelectionContent records={records} />;
    case "event":
      return <EventContent records={records} />;
    case "unknown":
      return <UnknownContent records={records} />;
    case "long_value":
      // long_value 在 VerdictTypeSection 中已单独 delegate 到 S171ValueVerdict
      return null;
  }
}

// ── selection: S168 12 harness → DimensionValidationCard ──────────────────────

function SelectionContent({ records }: { records: readonly RecorderRecord[] }) {
  if (records.length === 0) {
    return (
      <GlassCard className="p-3">
        <p className="text-xs text-muted-foreground">
          无 selection verdict——S168 12 harness 全 falsified/exploratory/underpowered，
          selection 层无 validated edge（edge 待盘中验证）
        </p>
      </GlassCard>
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {records.map((r) => (
        <DimensionValidationCard
          key={r.recorder_id}
          record={toDimensionRecord(r)}
        />
      ))}
    </div>
  );
}

// ── event: S169 PEAD → 待 S169 组件（honest 占位，不臆造渲染）──────────────────

function EventContent({ records }: { records: readonly RecorderRecord[] }) {
  if (records.length === 0) {
    return (
      <GlassCard className="p-3">
        <p className="text-xs text-muted-foreground">
          无 event verdict——S169 PEAD gap robust_edge（60d t=4.12）待 60 天复验中
        </p>
      </GlassCard>
    );
  }
  // S169 EventVerdictCard 组件待建——当前诚实占位，不臆造 schema 渲染
  return (
    <GlassCard className="p-3 border-l-2 border-amber-500/40">
      <p className="text-xs font-medium text-amber-400">
        S169 event verdict 组件待建
      </p>
      <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
        已有 {records.length} 条 event verdict 记录（edge_type=event）。
        S169 EventVerdictCard 尚未实现，当前按 recorder_id 占位：
      </p>
      <ul className="mt-2 space-y-0.5">
        {records.map((r) => {
          const em = r.verdict.event_metrics;
          return (
            <li
              key={r.recorder_id}
              className="text-xs text-muted-foreground font-mono"
            >
              {r.recorder_id} · status={r.verdict.status}
              {em && ` · net_mean=${em.net_mean?.toFixed(4) ?? "—"}`}
              {r.verdict.event_status && ` · ${r.verdict.event_status}`}
            </li>
          );
        })}
      </ul>
    </GlassCard>
  );
}

// ── unknown: population 或未分类 → fallback ──────────────────────────────────

function UnknownContent({ records }: { records: readonly RecorderRecord[] }) {
  if (records.length === 0) return null;
  return (
    <GlassCard className="p-3 border-l-2 border-gray-500/40">
      <p className="text-xs font-medium text-gray-400">
        未分类 verdict（edge_type=population 或 experiment_id 未知）
      </p>
      <ul className="mt-2 space-y-0.5">
        {records.map((r) => (
          <li
            key={r.recorder_id}
            className="text-xs text-muted-foreground font-mono"
          >
            {r.recorder_id} · edge_type={r.verdict.edge_type} · status=
            {r.verdict.status}
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}
