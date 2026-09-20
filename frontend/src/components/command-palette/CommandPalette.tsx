// S179 P0.2: 全局命令面板浮层——输入框 + 模糊匹配 + 键盘导航 + Cmd+K toggle + Esc 关闭。
// 自建组件（不引 cmdk/kbar），复用项目 glass 样式 + createPortal 范式（同 Sheet.tsx）。
import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType, KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Search, CornerDownLeft, Hash, Filter, Route, Telescope } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSelectStock } from "@/stores/currentStock";
import { useCommandPalette } from "./useCommandPalette";
import { searchAll, type SearchItem, type SearchGroup } from "./searchIndex";

const GROUP_ICON: Record<SearchGroup, ComponentType<{ className?: string }>> = {
  route: Route,
  stock: Hash,
  signal: Filter,
  research: Telescope,
};

const GROUP_LABEL: Record<SearchGroup, string> = {
  route: "路由",
  stock: "股票",
  signal: "信号",
  research: "研究深挖",
};

const MAX_RESULTS = 12;

export function CommandPalette() {
  const { isOpen, close } = useCommandPalette();
  const navigate = useNavigate();
  const selectStock = useSelectStock();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => searchAll(query, MAX_RESULTS), [query]);

  // open 时重置 + 聚焦输入框 + 锁 body 滚动
  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setActiveIndex(0);
      document.body.style.overflow = "hidden";
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  // results 数量变化时 clamp activeIndex
  useEffect(() => {
    setActiveIndex((prev) => Math.min(prev, results.length - 1));
  }, [results.length]);

  // 滚动 active item 到可视区
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (!isOpen) return null;

  const executeAction = (item: SearchItem) => {
    switch (item.action.type) {
      case "navigate":
        navigate(item.action.path);
        break;
      case "select-stock":
        selectStock(item.action.code, item.action.name, "command-palette");
        navigate(`/stock/${item.action.code}`);
        break;
      case "apply-preset":
        navigate(item.action.path);
        break;
    }
    close();
  };

  const handleKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((p) => Math.min(p + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((p) => Math.max(p - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = results[activeIndex];
      if (item) executeAction(item);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]"
      onKeyDown={handleKeyDown}
    >
      {/* 遮罩：点击关闭 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={close}
        aria-hidden="true"
      />
      {/* 面板 */}
      <div
        className="glass relative w-full max-w-xl rounded-xl shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="命令面板"
      >
        {/* 输入框 */}
        <div className="flex items-center gap-2 border-b border-border/50 px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            placeholder="搜索路由、股票代码、预设信号…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="rounded border border-border/50 px-1.5 py-0.5 text-xs text-muted-foreground">
            ESC
          </kbd>
        </div>
        {/* 结果列表 */}
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto p-2">
          {results.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              无匹配结果
            </div>
          ) : (
            results.map((item, idx) => {
              const Icon = GROUP_ICON[item.group];
              const active = idx === activeIndex;
              return (
                <button
                  key={item.id}
                  data-idx={idx}
                  onClick={() => executeAction(item)}
                  onMouseEnter={() => setActiveIndex(idx)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                    active
                      ? "bg-primary/10 text-primary"
                      : "text-foreground hover:bg-muted/40",
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      active ? "text-primary" : "text-muted-foreground",
                    )}
                  />
                  <span className="flex-1 truncate">{item.title}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {GROUP_LABEL[item.group]}
                  </span>
                  {active && (
                    <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
