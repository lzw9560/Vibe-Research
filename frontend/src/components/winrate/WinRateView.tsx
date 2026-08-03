// S025-B5 胜率视图主体：FilterBar 窗口滑块（7/30/90）+ 四区编排 + 挂 RecordsForm。
// 四区：概览(StatsMetrics)/趋势(TrendsChart)/下钻(BreakdownTable)/建议(AdjustmentsCard)。
// 下钻维度（板块/战法）+ 值输入由本组件持有，传给 BreakdownTable。
import { useState } from "react";
import { useDebounce } from "@/hooks/useDebounce";
import { FilterBar } from "@/components/ui/FilterBar";
import { StatsMetrics } from "./StatsMetrics";
import { TrendsChart } from "./TrendsChart";
import { BreakdownTable } from "./BreakdownTable";
import { AdjustmentsCard } from "./AdjustmentsCard";
import { RecordsForm } from "./RecordsForm";

type WindowSize = 7 | 30 | 90;
type Dimension = "sector" | "strategy";

interface WinRateViewProps {
  defaultWindow?: WindowSize;
}

const WINDOWS: { key: string; label: string; value: WindowSize }[] = [
  { key: "7", label: "7天", value: 7 },
  { key: "30", label: "30天", value: 30 },
  { key: "90", label: "90天", value: 90 },
];

const DIMENSIONS: { key: string; label: string; value: Dimension }[] = [
  { key: "sector", label: "按板块", value: "sector" },
  { key: "strategy", label: "按战法", value: "strategy" },
];

export function WinRateView({ defaultWindow = 30 }: WinRateViewProps) {
  const [windowSize, setWindowSize] = useState<WindowSize>(defaultWindow);
  const [dimension, setDimension] = useState<Dimension>("sector");
  const [value, setValue] = useState("");

  // 防抖 300ms：每键不触发请求，仅停顿后用 debounced 查询；输入框仍用 value 保响应。
  // 清空（含切维度清空）即时断查由 useDebounce 内部处理（见 hooks/useDebounce.ts）。
  const debounced = useDebounce(value, 300);

  const sector = dimension === "sector" ? debounced : undefined;
  const strategy = dimension === "strategy" ? debounced : undefined;

  const handleDimension = (d: Dimension) => {
    setDimension(d);
    setValue(""); // 切维度清空输入，避免残留值串味
  };

  return (
    <div className="space-y-6">
      <FilterBar
        pills={WINDOWS.map((w) => ({
          key: w.key,
          label: w.label,
          active: windowSize === w.value,
          onClick: () => setWindowSize(w.value),
        }))}
      />

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">概览</h2>
        <StatsMetrics windowSize={windowSize} />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">趋势</h2>
        <TrendsChart windowSize={windowSize} />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">下钻</h2>
        <FilterBar
          pills={DIMENSIONS.map((d) => ({
            key: d.key,
            label: d.label,
            active: dimension === d.value,
            onClick: () => handleDimension(d.value),
          }))}
          search={{
            value,
            onChange: setValue,
            placeholder: dimension === "sector" ? "输入板块名" : "输入战法名",
          }}
        />
        <BreakdownTable sector={sector} strategy={strategy} windowSize={windowSize} />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">建议</h2>
        <AdjustmentsCard windowSize={windowSize} />
      </section>

      <RecordsForm />
    </div>
  );
}
