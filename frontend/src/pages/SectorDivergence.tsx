import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Loader2 } from "lucide-react";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { api } from "@/lib/api";

interface SectorData {
  divergence_score: number;
  rotation_speed: number;
  interpretation: string;
  hot_sectors: string[];
  cold_sectors: string[];
  sectors: Array<{ name: string; change_pct: number; volume_ratio: number }>;
}

export function SectorDivergence() {
  const [data, setData] = useState<SectorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .sectorDivergence()
      .then((res: any) => {
        const d = res?.data ?? res;
        setData(d ?? null);
      })
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader title="板块分化" subtitle="Sector Divergence" />
        <GlassCard className="p-4 text-sm text-muted-foreground">
          数据未取得：{error}
        </GlassCard>
        <Disclaimer />
      </div>
    );
  }

  const score = data?.divergence_score ?? 0;
  const rotation = data?.rotation_speed ?? 0;

  return (
    <div>
      <PageHeader title="板块分化" subtitle="Sector Divergence" />

      <div className="grid gap-4">
        <GlassCard className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">分化度</h3>
            <span className="font-mono text-lg font-bold">{score.toFixed(1)}</span>
          </div>
          <div className="h-3 rounded-full bg-muted/20">
            <div
              className="h-3 rounded-full bg-primary transition-all"
              style={{ width: `${Math.min(score, 100)}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {data?.interpretation ?? ""}
          </p>
        </GlassCard>

        <GlassCard className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">轮动速度</h3>
            <span className="font-mono text-lg font-bold">{rotation.toFixed(1)}</span>
          </div>
          <div className="h-3 rounded-full bg-muted/20">
            <div
              className="h-3 rounded-full bg-blue-500 transition-all"
              style={{ width: `${Math.min(rotation, 100)}%` }}
            />
          </div>
        </GlassCard>

        {data?.sectors && data.sectors.length > 0 && (
          <GlassCard className="p-4">
            <h3 className="mb-3 text-sm font-semibold">板块涨跌</h3>
            <div className="space-y-2">
              {data.sectors.map((s) => (
                <div key={s.name} className="flex items-center gap-3">
                  <span className="w-20 text-sm">{s.name}</span>
                  <div className="flex-1 h-2 rounded-full bg-muted/20">
                    <div
                      className={`h-2 rounded-full transition-all ${
                        s.change_pct >= 0 ? "bg-green-500" : "bg-red-500"
                      }`}
                      style={{ width: `${Math.min(Math.abs(s.change_pct), 5) * 20}%` }}
                    />
                  </div>
                  <span className="w-12 text-right font-mono text-sm">
                    {s.change_pct >= 0 ? "+" : ""}
                    {s.change_pct.toFixed(2)}%
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>
        )}

        {(data?.hot_sectors?.length || data?.cold_sectors?.length) ? (
          <div className="grid grid-cols-2 gap-4">
            {data.hot_sectors.length > 0 && (
              <GlassCard className="p-4">
                <h3 className="mb-2 text-sm font-semibold text-green-500">热门板块</h3>
                <div className="flex flex-wrap gap-1">
                  {data.hot_sectors.map((s) => (
                    <span key={s} className="rounded bg-green-500/10 px-2 py-0.5 text-xs">
                      {s}
                    </span>
                  ))}
                </div>
              </GlassCard>
            )}
            {data.cold_sectors.length > 0 && (
              <GlassCard className="p-4">
                <h3 className="mb-2 text-sm font-semibold text-red-500">冷门板块</h3>
                <div className="flex flex-wrap gap-1">
                  {data.cold_sectors.map((s) => (
                    <span key={s} className="rounded bg-red-500/10 px-2 py-0.5 text-xs">
                      {s}
                    </span>
                  ))}
                </div>
              </GlassCard>
            )}
          </div>
        ) : null}
      </div>

      <Disclaimer />
    </div>
  );
}

export default SectorDivergence;
