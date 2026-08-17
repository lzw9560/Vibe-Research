// S063 T24：Layer 4 T+1 预判——14:30 后双场景卡片 + 收盘后校准展示。
// 标注"投影，非最终判定"（CC2）。
import { useIntradayT1Projection } from "@/lib/query";
import { Skeleton } from "@/components/ui/Skeleton";

const WEATHER_COLOR: Record<string, string> = {
  晴天: "text-amber-600 bg-amber-500/10",
  阴天: "text-slate-600 bg-slate-500/10",
  暴风雨: "text-red-600 bg-red-500/10",
  极端反弹: "text-violet-600 bg-violet-500/10",
  未知: "text-muted-foreground bg-muted/10",
};

export function T1ProjectionPanel() {
  const { data, isLoading } = useIntradayT1Projection();

  if (isLoading) {
    return <Skeleton className="h-[140px] w-full" />;
  }

  if (!data || data.status !== "ready") {
    return (
      <div className="rounded-lg bg-muted/10 p-4 text-sm text-muted-foreground">
        {data?.message ?? "T+1 预判 14:30 后可用"}
      </div>
    );
  }

  const scenarios = data.scenarios ?? [];

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        {scenarios.map((s) => (
          <div key={s.name} className="rounded-lg border border-border/40 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold">{s.name}</span>
              <span
                className={`rounded px-2 py-0.5 text-xs ${WEATHER_COLOR[s.projected_t1_weather] ?? WEATHER_COLOR.未知}`}
              >
                {s.projected_t1_weather}
              </span>
            </div>
            <p className="text-2xl font-bold">{s.projected_t1_score.toFixed(1)}</p>
            <p className="mt-1 text-xs text-muted-foreground">{s.assumption}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-700 dark:text-amber-400">
        <span className="font-medium">投影，非最终判定</span>
        {data.as_of ? (
          <span className="text-muted-foreground">—— 当前采样 {data.as_of}</span>
        ) : null}
      </div>
    </div>
  );
}
