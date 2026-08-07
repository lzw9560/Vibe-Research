import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /** 抽屉贴边方向，默认右侧。 */
  side?: "right" | "left";
}

// S031 R18：轻量侧边抽屉——createPortal 到 body，遮罩 + Esc + 点遮罩关。
// 不整页跳路由，供候选诊断卡（CandidateDetailPanel）等复用；路由页保留供直链。
export function Sheet({ open, onClose, children, side = "right" }: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div
        data-testid="sheet-overlay"
        aria-hidden="true"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />
      <div
        data-testid="sheet-panel"
        role="dialog"
        aria-modal="true"
        className={cn(
          "absolute top-0 h-full w-full max-w-md overflow-y-auto bg-background p-4 shadow-xl",
          side === "right" ? "right-0" : "left-0",
        )}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
