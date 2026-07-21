import { cn } from "@/lib/utils";

const SIGNAL_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  "多资金共识": { bg: "bg-success/10", text: "text-success", label: "✅ 多资金共识" },
  "分歧信号": { bg: "bg-warning/10", text: "text-warning", label: "⚠️ 分歧信号" },
  "机构主导": { bg: "bg-blue-400/10", text: "text-blue-400", label: "🏛️ 机构主导" },
  "游资主导": { bg: "bg-orange-400/10", text: "text-orange-400", label: "🐟 游资主导" },
};

export function SeatConsensusBadge({ signal }: { signal: string | null }) {
  const style = signal ? SIGNAL_STYLES[signal] : null;
  if (!style) {
    return (
      <span className="inline-flex items-center rounded-full bg-muted/20 px-2 py-0.5 text-[11px] text-muted-foreground">
        无信号
      </span>
    );
  }
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium", style.bg, style.text)}>
      {style.label}
    </span>
  );
}
