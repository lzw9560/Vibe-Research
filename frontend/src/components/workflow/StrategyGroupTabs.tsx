// S066 §3.3 策略组 Tab——天气软标注(Q7)推荐战法分 tab。
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

/** S066 §3.3 天气软标注策略组 Tab（Q7：非暴风雨全可用，推荐★徽标；暴风雨硬约束只 storm_reversal）。
 * 按当前天气的主跑策略 + fallback 分 tab，点击切换激活策略。
 */
export function StrategyGroupTabs({ weatherState, activeStrategy, onSelect }: Props) {
  const { data: weatherMap, isLoading: mapLoading } = useWeatherStrategyMap();
  const { data: strategies } = useFunnelStrategies();

  if (mapLoading) {
    return <Skeleton className="h-10 w-full" />;
  }

  const weather = weatherState ?? "未知";

  // Bug D 修复：weather_strategy_map 是推荐集合（软标注），不是可用列表。
  // 可用战法取 useFunnelStrategies 全量注册表；暴风雨硬约束只 storm_reversal
  // （对齐后端 get_strategies_for_weather）。推荐集合降级为"荐"徽标标注。
  const availableCodes = (() => {
    const registered = (strategies ?? []).map((s) => s.code).filter(Boolean);
    if (weather === "暴风雨") {
      // 暴风雨硬约束：只 storm_reversal（后端 get_strategies_for_weather 同款逻辑）
      return ["storm_reversal"];
    }
    // 其他天气：所有已注册战法都可用（不强过滤）
    return registered.length > 0
      ? registered
      : // strategies 端点未就绪时回退到本地全量标签（避免空白 tab 区）
        Object.keys(STRATEGY_LABELS);
  })();

  // 推荐集合（软标注，仅用于"荐"徽标）
  const recommendedCodes = weatherMap?.weather_strategy_map[weather] ?? [];
  const fallbackCodes = weatherMap?.fallback_strategies[weather] ?? [];

  const active = activeStrategy ?? availableCodes[0] ?? null;

  return (
    <div className="flex flex-wrap gap-1 rounded-lg bg-muted/15 p-1">
      {availableCodes.map((code) => {
        const cfg = strategies?.find((s) => s.code === code);
        const label = cfg?.name ?? STRATEGY_LABELS[code] ?? code;
        const isActive = active === code;
        const isRecommended = recommendedCodes.includes(code);
        const isFallback = fallbackCodes.includes(code);
        // S055 待激活：activation_note 非空 → 置灰不可点 + "待激活"徽标
        const activationNote = cfg?.activation_note;
        const isInactive = !!activationNote;
        const WeatherIcon = WEATHER_ICON[weather] ?? HelpCircle;
        return (
          <button
            key={code}
            onClick={() => {
              if (isInactive) return;  // 置灰 tab 不触发 onSelect
              onSelect(code);
            }}
            disabled={isInactive}
            title={activationNote ?? undefined}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              isInactive
                ? "opacity-50 cursor-not-allowed text-muted-foreground"
                : isActive
                  ? "bg-primary/15 text-primary shadow-glow"
                  : "text-muted-foreground hover:bg-muted/30 hover:text-foreground",
            )}
          >
            {isActive && !isInactive && <WeatherIcon className="h-3.5 w-3.5" />}
            <span>{label}</span>
            {isInactive && (
              <span className="rounded bg-warning/20 px-1 text-[10px] font-medium text-warning">待激活</span>
            )}
            {isRecommended && !isInactive && (
              <span className="rounded bg-primary/20 px-1 text-[10px] font-medium text-primary">荐</span>
            )}
            {isFallback && !isRecommended && !isInactive && (
              <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">备</span>
            )}
          </button>
        );
      })}
      {availableCodes.length === 0 && (
        <span className="px-3 py-1.5 text-sm text-muted-foreground">当前天气无激活策略</span>
      )}
    </div>
  );
}
