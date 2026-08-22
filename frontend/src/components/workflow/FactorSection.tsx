// S093 T11：从 PreMarketBriefing 私有函数抽为可复用组件。
// S031 R14/R19：单因子多层漏斗（L1 打分 / L2 战法 / L3 仓位）——L2 挂战法多选反筛。

import { useState } from "react";
import { TrendingUp } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { StrategyFilter } from "@/components/ui/StrategyFilter";
import type { FactorResult } from "@/lib/api";
import type { FunnelLayer } from "@/lib/candidates";

interface FactorSectionProps {
  factor: FactorResult;
  onPick: (code: string) => void;
}

export function FactorSection({ factor, onPick }: FactorSectionProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const layers = factor.layers ?? [];
  const l2 = layers.find((l) => l.layer_id === "LS-2");
  // L2 passed 的 best_strategy 去重 → 战法 chips（非空）
  const strategies = Array.from(
    new Set((l2?.passed ?? []).map((c) => c.best_strategy).filter((s): s is string => !!s)),
  );

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          <span className="font-medium">{factor.factor_name}</span>
        </div>
        <span className="text-xs text-muted-foreground">{factor.data_date}</span>
      </div>

      {layers.length > 0 ? (
        <div className="mt-3 space-y-2">
          {layers.map((l) => {
            // L2 战法层：StrategyFilter 多选 + 即时反筛 passed（纯前端，不请求后端）
            if (l.layer_id === "LS-2" && strategies.length > 0) {
              const all = l.passed ?? [];
              const filteredPassed = selected.size > 0
                ? all.filter((c) => c.best_strategy && selected.has(c.best_strategy))
                : all;
              const l2Display: FunnelLayer = { ...l, passed: filteredPassed, output_count: filteredPassed.length };
              return (
                <div key={l.layer_id}>
                  <StrategyFilter strategies={strategies} selected={selected} onChange={setSelected} className="mb-2" />
                  <FunnelLayerCard layer={l2Display} variant="info" onPick={onPick} date={factor.data_date} />
                </div>
              );
            }
            return <FunnelLayerCard key={l.layer_id} layer={l} variant="info" onPick={onPick} date={factor.data_date} />;
          })}
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">无漏斗层数据</p>
      )}
    </GlassCard>
  );
}
