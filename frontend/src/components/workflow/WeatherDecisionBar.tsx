// S063 T19：盘前简报顶部天气决策条（WeatherDecisionBar）。
// 全宽非卡片，纵向流第一块：天气图标+名+推荐/不推荐 chips+熔断三灯+天气色背景。S072 STI 去噪（score/phase 移出选股页留复盘）。
// spec §5.2：背景色微染天气色（极淡的 amber/slate/red/violet tint）。
import { Cloud, CloudRain, Sun, Zap, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import type { SentimentContext, SentimentWeatherState } from "@/lib/api";

const WEATHER_META: Record<
  SentimentWeatherState,
  { icon: typeof Sun; tint: string; label: string; badge: "success" | "warning" | "danger" | "info" }
> = {
  晴天: { icon: Sun, tint: "bg-amber-500/5 border-amber-500/20", label: "晴天", badge: "success" },
  阴天: { icon: Cloud, tint: "bg-slate-500/5 border-slate-500/20", label: "阴天", badge: "info" },
  暴风雨: { icon: CloudRain, tint: "bg-red-500/5 border-red-500/20", label: "暴风雨", badge: "danger" },
  极端反弹: { icon: Zap, tint: "bg-violet-500/5 border-violet-500/20", label: "极端反弹", badge: "info" },
  未知: { icon: HelpCircle, tint: "bg-slate-500/5 border-slate-500/10", label: "未取得", badge: "warning" },
};

const STRATEGY_LABELS: Record<string, string> = {
  first_plate: "首板挖掘",
  consecutive_relay: "连板接力",
  break_reseal: "炸板回封",
  low_absorption: "低吸龙头",
  reverse_package: "反包战法",
  n_shape_counterattack: "N字反击",
  platform_breakout: "平台突破",
  end_of_day_sneak: "尾盘偷袭",
  dragon_head: "龙头战法",
};

interface Props {
  ctx: SentimentContext | null | undefined;
}

export function WeatherDecisionBar({ ctx }: Props) {
  const weather = ctx?.weather_state ?? "未知";
  const meta = WEATHER_META[weather] ?? WEATHER_META.未知;
  const Icon = meta.icon;
  const fuseRules = ctx?.fuse_state?.rules ?? [];
  const allowed = ctx?.allowed_styles ?? [];
  const forbidden = ctx?.forbidden_styles ?? [];

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-4 rounded-lg border p-4",
        meta.tint,
      )}
    >
      {/* 左：天气图标 + 名（S072 STI 去噪：选股页无 score/phase，留 SentimentWeather 复盘） */}
      <div className="flex items-center gap-3">
        <Icon className="h-8 w-8 text-foreground/80" />
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold">{meta.label}</span>
            {/* S072 STI 去噪：score/phase 移出选股页（无 §44 edge，留 SentimentWeather 复盘） */}
          </div>
          <span className="text-xs text-muted-foreground">
            {ctx?.source_date ? `昨日情绪 · T-1(${ctx.source_date})` : "情绪数据未取得"}
            {ctx?.change_from_yesterday != null && (
              <span className={cn("ml-2", ctx.change_from_yesterday >= 0 ? "text-success" : "text-destructive")}>
                {ctx.change_from_yesterday >= 0 ? "+" : ""}{ctx.change_from_yesterday.toFixed(1)}
              </span>
            )}
          </span>
        </div>
      </div>

      {/* 中：推荐/不推荐战法 chips（Q7 软标注；暴风雨 forbidden=硬约束 storm_reversal only） */}
      <div className="flex flex-1 flex-wrap items-center gap-1.5">
        {allowed.length === 0 && forbidden.length === 0 ? (
          <span className="text-xs text-muted-foreground">战法推荐未取得（全可用，Q7 软标注）</span>
        ) : (
          <>
            {allowed.map((code) => (
              <Badge key={code} variant="primary" className="text-[10px]">
                {STRATEGY_LABELS[code] ?? code}
              </Badge>
            ))}
            {forbidden.map((code) => (
              <Badge
                key={code}
                variant="default"
                className="text-[10px] line-through opacity-50"
              >
                {STRATEGY_LABELS[code] ?? code}
              </Badge>
            ))}
          </>
        )}
      </div>

      {/* 右：熔断三灯 */}
      <div className="flex items-center gap-2">
        {fuseRules.length === 0 ? (
          <span className="text-xs text-muted-foreground">熔断状态未取得</span>
        ) : (
          fuseRules.map((rule) => {
            const triggered = rule.is_triggered;
            return (
              <div
                key={rule.id}
                className="flex flex-col items-center gap-0.5"
                title={`${rule.name}：${rule.current_state}`}
              >
                <span
                  className={cn(
                    "h-2.5 w-2.5 rounded-full",
                    triggered
                      ? "bg-red-500 animate-pulse"
                      : "bg-emerald-500/70",
                  )}
                />
                <span className="text-[9px] text-muted-foreground">
                  {rule.name.slice(0, 2)}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
