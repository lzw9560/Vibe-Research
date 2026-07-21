import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, Wallet, Search,
  ChevronDown, LineChart, Github, UserRound, Flame,
  Cog, Cpu, Database, Cable, Rocket, FlaskConical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useDarkMode";
import type { Theme } from "@/hooks/useDarkMode";

const APP_VERSION = "v0.1.3";
const REPO_URL = "https://github.com/simonlin1212/Vibe-Research";
const SITE_URL = "https://www.simonlin.net";

// ---- 分组定义 ----
const GROUPS = [
  {
    name: "市场概览",
    icon: Activity,
    tabs: [
      { to: "/daily-review", label: "每日复盘" },
      { to: "/intel", label: "资讯雷达" },
      { to: "/sectors", label: "板块中心" },
      { to: "/industry", label: "行业排行" },
    ],
  },
  {
    name: "个股分析",
    icon: Search,
    tabs: [
      { to: "/stock-data", label: "个股数据" },
      { to: "/watchlist", label: "自选股" },
    ],
  },
  {
    name: "投资管理",
    icon: Wallet,
    tabs: [
      { to: "/portfolio", label: "我的持仓" },
      { to: "/my-reports", label: "我的研报" },
      { to: "/notes", label: "研究记录" },
    ],
  },
  {
    name: "打板策略",
    icon: Flame,
    tabs: [
      { to: "/limitup", label: "打板策略" },
      { to: "/settings", label: "接入 AI" },
    ],
  },
];

// 板块中心子链接
const SECTOR_LINKS = [
  { to: "/sectors/humanoid", icon: Cog, label: "人形机器人" },
  { to: "/sectors/ai-computing", icon: Cpu, label: "AI 算力" },
  { to: "/sectors/hbm", icon: Database, label: "HBM" },
  { to: "/sectors/cpo", icon: Cable, label: "光互联" },
  { to: "/sectors/business-space", icon: Rocket, label: "商业航天" },
  { to: "/sectors/ai-pharma", icon: FlaskConical, label: "生物医药" },
];

// 主题选项
const THEMES: { key: Theme; emoji: string; label: string }[] = [
  { key: "dark", emoji: "🌙", label: "暗色" },
  { key: "light", emoji: "☀️", label: "亮色" },
  { key: "warm-orange", emoji: "🔥", label: "暖橙" },
];

// 获取当前页面属于哪个分组和 Tab 索引
function findActiveTab(pathname: string): { groupIndex: number; tabIndex: number } | null {
  for (let gi = 0; gi < GROUPS.length; gi++) {
    const tabIdx = GROUPS[gi].tabs.findIndex((t) => t.to === pathname);
    if (tabIdx !== -1) return { groupIndex: gi, tabIndex: tabIdx };
  }
  return null;
}

