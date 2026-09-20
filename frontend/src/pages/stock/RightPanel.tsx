// S179 Phase 1: 个股 cockpit 右侧面板——8 图标竖排 toggle（自选/资讯/财务/资金/信号/笔记/龙虎榜/AI）。
// 纯图标 rail：点图标 → onActiveChange 上报 → 主区 ChartCenter 渲染对应 panel（不在右侧窄栏显示）。
// 信号/龙虎榜已在主区（SignalArea/StockSeatCard），点这俩 tab = 滚到主区对应位置（pointer）。
import type { ReactNode } from "react";
import {
  Star,
  Newspaper,
  BarChart3,
  Wallet,
  Activity,
  StickyNote,
  ScrollText,
  Sparkles,
  Gauge,
  Building2,
  ShieldAlert,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type PanelKey =
  | "watchlist"
  | "news"
  | "financials"
  | "fundflow"
  | "signals"
  | "notes"
  | "dragonTiger"
  | "ai"
  | "techScore"
  | "basicInfo"
  | "validatedEdge"
  | "todaySignals";

interface PanelDef {
  key: PanelKey;
  label: string;
  icon: ReactNode;
}

function buildPanels(): PanelDef[] {
  return [
    { key: "watchlist", label: "自选", icon: <Star className="h-4 w-4" aria-hidden="true" /> },
    { key: "news", label: "资讯", icon: <Newspaper className="h-4 w-4" aria-hidden="true" /> },
    { key: "financials", label: "财务", icon: <BarChart3 className="h-4 w-4" aria-hidden="true" /> },
    { key: "fundflow", label: "资金", icon: <Wallet className="h-4 w-4" aria-hidden="true" /> },
    { key: "signals", label: "信号", icon: <Activity className="h-4 w-4" aria-hidden="true" /> },
    { key: "todaySignals", label: "今日", icon: <Zap className="h-4 w-4" aria-hidden="true" /> },
    { key: "validatedEdge", label: "验证", icon: <ShieldAlert className="h-4 w-4" aria-hidden="true" /> },
    { key: "techScore", label: "技术", icon: <Gauge className="h-4 w-4" aria-hidden="true" /> },
    { key: "basicInfo", label: "基本面", icon: <Building2 className="h-4 w-4" aria-hidden="true" /> },
    { key: "notes", label: "笔记", icon: <StickyNote className="h-4 w-4" aria-hidden="true" /> },
    { key: "dragonTiger", label: "龙虎榜", icon: <ScrollText className="h-4 w-4" aria-hidden="true" /> },
    { key: "ai", label: "AI", icon: <Sparkles className="h-4 w-4" aria-hidden="true" /> },
  ];
}

interface RightPanelProps {
  /** 当前活跃 panel（高亮图标）；null=无活跃 */
  active: PanelKey | null;
  /** 点图标上报——主区据此渲染对应 panel */
  onActiveChange: (k: PanelKey | null) => void;
}

/**
 * RightPanel — 个股 cockpit 右侧 8 图标 toggle rail（L3 层）。
 *
 * 纯图标 rail（w-14 贴右缘竖排 8 图标），click 上报 onActiveChange，
 * panel 内容在主区 ChartCenter 渲染（宽敞，不在右侧窄栏挤）。
 * 信号/龙虎榜已在主区（SignalArea/StockSeatCard），点这俩 tab = pointer。
 */
export function RightPanel({ active, onActiveChange }: RightPanelProps) {
  const panels = buildPanels();
  return (
    <div className="flex h-full justify-end">
    <nav
      className="flex w-14 flex-col items-center gap-0.5 border-l border-border/40 bg-muted/10 py-2"
      aria-label="个股面板"
    >
      {panels.map((p) => {
        const isActive = active === p.key;
        return (
          <button
            key={p.key}
            type="button"
            onClick={() => onActiveChange(isActive ? null : p.key)}
            title={p.label}
            aria-pressed={isActive}
            className={cn(
              "flex w-12 flex-col items-center gap-0.5 rounded-md px-1 py-2 text-xs transition-colors",
              isActive
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
            )}
          >
            {p.icon}
            <span className="whitespace-nowrap">{p.label}</span>
          </button>
        );
      })}
    </nav>
    </div>
  );
}

export default RightPanel;
