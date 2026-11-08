import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";

// S243 运维 yield 看板——散户结构性 yield（非选股 alpha）
// 选股因子 alpha 穷尽 definitive 后，practitioner reframe：散户 edge 在 underpricing/行为不在选股

interface RepoInfo {
  symbol?: string;
  rate: number | null;
  high?: number;
  low?: number;
  time?: string;
  quarter_end: boolean;
  month_end: boolean;
  threshold?: number;
  error?: string;
}

interface CBItem {
  code: string;
  name: string;
  subscribe_date?: string;
  list_date?: string;
}

interface YieldSnapshot {
  repo: RepoInfo;
  cb_today: { count: number; items: CBItem[] };
  ipo_today: { count: number; items: unknown[]; note?: string };
}

export function YieldPanel() {
  const [data, setData] = useState<YieldSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const r = await fetch("/api/yield/snapshot");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const json = (await r.json()) as YieldSnapshot;
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "fetch failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const timer = setInterval(load, 60000); // 1min 刷新（GC001 实时）
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (loading) return <Skeleton className="h-40 w-full" />;
  if (error || !data) {
    return (
      <GlassCard className="p-4">
        <div className="text-sm text-muted-foreground">运维 yield 加载失败：{error ?? "无数据"}</div>
      </GlassCard>
    );
  }

  const { repo, cb_today, ipo_today } = data;
  const shouldRemind = (repo.rate ?? 0) >= (repo.threshold ?? 3) || repo.quarter_end || repo.month_end;

  return (
    <GlassCard className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">运维 Yield（结构性 underpricing）</h3>
        <Badge variant="default" className="text-xs">S243</Badge>
      </div>

      {/* GC001 逆回购 */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">逆回购 GC001</span>
          {repo.quarter_end && <Badge className="bg-red-500/15 text-red-600 text-xs">季末/年末</Badge>}
          {repo.month_end && !repo.quarter_end && <Badge className="bg-amber-500/15 text-amber-600 text-xs">月末</Badge>}
          {shouldRemind && <Badge className="bg-green-500/15 text-green-600 text-xs">sweep 时机</Badge>}
        </div>
        {repo.rate != null ? (
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold ${repo.rate >= 3 ? "text-green-600" : "text-foreground"}`}>
              {repo.rate.toFixed(3)}%
            </span>
            <span className="text-xs text-muted-foreground">年化</span>
            {repo.high != null && (
              <span className="text-xs text-muted-foreground">高 {repo.high.toFixed(2)}%</span>
            )}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">{repo.error ?? "GC001 暂不可用"}</div>
        )}
        <div className="text-xs text-muted-foreground">14:50 前证券账户逆回购（底仓闲置资金 sweep，零风险）</div>
      </div>

      {/* CB 信用申购 */}
      <div className="space-y-1 border-t pt-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">CB 信用申购（今日）</span>
          <Badge variant="default" className="text-xs">{cb_today.count} 只</Badge>
        </div>
        {cb_today.count > 0 ? (
          <div className="space-y-0.5">
            {cb_today.items.slice(0, 3).map((cb) => (
              <div key={cb.code} className="text-xs">
                {cb.code} {cb.name}
              </div>
            ))}
            {cb_today.count > 3 && <div className="text-xs text-muted-foreground">...等 {cb_today.count - 3} 只</div>}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">今日无 CB 申购</div>
        )}
        <div className="text-xs text-muted-foreground">9:30-15:00 信用申购（零成本无市值要求）</div>
      </div>

      {/* 打新（Phase 3 deferred） */}
      <div className="space-y-1 border-t pt-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">打新筛选</span>
          <Badge variant="default" className="text-xs text-muted-foreground">Phase 3 待接线</Badge>
        </div>
        <div className="text-xs text-muted-foreground">{ipo_today.note ?? "IPO 日历数据源待调研"}</div>
      </div>
    </GlassCard>
  );
}
