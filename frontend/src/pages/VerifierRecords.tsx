// S165 R2: 实验记录页——list RecorderRecord（recorder_id + data_snapshot_id + hash + params + n_trials + verdict + timestamp）。
// v2: 加 not_validated pill + edge_type 标签 + data_snapshot_id 显示。
// S165 wire: 接 GET /api/verifier/records（useVerifierRecords）。后端未就绪/空 → mock fixture fallback + "mock" 徽标。
// 一条 recorder_id 可复现（点 → stub onClick，无真实导航）。
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { useVerifierRecords } from "@/lib/query";
import { recorderRecordMocks } from "@/lib/__fixtures__/dimension-validation.mock";
import type { RecorderRecord, VerifierStatus } from "@/lib/verifier-contract";

const STATUS_PILL: Record<VerifierStatus, string> = {
  robust_edge: "bg-emerald-500/10 text-emerald-600",
  underpowered: "bg-amber-500/10 text-amber-600",
  falsified: "bg-red-500/10 text-red-600",
  not_validated: "bg-gray-400/10 text-gray-400",
  exploratory: "bg-gray-400/10 text-gray-400",
};

function fmtParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params);
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(" · ");
}

function VerifierRecordRow({
  record,
  onClick,
}: {
  record: RecorderRecord;
  onClick: () => void;
}) {
  return (
    <GlassCard className="p-3 space-y-1.5" onClick={onClick}>
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={onClick}
          className="font-mono text-sm text-blue-500 hover:underline"
        >
          {record.recorder_id}
        </button>
        <div className="flex items-center gap-1.5">
          {/* v2: edge_type 主 scoping 标签旁 status */}
          <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-600">
            {record.verdict.edge_type}
          </span>
          <span
            className={cn(
              "rounded px-2 py-0.5 text-xs",
              STATUS_PILL[record.verdict.status],
            )}
          >
            {record.verdict.status}
          </span>
        </div>
      </div>
      <div className="text-xs text-muted-foreground">
        <span className="font-mono">{record.input_snapshot_hash}</span>
        {record.data_snapshot_id && (
          <span className="ml-2">
            snapshot: <span className="font-mono">{record.data_snapshot_id}</span>
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        {fmtParams(record.params)}
      </div>
      <div className="flex items-center gap-4 text-xs">
        <span className="text-muted-foreground">
          n_trials: <span className="text-foreground">{record.n_trials}</span>
        </span>
        <span className="text-muted-foreground">
          lift:{" "}
          <span className="text-foreground">
            {record.verdict.lift != null ? record.verdict.lift.toFixed(3) : "—"}
          </span>
        </span>
        <span className="text-muted-foreground">
          days_robust:{" "}
          <span className="text-foreground">{record.verdict.days_robust}</span>
        </span>
        <span className="text-muted-foreground">
          n: <span className="text-foreground">{record.verdict.n}</span>
        </span>
      </div>
      <div className="text-[10px] text-muted-foreground">
        {record.timestamp}
      </div>
      {record.verdict.note && (
        <div className="text-xs text-muted-foreground">{record.verdict.note}</div>
      )}
    </GlassCard>
  );
}

export function VerifierRecords() {
  const [selected, setSelected] = useState<string | null>(null);
  const { data, isLoading, error } = useVerifierRecords();

  // honest fallback: 后端未就绪/空 → mock fixture + "mock" 徽标（不 break UI）。
  const hasReal = !!data && data.length > 0;
  const records: readonly RecorderRecord[] = hasReal ? data! : recorderRecordMocks;
  const isMock = !hasReal;

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">实验记录（Recorder Records）</h1>
        <div className="flex items-center gap-1.5">
          {isLoading && (
            <span className="text-xs text-muted-foreground">加载中…</span>
          )}
          {error && !isLoading && (
            <span className="text-xs text-red-500">
              后端未就绪，显示 mock
            </span>
          )}
          {isMock && !isLoading && (
            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600">
              MOCK
            </span>
          )}
          {!isMock && (
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-600">
              LIVE
            </span>
          )}
        </div>
      </div>

      {selected && (
        <div className="rounded-lg bg-blue-500/10 p-2 text-xs text-blue-600">
          已选: {selected}（stub，无真实导航——S161 wire 后接重算/查看）
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {records.map((r) => (
          <VerifierRecordRow
            key={r.recorder_id}
            record={r}
            onClick={() => setSelected(r.recorder_id)}
          />
        ))}
      </div>
    </div>
  );
}
