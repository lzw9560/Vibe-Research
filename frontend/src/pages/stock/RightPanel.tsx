// S179 Phase 1: 个股 cockpit 右侧面板——8 图标竖排 toggle（自选/资讯/财务/资金/信号/笔记/龙虎榜/AI）。
// 单活手风琴：click 新 panel = 切，click 活 panel = 收。每 panel 内容 Phase 2 接线（stub）。
// 图标 rail 固定窄条（w-14）贴右缘，展开内容占 rail 左侧剩余空间。
import { useState, type ReactNode } from "react";
import {
  Star,
  Newspaper,
  BarChart3,
  Wallet,
  Activity,
  StickyNote,
  ScrollText,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";

type PanelKey =
  | "watchlist"
  | "news"
  | "financials"
  | "fundflow"
  | "signals"
  | "notes"
  | "dragonTiger"
  | "ai";

interface PanelDef {
  key: PanelKey;
  label: string;
  icon: ReactNode;
  /** Phase 2 接线提示：标注待接的 API 端点 */
  hint: ReactNode;
}

function buildPanels(code: string): PanelDef[] {
  return [
    {
      key: "watchlist",
      label: "自选",
      icon: <Star className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          加入/移除自选·<code className="font-mono">/api/watchlist</code> 待接线
        </span>
      ),
    },
    {
      key: "news",
      label: "资讯",
      icon: <Newspaper className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          新闻 + 公告·<code className="font-mono">/api/news</code> +{" "}
          <code className="font-mono">/api/announcements</code> 待接线
        </span>
      ),
    },
    {
      key: "financials",
      label: "财务",
      icon: <BarChart3 className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          财报 + 估值·<code className="font-mono">/api/financials</code> +{" "}
          <code className="font-mono">/api/valuation</code> 待接线
        </span>
      ),
    },
    {
      key: "fundflow",
      label: "资金",
      icon: <Wallet className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          资金流向·<code className="font-mono">/api/fund-flow?code={code}</code>{" "}
          待接线
        </span>
      ),
    },
    {
      key: "signals",
      label: "信号",
      icon: <Activity className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          策略信号·<code className="font-mono">/api/strategy/signals/{code}</code>{" "}
          待接线
        </span>
      ),
    },
    {
      key: "notes",
      label: "笔记",
      icon: <StickyNote className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          个股笔记·<code className="font-mono">/api/notes</code> 待接线
        </span>
      ),
    },
    {
      key: "dragonTiger",
      label: "龙虎榜",
      icon: <ScrollText className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          龙虎榜·<code className="font-mono">/api/dragon-tiger?code={code}</code>{" "}
          待接线
        </span>
      ),
    },
    {
      key: "ai",
      label: "AI",
      icon: <Sparkles className="h-4 w-4" aria-hidden="true" />,
      hint: (
        <span>
          问 AI·<code className="font-mono">AskAiButton</code> 待接线
        </span>
      ),
    },
  ];
}

interface RightPanelProps {
  /** 当前个股代码——Phase 2 各 panel 据此取数 */
  code: string;
}

/**
 * RightPanel — 个股 cockpit 右侧 8 图标 toggle 面板（L3 层）。
 *
 * 图标 rail（w-14）贴右缘竖排 8 图标，click toggle 展开对应 stub 面板。
 * 单活手风琴：同时只展开一个 panel；click 活 panel 收起。
 * panel 内容 Phase 2 接线（资讯/财务/资金/龙虎榜接现有 API，自选/笔记/AI 待定）。
 */
export function RightPanel({ code }: RightPanelProps) {
  const [active, setActive] = useState<PanelKey | null>(null);
  const panels = buildPanels(code);
  const activeDef = panels.find((p) => p.key === active) ?? null;

  return (
    <div className="flex h-full">
      {/* 展开内容区（flex-1，rail 左侧）*/}
      <div className="flex-1 overflow-auto p-3">
        {activeDef ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-primary">{activeDef.icon}</span>
              <h4 className="text-sm font-semibold">{activeDef.label}</h4>
            </div>
            <HonestEmptyState
              message={`「${activeDef.label}」面板·Phase 2 接线`}
              hint={activeDef.hint}
            />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-xs text-muted-foreground/50">
              点击右侧图标展开面板
            </p>
          </div>
        )}
      </div>

      {/* 图标 rail（w-14，贴右缘，竖排 8 图标）*/}
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
              onClick={() => setActive(isActive ? null : p.key)}
              title={p.label}
              aria-pressed={isActive}
              className={cn(
                "flex w-12 flex-col items-center gap-0.5 rounded-md px-1 py-2 text-[10px] transition-colors",
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
