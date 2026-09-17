// S204 T9: 多日跟踪只读看板——活跃 track 列表 + 指标快照 Drawer。
import { useState } from "react";
import { useTrackingPool, useTrackingSnapshots } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";

const STATUS_VARIANT: Record<string, "success" | "default" | "danger"> = {
  tracking: "default",
  admit: "success",
  promoted: "success",
  decayed: "danger",
};

export function TrackingPanel() {
  const { data, isLoading, error } = useTrackingPool("tracking");
  const [selected, setSelected] = useState<string | null>(null);

  if (isLoading) return <Skeleton className="h-40" />;
  if (error)
    return (
      <GlassCard className="p-4">
        多日跟踪加载失败：{error instanceof Error ? error.message : "未知错误"}
      </GlassCard>
    );
  if (!data || data.count === 0)
    return (
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-foreground mb-2">活跃跟踪池</h3>
        <p className="text-sm text-muted-foreground">
          当前无活跃跟踪记录（current_status=tracking）。多日跟踪架构已通电但
          escalation 需 ≥3 天 aging 积累，数据空是诚实状态非 bug。
        </p>
      </GlassCard>
    );

  return (
    <div className="space-y-4">
      <GlassCard className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-foreground">活跃跟踪池</h3>
          <Badge variant="default">{data.count} 条</Badge>
        </div>
        <div className="space-y-2">
          {data.tracks.map((t) => (
            <button
              key={t.code}
              onClick={() => setSelected(t.code === selected ? null : t.code)}
              className="w-full text-left border border-border rounded-lg p-3 hover:border-primary/50 transition"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-foreground">{t.code}</span>
                <Badge variant={STATUS_VARIANT[t.current_status] ?? "default"}>
                  {t.current_status} · {t.tracking_age_days}天
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                {t.first_admit_date} 入场 · {t.admit_signal || "无信号"}
              </div>
            </button>
          ))}
        </div>
      </GlassCard>

      {selected && <SnapshotList code={selected} />}
    </div>
  );
}

function SnapshotList({ code }: { code: string }) {
  const { data, isLoading, error } = useTrackingSnapshots(code);
  if (isLoading) return <Skeleton className="h-32" />;
  if (error)
    return (
      <GlassCard className="p-4">
        快照加载失败：{error instanceof Error ? error.message : "未知"}
      </GlassCard>
    );
  if (!data || data.count === 0)
    return (
      <GlassCard className="p-4">
        <h3 className="text-sm font-medium text-foreground mb-2">{code} 指标快照</h3>
        <p className="text-sm text-muted-foreground">无快照记录。</p>
      </GlassCard>
    );
  return (
    <GlassCard className="p-5">
      <h3 className="text-sm font-medium text-foreground mb-3">
        {code} 指标快照（{data.count}）
      </h3>
      <div className="space-y-2 max-h-96 overflow-auto">
        {data.snapshots.map((s) => (
          <div key={s.trade_date} className="border border-border rounded p-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-mono text-foreground">{s.trade_date}</span>
              <Badge variant="default">{s.source}</Badge>
            </div>
            <pre className="text-xs text-muted-foreground mt-1 overflow-auto">
              {JSON.stringify(s.indicators, null, 2).slice(0, 400)}
            </pre>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}
