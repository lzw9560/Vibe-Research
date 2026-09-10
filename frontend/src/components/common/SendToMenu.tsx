// S179 P0.4: 送入菜单——选股行 dropdown → {watchlist, portfolio, journal, research} 四向送入。
// 数据 schema 契约（spec §9 grill #14）：
//   SendPayload = { code: string; name: string; source_page: string; timestamp: number; target: SendTarget }
//
// 后端各 target API 待核实（open_question）：
//   watchlist → 仅 auctionWatchlist (GET /auction/watchlist) 存在，通用 watchlist POST API 待建
//   portfolio → POST /api/portfolio/holdings 待核实
//   journal  → POST /api/journal/closed-loop 已存在（S173），但接受 signal_id 非裸 stock_code，需适配
//   research → 本地 localStorage（notes.ts addNote 已有，不需后端）
//
// 当前组件仅 emit SendPayload（调 onSend），不直调后端——后端接线待 P1 阶段。
import { useEffect, useRef, useState, type ComponentType } from "react";
import { Star, Briefcase, BookOpen, FileSearch, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type SendTarget = "watchlist" | "portfolio" | "journal" | "research";

/**
 * 送入数据契约——所有 target 共用统一 schema（spec §9 grill #14）。
 * 调用方收到后按 target 分发到对应后端 API 或本地存储。
 */
export interface SendPayload {
  code: string;           // 6 位裸 code（如 "600519"）
  name: string;           // 股票名称
  source_page: string;    // 来源页面标识（如 "screener" / "intraday" / "candidate"）
  timestamp: number;      // 送入时间戳(ms)
  target: SendTarget;     // 目标去向
}

interface SendToMenuProps {
  /** 股票 code（6 位裸 code） */
  code: string;
  /** 股票名称 */
  name: string;
  /** 来源页面标识，写入 payload.source_page */
  sourcePage: string;
  /** 送入回调——收到完整 SendPayload（含 target）后按 target 分发 */
  onSend: (payload: SendPayload) => void;
  className?: string;
  disabled?: boolean;
}

interface TargetOption {
  id: SendTarget;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

const TARGETS: readonly TargetOption[] = [
  { id: "watchlist", label: "加入自选", icon: Star },
  { id: "portfolio", label: "加入持仓", icon: Briefcase },
  { id: "journal", label: "加入交易日志", icon: BookOpen },
  { id: "research", label: "加入研究记录", icon: FileSearch },
];

export function SendToMenu({ code, name, sourcePage, onSend, className, disabled }: SendToMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点外部关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const handleSelect = (target: SendTarget) => {
    onSend({
      code,
      name,
      source_page: sourcePage,
      timestamp: Date.now(),
      target,
    });
    setOpen(false);
  };

  return (
    <div ref={ref} className={cn("relative inline-block", className)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded border border-border/40 bg-card/30 px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-50"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        送入
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 min-w-[140px] overflow-hidden rounded-lg border border-border/60 bg-background py-1 shadow-lg"
        >
          {TARGETS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="menuitem"
              onClick={() => handleSelect(id)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] text-foreground transition-colors hover:bg-muted/40"
            >
              <Icon className="h-3.5 w-3.5 text-muted-foreground" />
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
