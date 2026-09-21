// 加自选按钮——传 code，点击调 apiWatchlist.add，状态反馈（idle/loading/added/error）
// 复用 watchlist.ts POST API + localStorage fallback。选股页通用。
import { useState } from "react";
import { Star, Check, Loader2 } from "lucide-react";
import { apiWatchlist } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

interface Props {
  code: string;
  size?: "sm" | "md";
  className?: string;
}

export function AddToWatchlistButton({ code, size = "sm", className }: Props) {
  const [state, setState] = useState<"idle" | "loading" | "added" | "error">("idle");

  const onClick = async () => {
    if (state === "loading" || state === "added") return;
    setState("loading");
    try {
      await apiWatchlist.add([code]);
      setState("added");
      setTimeout(() => setState("idle"), 1500);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 1500);
    }
  };

  const Icon = state === "loading" ? Loader2 : state === "added" ? Check : Star;
  const label = state === "added" ? "已加入" : state === "error" ? "失败" : "加自选";

  return (
    <button
      onClick={onClick}
      disabled={state === "loading" || state === "added"}
      title={`加 ${code} 到自选`}
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-1 font-medium transition-colors",
        size === "sm" ? "text-xs" : "text-sm",
        state === "added"
          ? "bg-emerald-500/15 text-emerald-600"
          : state === "error"
            ? "bg-red-500/15 text-red-600"
            : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        className,
      )}
    >
      <Icon className={cn("h-3.5 w-3.5", state === "loading" && "animate-spin")} />
      {label}
    </button>
  );
}
