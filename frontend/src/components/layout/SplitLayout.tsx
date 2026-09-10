import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ---- defaults & bounds ----
const DEFAULT_KEY = "vr-split-left";
const DEFAULT_WIDTH = 340;
const MIN_WIDTH = 220;
const MAX_WIDTH = 560;
const HANDLE_W = 6;

interface SplitLayoutProps {
  /** Left pane content (list / sidebar). */
  left: ReactNode;
  /** Right pane content (detail / main). */
  right: ReactNode;
  /** localStorage key for width persistence. */
  storageKey?: string;
  /** Default left-pane width in px (also the double-click reset target). */
  defaultWidth?: number;
  /** Minimum left-pane width in px. */
  minLeft?: number;
  /** Maximum left-pane width in px. */
  maxLeft?: number;
  className?: string;
}

/**
 * SplitLayout — CSS Grid 左右分栏 + 拖拽条 + localStorage 持久化宽度。
 *
 * grid-template-columns: var(--split-left, 340px) 1fr
 * 拖拽条改 --split-left CSS 变量，localStorage 记忆宽度。
 * 单屏 13 寸优化，不做移动端降级（用户决策）。
 * 无第三方依赖，纯 CSS Grid + pointer events。
 */
export function SplitLayout({
  left,
  right,
  storageKey = DEFAULT_KEY,
  defaultWidth = DEFAULT_WIDTH,
  minLeft = MIN_WIDTH,
  maxLeft = MAX_WIDTH,
  className,
}: SplitLayoutProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  // init from localStorage (clamped to bounds) — SSR guard for safety
  const [width, setWidth] = useState<number>(() => {
    if (typeof window === "undefined") return defaultWidth;
    const saved = localStorage.getItem(storageKey);
    const parsed = saved != null ? parseInt(saved, 10) : defaultWidth;
    return clamp(Number.isNaN(parsed) ? defaultWidth : parsed, minLeft, maxLeft);
  });

  // persist width whenever it changes
  useEffect(() => {
    localStorage.setItem(storageKey, String(width));
  }, [width, storageKey]);

  // window-level pointer listeners so drag continues outside the handle
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!draggingRef.current || containerRef.current == null) return;
      const rect = containerRef.current.getBoundingClientRect();
      setWidth(clamp(e.clientX - rect.left, minLeft, maxLeft));
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [minLeft, maxLeft]);

  // @types/react v19 removed the index signature for custom CSS properties,
  // so we assert — the runtime value is a valid CSS custom property.
  const gridStyle = {
    "--split-left": `${width}px`,
    gridTemplateColumns: `var(--split-left, ${defaultWidth}px) 1fr`,
  } as CSSProperties;

  return (
    <div
      ref={containerRef}
      className={cn("relative grid h-full w-full overflow-hidden", className)}
      style={gridStyle}
    >
      {/* left pane */}
      <div className="h-full overflow-auto">{left}</div>
      {/* right pane */}
      <div className="h-full overflow-auto">{right}</div>

      {/* drag handle — absolutely positioned on the column boundary */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-valuenow={width}
        aria-valuemin={minLeft}
        aria-valuemax={maxLeft}
        aria-label="拖拽调整左侧栏宽度"
        tabIndex={0}
        onPointerDown={(e) => {
          e.preventDefault();
          draggingRef.current = true;
          document.body.style.userSelect = "none";
          document.body.style.cursor = "col-resize";
        }}
        onDoubleClick={() => setWidth(defaultWidth)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") {
            e.preventDefault();
            setWidth((w) => clamp(w - 16, minLeft, maxLeft));
          } else if (e.key === "ArrowRight") {
            e.preventDefault();
            setWidth((w) => clamp(w + 16, minLeft, maxLeft));
          }
        }}
        className={cn(
          "absolute top-0 bottom-0 z-10 cursor-col-resize touch-none",
          "bg-border/30 transition-colors hover:bg-primary/40",
          "focus-visible:bg-primary/40 focus-visible:outline-none",
        )}
        style={{
          left: `var(--split-left, ${defaultWidth}px)`,
          width: HANDLE_W,
          transform: "translateX(-50%)",
        }}
      >
        {/* grip indicator — subtle center line, non-interactive */}
        <div className="pointer-events-none absolute left-1/2 top-1/2 h-8 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground/20" />
      </div>
    </div>
  );
}

function clamp(val: number, min: number, max: number): number {
  return Math.min(Math.max(val, min), max);
}
