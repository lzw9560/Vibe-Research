import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, Search, Wallet, Flame,
  ChevronDown, LineChart, Github, UserRound,
  Cog, Menu,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useDarkMode";
import { PageTransition } from "@/components/ui/PageTransition";
import { Breadcrumbs, type BreadcrumbItem } from "@/components/ui/Breadcrumbs";
import { BreadcrumbContext } from "@/components/ui/BreadcrumbContext";
import {
  NAV_GROUPS,
  routeMetaMap,
  findActiveGroup,
  type RouteMeta,
} from "@/router";
import {
  SECTOR_LINKS,
  THEMES,
  APP_VERSION,
  REPO_URL,
  CONTACT_HANDLE,
  SUB_TABS,
} from "./navigation";

// 图标映射（NAV_GROUPS 使用字符串 icon 名）
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  activity: Activity,
  search: Search,
  wallet: Wallet,
  flame: Flame,
  cog: Cog,
};

// 每个分组的 tab 列表（与 router.tsx tabsByGroup 保持一致）
const TABS_BY_GROUP: string[][] = [
  ["/daily-review", "/sentiment/weather", "/intel", "/sectors", "/industry"],
  ["/stock-data", "/watchlist", "/recommendation"],
  ["/portfolio", "/my-reports", "/notes"],
  ["/workflow", "/workflow/pre-market", "/workflow/intraday", "/workflow/alerts", "/workflow/post-market"],
  ["/limitup/gene", "/limitup/auction", "/limitup/seats", "/strategy-signals", "/backtest", "/risk-dashboard"],
  ["/scheduled-tasks", "/settings", "/metrics", "/health"],
];

// 板块中心子链接的分组索引（Group 0）
const SECTOR_GROUP_INDEX = 0;

// 打板工作流的分组索引（Group 3），"更多"子菜单对应 /workflow 的子路由
const MORE_GROUP_INDEX = 3;
const MORE_TABS = [
  { to: "/workflow/pre-market", label: "盘前简报" },
  { to: "/workflow/intraday", label: "盘中监控" },
  { to: "/workflow/alerts", label: "炸板预警" },
  { to: "/workflow/post-market", label: "盘后复盘" },
];

function getQueryParam(url: string, key: string): string | null {
  try {
    const params = new URLSearchParams(url.split("?")[1] || "");
    return params.get(key);
  } catch {
    return null;
  }
}

/**
 * 根据 pathname 获取路由元数据
 */
function resolveRouteMeta(pathname: string): RouteMeta | undefined {
  // 精确匹配
  if (routeMetaMap[pathname]) return routeMetaMap[pathname] as RouteMeta;
  // 前缀匹配（如 /stock/:code → /stock/:code meta, /sectors/:key → /sectors/:key meta）
  for (const [path, meta] of Object.entries(routeMetaMap)) {
    if (path.includes(":") && pathname.startsWith(path.replace(/:\w+/, ""))) {
      return meta as RouteMeta;
    }
  }
  return undefined;
}

