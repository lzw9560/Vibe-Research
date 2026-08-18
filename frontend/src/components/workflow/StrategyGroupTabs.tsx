// S066 §3.3 策略组 Tab（S072 去天气：全战法平等展示，无天气推荐★/暴风雨硬约束；
// 暴风雨仓位=0 由 PositionAdvisor §6/§15 兜底，战法 tab 不再按天气过滤）。
import { cn } from "@/lib/utils";
import { useFunnelStrategies } from "@/lib/query/strategy";
import { Skeleton } from "@/components/ui/Skeleton";

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
  weak_turn_strong: "弱转强接力",
  pattern_reversal: "形态反包",
};

interface Props {
  activeStrategy: string | null;
  onSelect: (code: string) => void;
}

export function StrategyGroupTabs({ activeStrategy, onSelect }: Props) {
  const { data: strategies, isLoading } = useFunnelStrategies();

  if (isLoading) {
    return <Skeleton className="h-10 w-full" />;
  }

  const registered = (strategies ?? []).map((s) => s.code).filter(Boolean);
  const codes = registered.length > 0 ? registered : Object.keys(STRATEGY_LABELS);
  const active = activeStrategy ?? codes[0] ?? null;

  return (
    <div className="flex flex-wrap gap-1 rounded-lg bg-muted/15 p-1">
      {codes.map((code) => {
        const cfg = strategies?.find((s) => s.code === code);
        const label = cfg?.name ?? STRATEGY_LABELS[code] ?? code;
        const isActive = active === code;
        // S055 待激活：activation_note 非空 → 置灰不可点 + "待激活"徽标
        const activationNote = cfg?.activation_note;
        const isInactive = !!activationNote;
        return (
          <button
            key={code}
            onClick={() => {
              if (isInactive) return;
              onSelect(code);
            }}
            disabled={isInactive}
            title={activationNote ?? undefined}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              isInactive
                ? "cursor-not-allowed text-muted-foreground opacity-50"
                : isActive
                  ? "bg-primary/15 text-primary shadow-glow"
                  : "text-muted-foreground hover:bg-muted/30 hover:text-foreground",
            )}
          >
            <span>{label}</span>
            {isInactive && (
              <span className="rounded bg-warning/20 px-1 text-[10px] font-medium text-warning">待激活</span>
            )}
          </button>
        );
      })}
      {codes.length === 0 && (
        <span className="px-3 py-1.5 text-sm text-muted-foreground">无注册战法</span>
      )}
    </div>
  );
}
