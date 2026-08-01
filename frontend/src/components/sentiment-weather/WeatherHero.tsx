import { useMemo } from "react";
import { CloudSun, RefreshCw, Info } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import type { WeatherState } from "@/lib/api";

interface WeatherHeroProps {
  weather: WeatherState | null;
  onRefresh: () => void;
  refreshing: boolean;
}

export function WeatherHero({ weather, onRefresh, refreshing }: WeatherHeroProps) {
  const weatherState = weather?.weather_state ?? "未知";
  const stiScore = weather?.sti_score ?? null;
  const stiPhase = weather?.sti_phase ?? null;
  const confidence = weather?.confidence ?? "中";
  const dataUpdated = weather?.data_updated ?? null;

  const phaseColor = useMemo(() => {
    const map: Record<string, string> = {
      "晴天": "text-success",
      "阴天": "text-warning",
      "暴风雨": "text-danger",
      "极端反弹": "text-purple-400",
    };
    return map[weatherState] || "text-muted-foreground";
  }, [weatherState]);

  return (
    <GlassCard className={`p-5 border bg-blue-500/5 border-blue-500/10`}>
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        {/* Left: Weather State + STI Score */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <CloudSun className="h-5 w-5 text-foreground/80" />
            <div>
              <h3 className="text-sm font-medium text-foreground/80">市场天气</h3>
              <p className={`text-xl font-bold ${phaseColor}`}>{weatherState}</p>
            </div>
          </div>

          <div className="h-8 w-px bg-border hidden sm:block" />

          <div>
            <p className="text-xs text-foreground/60">STI 情绪温度</p>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold tabular-nums text-foreground">
                {stiScore !== null ? stiScore.toFixed(1) : "--"}
              </span>
              <span className="text-sm text-foreground/50">/ 100</span>
            </div>
          </div>
        </div>

        {/* Center: Phase + Confidence */}
        <div className="flex items-center gap-3">
          {stiPhase && (
            <Badge variant="default" className="text-xs">
              {stiPhase}期
            </Badge>
          )}
          <div className="text-xs text-foreground/60">
            置信度: {confidence}
          </div>
        </div>

        {/* Right: Meta + Actions */}
        <div className="flex items-center gap-3">
          {dataUpdated && (
            <div className="text-xs text-foreground/50 hidden md:block">
              更新: {dataUpdated}
            </div>
          )}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="text-foreground/60 hover:text-foreground transition-colors"
            title="刷新"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Compact STI Gauge */}
      {stiScore !== null && (
        <div className="mt-4">
          <div className="h-2 rounded-full bg-foreground/10 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500 transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, stiScore))}%` }}
            />
          </div>
          <div className="flex justify-between mt-1 text-[10px] text-foreground/40">
            <span>冰点</span>
            <span>启动</span>
            <span>分歧</span>
            <span>高潮</span>
          </div>
        </div>
      )}

      {/* Subtle disclaimer */}
      <div className="mt-3 flex items-start gap-1.5 text-[10px] text-foreground/40">
        <Info className="h-3 w-3 mt-0.5 shrink-0" />
        <span>情绪温度仅为历史统计维度之一，不构成任何操作建议。股市有风险，投资需谨慎。</span>
      </div>
    </GlassCard>
  );
}
