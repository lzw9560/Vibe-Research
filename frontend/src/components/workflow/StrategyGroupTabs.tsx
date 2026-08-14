// S066 §3.3 策略组 Tab——按天气硬开关激活的策略组分 tab。
// spec §11.2：策略分组：按天气激活的策略组分 tab，每 tab 显示该策略的候选列表。
import { Cloud, CloudRain, Sun, Zap, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWeatherStrategyMap, useFunnelStrategies } from "@/lib/query/strategy";
import { Skeleton } from "@/components/ui/Skeleton";

const WEATHER_ICON: Record<string, typeof Sun> = {
  晴天: Sun,
  阴天: Cloud,
  暴风雨: CloudRain,
  极端反弹: Zap,
  未知: HelpCircle,
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
  storm_reversal: "暴风雨逆势",
};

interface Props {
  weatherState: string | null | undefined;
  activeStrategy: string | null;
  onSelect: (code: string) => void;
}

/** S066 §3.3 天气硬开关策略组 Tab。
 * 按当前天气的主跑策略 + fallback 分 tab，点击切换激活策略。
 */
export function StrategyGroupTabs({ weatherState, activeStrategy, onSelect }: Props) {
  const { data: weatherMap, isLoading: mapLoading } = useWeatherStrategyMap();
  const { data: strategies } = useFunnelStrategies();

  if (mapLoading) {
    return <Skeleton className="h-10 w-full" />;
  }

  const weather = weatherState ?? "未知";
  const primaryCodes = weatherMap?.weather_strategy_map[weather] ?? ["first_plate", "consecutive_relay"];
  const fallbackCodes = weatherMap?.fallback_strategies[weather] ?? [];

  const allCodes = [...primaryCodes, ...fallbackCodes.filter((c) => !primaryCodes.includes(c))];
  const active = activeStrategy ?? primaryCodes[0] ?? null;

  return (
    <div className="flex flex-wrap gap-1 rounded-lg bg-muted/15 p-1">
      {allCodes.map((code) => {
        const cfg = strategies?.find((s) => s.code === code);
        const label = cfg?.name ?? STRATEGY_LABELS[code] ?? code;
        const isActive = active === code;
        const isPrimary = primaryCodes.includes(code);
        const WeatherIcon = WEATHER_ICON[weather] ?? HelpCircle;
        return (
          <button
            key={code}
            onClick={() => onSelect(code)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-primary/15 text-primary shadow-glow"
                : "text-muted-foreground hover:bg-muted/30 hover:text-foreground",
            )}
          >
            {isActive && <WeatherIcon className="h-3.5 w-3.5" />}
            <span>{label}</span>
            {!isPrimary && (
              <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">备</span>
            )}
          </button>
        );
      })}
      {allCodes.length === 0 && (
        <span className="px-3 py-1.5 text-sm text-muted-foreground">当前天气无激活策略</span>
      )}
    </div>
  );
}
