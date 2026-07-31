// 漏斗各层卡片：输入/输出/被过滤原因（S002 F2，AC1 每层可检视）。
import type { FunnelLayer } from "@/lib/candidates";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";

export function FunnelLayers({ layers }: { layers: FunnelLayer[] }) {
  if (!layers.length) return null;
  return (
    <div className="space-y-3">
      <SectionHeader title="漏斗各层" subtitle="每层输入/输出与过滤原因" />
      {layers.map((l) => (
        <GlassCard key={l.layer_id} className="p-4">
          <div className="flex items-center justify-between">
            <div className="font-medium">
              <span className="text-muted-foreground mr-2">{l.layer_id}</span>
              {l.name}
            </div>
            <div className="text-sm text-muted-foreground">
              输入 <span className="text-foreground">{l.input_count}</span> → 输出{" "}
              <span className="text-foreground">{l.output_count}</span>
            </div>
          </div>
          {l.output_count === 0 && (
            <div className="mt-2 text-sm text-warning">该层无符合标的，下游无输入</div>
          )}
          {l.filtered_out.length > 0 && (
            <div className="mt-3 grid gap-1 text-sm">
              <div className="text-muted-foreground">被过滤（{l.filtered_out.length}）：</div>
              {l.filtered_out.slice(0, 20).map((f) => (
                <div key={f.code} className="flex justify-between">
                  <span>{f.name ? `${f.name} ${f.code}` : f.code}</span>
                  <span className="text-muted-foreground">{f.reason}</span>
                </div>
              ))}
              {l.filtered_out.length > 20 && (
                <div className="text-muted-foreground">…共 {l.filtered_out.length} 条</div>
              )}
            </div>
          )}
        </GlassCard>
      ))}
    </div>
  );
}
