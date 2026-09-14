// Track D M6: 焦点日 T-1/T/T+1 切换条——跨页复用。
// 读全局 focusDate（stores/focusDay）→ useDateTriplet(focusDate) 取 review/today/forward。
// 点 T-1/T/T+1 设全局 focusDate（各页 useDateTriplet 跟切重拉）；"自动"回 null。
// 今日 hub 原内联显示抽出为此组件，扩到复盘/持仓/盘面。
import { Calendar, RotateCcw } from "lucide-react";
import { useDateTriplet } from "@/lib/query";
import { useFocusDay, useSetFocusDay } from "@/stores/focusDay";
import { cn } from "@/lib/utils";

function fmtMd(d?: string): string {
  // "2026-09-13" → "09-13"
  return d ? d.slice(5) : "—";
}

export function FocusDayStrip({ className }: { className?: string }) {
  const { focusDate } = useFocusDay();
  const setFocus = useSetFocusDay();
  const { data: triplet } = useDateTriplet(focusDate ?? undefined);

  const review = triplet?.review; // T-1
  const today = triplet?.today; // T
  const forward = triplet?.forward; // T+1

  // active 判定：focusDate 命中某日 → 该日 active；null（自动）→ today active
  const isActive = (d?: string) => !!d && (focusDate === d || (focusDate === null && d === today));

  const pill = (label: string, d?: string) => {
    const active = isActive(d);
    return (
      <button
        key={label}
        onClick={() => d && setFocus(d)}
        disabled={!d}
        className={cn(
          "rounded-md px-2 py-0.5 text-xs transition-colors",
          active
            ? "bg-primary/15 font-medium text-primary"
            : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
          !d && "opacity-40",
        )}
        title={d ? `${label}: ${d}` : `${label} 无数据`}
      >
        {label} {fmtMd(d)}
      </button>
    );
  };

  return (
    <span className={cn("inline-flex items-center gap-1 text-xs text-muted-foreground", className)}>
      <Calendar className="h-3.5 w-3.5" />
      {pill("T-1", review)}
      {pill("T", today)}
      {pill("T+1", forward)}
      {focusDate !== null && (
        <button
          onClick={() => setFocus(null)}
          className="inline-flex items-center gap-0.5 rounded text-[10px] text-muted-foreground/70 hover:text-foreground"
          title="回自动模式（按时段算）"
        >
          <RotateCcw className="h-3 w-3" />
          自动
        </button>
      )}
    </span>
  );
}