export function Layout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [breadcrumbs, setBreadcrumbs] = useState<BreadcrumbItem[]>([]);

  // 当前激活的分组和 Tab
  const groupIndex = findActiveGroup(pathname);

  // 展开状态
  const [sectorExpanded, setSectorExpanded] = useState(false);
  const [moreExpanded, setMoreExpanded] = useState(false);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", sidebarCollapsed ? "collapsed" : "expanded");
  }, [sidebarCollapsed]);

  // 移动端菜单锁定滚动
  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

  // 面包屑生成
  useEffect(() => {
    const meta = resolveRouteMeta(pathname);
    const items: BreadcrumbItem[] = [];

    // 分组名称
    if (groupIndex >= 0 && groupIndex < NAV_GROUPS.length) {
      items.push({ label: NAV_GROUPS[groupIndex].name });
    }

    // 页面标题
    if (meta?.title) {
      items.push({ label: meta.title });
    }

    setBreadcrumbs(items);
  }, [pathname, groupIndex]);

  const handleTabClick = (to: string) => {
    navigate(to);
    setMobileMenuOpen(false);
  };

  // 获取分组内的 tab 列表
  const getGroupTabs = (gi: number): string[] => TABS_BY_GROUP[gi] || [];

  // 获取 tab 标签
  const getTabLabel = (tabPath: string): string => {
    const meta = routeMetaMap[tabPath];
    if (meta?.title) return meta.title;
    // 对于带参数的路由，取基础路径的 meta
    const baseKey = Object.keys(routeMetaMap).find(k => tabPath.startsWith(k.replace(/:\w+/, "")));
    return baseKey ? (routeMetaMap[baseKey]?.title || tabPath) : tabPath;
  };

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className={cn(
        "glass z-10 m-2 flex shrink-0 flex-col rounded-2xl transition-all duration-300",
        "fixed inset-y-0 left-0 z-50 w-60 -translate-x-full md:relative md:inset-auto md:z-10 md:m-2 md:translate-x-0",
        sidebarCollapsed ? "md:w-14" : "md:w-60",
        mobileMenuOpen && "translate-x-0",
      )}>
        {/* Mobile Close Button */}
        <button
          onClick={() => setMobileMenuOpen(false)}
          className="absolute right-2 top-2 rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground md:hidden"
          aria-label="关闭菜单"
        >
          <ChevronDown className="h-4 w-4 rotate-90" />
        </button>

        {/* Brand */}
        <div className={cn("border-b border-border/50", sidebarCollapsed ? "flex justify-center p-3" : "p-4")}>
          <Link to="/daily-review" className={cn("flex items-center", sidebarCollapsed ? "justify-center" : "gap-2")}>
            <LineChart className="h-6 w-6 shrink-0 text-primary text-glow" />
            {!sidebarCollapsed && (
              <>
                <span className="text-lg font-extrabold tracking-tight">
                  Vibe-<span className="text-primary">Research</span>
                </span>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  个人 AI 投研系统 · A股/美股/港股
                </p>
              </>
            )}
          </Link>
        </div>

        {/* Group Nav */}
        <nav className={cn("flex-1 overflow-auto", sidebarCollapsed ? "p-1.5" : "p-2.5")} aria-label="主导航">
          {NAV_GROUPS.map((group, gi) => {
            const isActiveGroup = gi === groupIndex;
            const Icon = ICON_MAP[group.icon] || Activity;
            const tabs = getGroupTabs(gi);
            const isSectorGroup = gi === SECTOR_GROUP_INDEX && group.name === "市场概览";
            const showSectors = isSectorGroup && sectorExpanded;
            const isMoreGroup = gi === MORE_GROUP_INDEX;
            const showMore = isMoreGroup && moreExpanded;

            return (
              <div key={group.name} className="mb-1">
                {/* 分组标题 */}
                <button
                  onClick={() => {
                    if (sidebarCollapsed) {
                      setSidebarCollapsed(false);
                      return;
                    }
                    // 板块中心组：切换子菜单
                    if (isSectorGroup) {
                      setSectorExpanded((p) => !p);
                      return;
                    }
                    // 其他组：跳到第一个 tab
                    if (tabs.length > 0) {
                      handleTabClick(tabs[0]);
                    }
                  }}
                  aria-expanded={isActiveGroup && !sidebarCollapsed}
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
                      {(isSectorGroup || isMoreGroup) && (
                        <ChevronDown className={cn("h-3 w-3 transition-transform", (isSectorGroup ? sectorExpanded : moreExpanded) && "rotate-180")} />
                      )}
                    </>
                  )}
                </button>

                {/* 分组 Tab 列表（展开时） */}
                {!sidebarCollapsed && isActiveGroup && (
                  <div className="mt-0.5 space-y-0.5 pl-1">
                    {tabs.map((tab) => {
                      const isActive = pathname === tab || pathname.startsWith(tab + "/");
                      return (
                        <Link
                          key={tab}
                          to={tab}
                          aria-current={isActive ? "page" : undefined}
                          onClick={() => {
                            if (isMoreGroup && tabs[0] && pathname === tabs[0]) {
                              setMoreExpanded((p) => !p);
                            }
                          }}
                          className={cn(
                            "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors",
                            isActive
                              ? "bg-primary/12 font-medium text-primary"
                              : "text-muted-foreground/70 hover:bg-muted/40 hover:text-foreground",
                          )}
                        >
                          <span className={cn("h-1.5 w-1.5 rounded-full", isActive ? "bg-primary" : "bg-muted-foreground/30")} />
                          {getTabLabel(tab)}
                        </Link>
                      );
                    })}

                    {/* 板块中心子链接 */}
                    {showSectors && (
                      <div className="ml-1 border-l border-border/40 pl-2 space-y-0.5">
                        {SECTOR_LINKS.map(({ to: st, icon: SIcon, label: slabel }) => {
                          const sactive = pathname === st;
                          return (
                            <Link
                              key={st}
                              to={st}
                              aria-current={sactive ? "page" : undefined}
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

                    {/* "更多"子菜单 */}
                    {showMore && (
                      <div className="ml-1 border-l border-border/40 pl-2 space-y-0.5">
                        {MORE_TABS.map((tab) => {
                          const isActive = pathname === tab.to;
                          return (
                            <Link
                              key={tab.to}
                              to={tab.to}
                              aria-current={isActive ? "page" : undefined}
                              className={cn(
                                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors",
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
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Footer */}
        <div className={cn("border-t border-border/50", sidebarCollapsed ? "flex flex-col items-center gap-1.5 p-2" : "p-3")}>
          {sidebarCollapsed ? (
            <>
              <div className="flex items-center gap-1">
                {THEMES.map(({ key, emoji }) => (
                  <button
                    key={key}
                    onClick={() => setTheme(key)}
                    aria-label={`切换到${THEMES.find(t => t.key === key)?.label || key}主题`}
                    className={cn(
                      "flex h-6 w-6 items-center justify-center rounded-full text-xs transition-all",
                      theme === key
                        ? "bg-primary/20 ring-2 ring-primary/40 scale-110"
                        : "hover:bg-muted/40",
                    )}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setSidebarCollapsed(false)}
                className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                aria-label="展开侧边栏"
              >
                <ChevronDown className="h-4 w-4 rotate-[-90deg]" />
              </button>
            </>
          ) : (
            <>
              <div className="mb-2">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">主题</p>
                <div className="flex items-center gap-2">
                  {THEMES.map(({ key, emoji, label }) => (
                    <button
                      key={key}
                      onClick={() => setTheme(key)}
                      aria-pressed={theme === key}
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

              <div className="flex items-center justify-between">
                <a
                  href={`mailto:${CONTACT_HANDLE}`}
                  className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label="联系作者"
                  title="联系作者"
                >
                  <UserRound className="h-3.5 w-3.5" />
                </a>
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label="GitHub 仓库"
                  title="GitHub"
                >
                  <Github className="h-3.5 w-3.5" />
                </a>
                <button
                  onClick={() => setSidebarCollapsed(true)}
                  className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
                  aria-label="收起侧边栏"
                  title="收起"
                >
                  <ChevronDown className="h-3.5 w-3.5 rotate-[-90deg]" />
                </button>
              </div>

              <span className="block text-[11px] text-primary/80 transition-colors hover:text-primary">
                {CONTACT_HANDLE}
              </span>
              <p className="text-[11px] leading-relaxed text-muted-foreground/60">
                {APP_VERSION} · 不荐股 · 不预测 · 无倾向
              </p>
            </>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Mobile Header */}
        <div className="flex items-center gap-3 border-b border-border/40 bg-background/60 px-4 py-3 md:hidden">
          <button
            onClick={() => setMobileMenuOpen((p) => !p)}
            className="rounded p-2 text-muted-foreground transition-colors hover:text-foreground"
            aria-label="打开菜单"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Link to="/daily-review" className="flex items-center gap-2">
            <LineChart className="h-5 w-5 text-primary text-glow" />
            <span className="text-base font-extrabold tracking-tight">
              Vibe-<span className="text-primary">Research</span>
            </span>
          </Link>
        </div>

        {/* Mobile Backdrop */}
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
            onClick={() => setMobileMenuOpen(false)}
            aria-hidden="true"
          />
        )}

        {/* Primary Tab Bar - Mobile only */}
        {groupIndex >= 0 && (
          <div className="border-b border-border/40 bg-background/60 backdrop-blur-sm md:hidden">
            <div className="mx-auto max-w-6xl px-4">
              <div className="flex items-center gap-1 overflow-x-auto py-2" role="tablist">
                {TABS_BY_GROUP[groupIndex]?.map((tab) => {
                  const isActive = pathname === tab || pathname.startsWith(tab + "/");
                  return (
                    <button
                      key={tab}
                      role="tab"
                      aria-selected={isActive}
                      aria-current={isActive ? "page" : undefined}
                      onClick={() => handleTabClick(tab)}
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
                      {getTabLabel(tab)}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Secondary Sub-Tabs - Config-driven from SUB_TABS */}
        {Object.entries(SUB_TABS).map(([prefix, tabs]) => {
          if (!pathname.startsWith(prefix)) return null;
          return (
            <div key={prefix} className="border-b border-border/30 bg-background/40 md:hidden">
              <div className="mx-auto max-w-6xl px-4">
                <div className="flex items-center gap-0.5 overflow-x-auto py-1.5">
                  {tabs.map((subTab) => {
                    const activeTab = getQueryParam(pathname, "tab");
                    const isActive = subTab.to
                      ? pathname === subTab.to
                      : activeTab === subTab.key || (!activeTab && subTab.key === tabs[0]?.key);

                    return (
                      <button
                        key={subTab.key}
                        onClick={() => subTab.to && handleTabClick(subTab.to)}
                        className={cn(
                          "whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-all",
                          isActive
                            ? "bg-primary/10 text-primary"
                            : "text-muted-foreground/60 hover:text-foreground hover:bg-muted/20",
                        )}
                      >
                        {subTab.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}

        {/* Page Content */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-6xl px-6 py-6">
            {breadcrumbs.length > 0 && <Breadcrumbs items={breadcrumbs} className="mb-4" />}
            <BreadcrumbContext.Provider value={{ items: breadcrumbs, setItems: setBreadcrumbs }}>
              <PageTransition>
                <Outlet />
              </PageTransition>
            </BreadcrumbContext.Provider>
          </div>
        </main>
      </div>
    </div>
  );
}
