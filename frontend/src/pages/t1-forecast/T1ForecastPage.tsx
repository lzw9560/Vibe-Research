// pages/t1-forecast/T1ForecastPage.tsx — S232 T+1 涨停预测 watchlist 看板页。
// 观察池工具非买入信号。5.28x lift 真但 EV -0.87% 负，二次确认累积 60 天验证中。
import { PageHeader } from "@/components/ui/PageHeader";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { WatchlistCard } from "@/components/t1-forecast/WatchlistCard";

export function T1ForecastPage() {
  return (
    <div>
      <PageHeader
        title="T+1 涨停预测 watchlist"
        subtitle="S232 观察池工具 · 非买入信号 · 5.28x lift 真但 EV 负 · 二次确认累积验证中"
      />
      <div className="mb-4">
        <WatchlistCard />
      </div>
      <Disclaimer />
      <NextStepBar pageCtx="t1-forecast" />
    </div>
  );
}
