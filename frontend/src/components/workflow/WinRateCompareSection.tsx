// S093 T11：从 PreMarketBriefing 私有函数抽为可复用组件。
// S031 R22：战法胜率对比——useStrategyBacktest 真实回测 + 各因子 L2 passed 合成估算。
// S072 去天气：不再按天气推荐标★（天气无 §44 edge，lift 0.956<1）。

import { useStrategyBacktest } from "@/lib/query/strategy";
import { WinRateComparePanel } from "@/components/ui/WinRateComparePanel";
import type { FactorResult } from "@/lib/api";

interface WinRateCompareSectionProps {
  factors: FactorResult[];
  onPick: (code: string) => void;
}

export function WinRateCompareSection({ factors, onPick }: WinRateCompareSectionProps) {
  const { data: backtest, isLoading } = useStrategyBacktest(60);
  // 取所有因子 L2 战法层 passed（携 best_strategy + confidence_value）
  const l2Passed = factors
    .flatMap((f) => f.layers ?? [])
    .filter((l) => l.layer_id === "LS-2")
    .flatMap((l) => l.passed ?? []);
  if (!factors.length) return null;
  return (
    <div className="mb-6">
      <WinRateComparePanel
        backtest={backtest}
        l2Passed={l2Passed}
        loading={isLoading}
        onPickCandidate={onPick}
      />
    </div>
  );
}