export function Layout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");

  // 当前激活的分组和 Tab
  const active = findActiveTab(pathname);
  const activeGroupIndex = active?.groupIndex ?? 0;

  // 板块中心的子菜单展开状态
  const [sectorExpanded, setSectorExpanded] = useState(false);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", sidebarCollapsed ? "collapsed" : "expanded");
  }, [sidebarCollapsed]);

  // 点击 Tab 时自动导航
  const handleTabClick = (to: string) => {
    navigate(to);
  };

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className={cn(
        "glass z-10 m-2 flex shrink-0 flex-col rounded-2xl transition-all duration-300",
        sidebarCollapsed ? "w-14" : "w-60",
      )}>
        {/* Brand */}
        <div className={cn("border-b border-border/50", sidebarCollapsed ? "flex justify-center p-3" : "p-4")}>
          <Link to="/daily-review" className={cn("flex items-center", sidebarCollapsed ? "justify-center" : "gap-2")}>
            <LineChart className="h-6 w-6 shrink-0 text-primary text-glow" />
            {!sidebarCollapsed && (
              <span className="text-lg font-extrabold tracking-tight">
                Vibe-<span className="text-primary">Research</span>
              </span>
            )}
          </Link>
          {!sidebarCollapsed && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              个人 AI 投研系统 · A股/美股/港股
            </p>
          )}
        </div>

        {/* Group Nav */}
        <nav className={cn("flex-1 overflow-auto", sidebarCollapsed ? "p-1.5" : "p-2.5")}>
          {GROUPS.map((group, gi) => {
            const isActiveGroup = gi === activeGroupIndex;
            const Icon = group.icon;
            return (
              <div key={group.name} className="mb-1">
                {/* 分组标题 */}
                <button
                  onClick={() => {
                    if (sidebarCollapsed) {
                      setSidebarCollapsed(false);
                      return;
                    }
                    if (group.name === "sectors") {
                      setSectorExpanded((p) => !p);
                      return;
                    }
                    // 点击分组标题 = 跳到该分组第一个 Tab
                    handleTabClick(group.tabs[0].to);
                  }}
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wider transition-colors",
                    isActiveGroup
                      ? "text-primary"
                      : "text-muted-foreground/60 hover:text-foreground",
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  {!sidebarCollapsed && (
                    <>
                      <span className="flex-1 text-left">{group.name}</span>
                      {group.name === "sectors" && (
                        <ChevronDown className={cn("h-3 w-3 transition-transform", sectorExpanded && "rotate-180")} />
                      )}
                    </>
                  )}
                </button>

                {/* 分组 Tab 列表（展开时） */}
                {!sidebarCollapsed && isActiveGroup && (
                  <div className="mt-0.5 space-y-0.5 pl-1">
                    {group.tabs.map((tab) => {
                      const isActive = pathname === tab.to;
                      return (
                        <Link
                          key={tab.to}
                          to={tab.to}
                          className={cn(
                            "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors",
                            isActive
                              ? "bg-primary/12 font-medium text-primary"
                              : "text-muted-foreground/70 hover:bg-muted/40 hover:text-foreground",
                          )}
                        >
                          <span className={cn("h-1.5 w-1.5 rounded-full", isActive ? "bg-primary" : "bg-muted-foreground/30")} />
                          {tab.label}
                        </Link>
                      );
                    })}

                    {/* 板块中心子链接 */}
                    {group.name === "板块中心" && sectorExpanded && (
                      <div className="ml-3 border-l border-border/40 pl-2 space-y-0.5">
                        {SECTOR_LINKS.map(({ to: st, icon: SIcon, label: slabel }) => {
                          const sactive = pathname === st;
                          return (
                            <Link
                              key={st}
                              to={st}
                              className={cn(
                                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors",
                                sactive
                                  ? "bg-primary/10 font-medium text-primary"
                                  : "text-muted-foreground/60 hover:bg-muted/30 hover:text-foreground",
                              )}
                            >
                              <SIcon className="h-3 w-3 shrink-0" />
                              {slabel}
                            </Link>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Footer: 主题选择器 + 折叠按钮 */}
        <div className={cn("border-t border-border/50", sidebarCollapsed ? "flex flex-col items-center gap-1.5 p-2" : "p-3")}>
          {sidebarCollapsed ? (
            <>
              {/* 折叠态：只显示主题圆点和折叠按钮 */}
              <div className="flex items-center gap-1">
                {THEMES.map(({ key, emoji }) => (
                  <button
                    key={key}
                    onClick={() => setTheme(key)}
                    className={cn(
                      "flex h-6 w-6 items-center justify-center rounded-full text-xs transition-all",
                      theme === key
                        ? "bg-primary/20 ring-2 ring-primary/40 scale-110"
                        : "hover:bg-muted/40",
                    )}
                    title={key === "dark" ? "暗色" : key === "light" ? "亮色" : "暖橙"}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setSidebarCollapsed(false)}
                className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                title="展开"
              >
                <ChevronDown className="h-4 w-4 rotate-[-90deg]" />
              </button>
            </>
          ) : (
            <>
              {/* 展开态：主题选择器 */}
              <div className="mb-2">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">主题</p>
                <div className="flex items-center gap-2">
                  {THEMES.map(({ key, emoji, label }) => (
                    <button
                      key={key}
                      onClick={() => setTheme(key)}
                      className={cn(
                        "flex flex-1 items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-all",
                        theme === key
                          ? "bg-primary/15 text-primary ring-1 ring-primary/30"
                          : "text-muted-foreground/60 hover:bg-muted/30 hover:text-foreground",
                      )}
                    >
                      <span>{emoji}</span>
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* 链接行 */}
              <div className="flex items-center justify-between">
                <a
                  href={SITE_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  title="联系作者"
                >
                  <UserRound className="h-3.5 w-3.5" />
                </a>
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  title="GitHub"
                >
                  <Github className="h-3.5 w-3.5" />
                </a>
                <button
                  onClick={() => setSidebarCollapsed(true)}
                  className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
                  title="收起"
                >
                  <ChevronDown className="h-3.5 w-3.5 rotate-[-90deg]" />
                </button>
              </div>

              <a
                href={SITE_URL}
                target="_blank"
                rel="noreferrer"
                className="block text-[11px] text-primary/80 transition-colors hover:text-primary"
              >
                联系作者 · simonlin.net
              </a>
              <p className="text-[11px] leading-relaxed text-muted-foreground/60">
                {APP_VERSION} · 不荐股 · 不预测 · 无倾向
              </p>
            </>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Tab Navigation Bar */}
        {active && (
          <div className="border-b border-border/40 bg-background/60 backdrop-blur-sm">
            <div className="mx-auto max-w-6xl px-6">
              <div className="flex items-center gap-1 overflow-x-auto py-2">
                {GROUPS[active.groupIndex].tabs.map((tab) => {
                  const isActive = pathname === tab.to;
                  return (
                    <button
                      key={tab.to}
                      onClick={() => handleTabClick(tab.to)}
                      className={cn(
                        "relative whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-medium transition-all",
                        isActive
                          ? "text-primary"
                          : "text-muted-foreground/60 hover:text-foreground hover:bg-muted/30",
                      )}
                    >
                      {isActive && (
                        <span
                          className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-primary"
                          style={{ boxShadow: "0 0 8px hsl(var(--primary) / 0.5)" }}
                        />
                      )}
                      {tab.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Page Content */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-6xl px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
