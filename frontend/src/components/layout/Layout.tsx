import { useEffect, useState, useMemo } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  LineChart, Menu, Sun, Moon, ChevronsLeft, ChevronsRight,
  Github,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useDarkMode";
import { NAV_GROUPS, APP_VERSION, REPO_URL, SUB_TABS } from "./navigation";

export function Layout() {
  const { pathname } = useLocation();
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = () => setTheme(dark ? "light" : "dark");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<string>("市场总览");

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

  const getActiveGroup = () => {
    for (const group of NAV_GROUPS) {
      if (group.tabs.some(tab => pathname === tab.to || pathname.startsWith(tab.to))) {
        return group.name;
      }
    }
    return "市场总览";
  };

  useEffect(() => {
    const active = getActiveGroup();
    if (active !== expandedGroup) setExpandedGroup(active);
  }, [pathname]);

  // 二级 sub tabs：匹配 SUB_TABS 前缀，有则渲染横向 TabBar（无则隐藏）
  const subTabs = useMemo(() => {
    const matched = Object.keys(SUB_TABS)
      .filter(prefix => pathname.startsWith(prefix))
      .sort((a, b) => b.length - a.length); // 最长前缀优先（/sentiment/weather 优先于 /sentiment）
    if (matched.length === 0) return null;
    const key = matched[0];
    return { tabs: SUB_TABS[key], prefix: key };
  }, [pathname]);

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className={cn(
        "glass z-10 m-2 flex shrink-0 flex-col rounded-2xl transition-all duration-200",
        collapsed ? "w-14" : "w-60",
      )}>
        {/* Brand */}
        <div className={cn("border-b border-border/50", collapsed ? "flex justify-center p-3" : "p-4")}>
          <Link to="/daily-review" className={cn("flex items-center", collapsed ? "justify-center" : "gap-2")}>
            <LineChart className="h-6 w-6 shrink-0 text-primary text-glow" />
            {!collapsed && (
              <span className="text-lg font-extrabold tracking-tight">
                Vibe-<span className="text-primary">Research</span>
              </span>
            )}
          </Link>
        </div>

        {/* Nav Groups */}
        <nav className="flex-1 overflow-auto" aria-label="主导航">
          {NAV_GROUPS.map((group) => {
            const Icon = group.icon;
            const isExpanded = expandedGroup === group.name;
            const hasActive = group.tabs.some(tab => 
              pathname === tab.to || pathname.startsWith(tab.to)
            );

            return (
              <div key={group.name} className="mb-1">
                {/* Group Header */}
                <button
                  onClick={() => setExpandedGroup(isExpanded ? "" : group.name)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-sm font-medium transition-colors",
                    collapsed ? "justify-center" : "",
                    hasActive ? "text-primary" : "text-muted-foreground hover:text-foreground"
                  )}
                  title={collapsed ? group.name : undefined}
                >
                  <Icon className={cn("h-4 w-4", hasActive && "text-primary")} />
                  {!collapsed && (
                    <>
                      <span className="flex-1 text-left">{group.name}</span>
                      <span className={cn(
                        "text-xs transition-transform",
                        isExpanded && "rotate-90"
                      )}>›</span>
                    </>
                  )}
                </button>

                {/* Group Tabs */}
                {isExpanded && !collapsed && (
                  <div className="ml-4 space-y-0.5 border-l border-border/30 pl-2">
                    {group.tabs.map((tab) => {
                      const active = pathname === tab.to || pathname.startsWith(tab.to);
                      return (
                        <Link
                          key={tab.to}
                          to={tab.to}
                          onClick={() => setMobileMenuOpen(false)}
                          className={cn(
                            "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors",
                            active
                              ? "bg-primary/10 font-medium text-primary"
                              : "text-muted-foreground/80 hover:bg-muted/40 hover:text-foreground"
                          )}
                        >
                          {tab.label}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Footer */}
        <div className={cn("border-t border-border/50", collapsed ? "flex flex-col items-center gap-2 p-2" : "space-y-2 p-3")}>
          {collapsed ? (
            <>
              <button onClick={toggle} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" aria-label={dark ? "切换到亮色" : "切换到暗色"}>
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <button onClick={() => setCollapsed(false)} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" aria-label="展开侧边栏">
                <ChevronsRight className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <button onClick={toggle} className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground">
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                  {dark ? "亮色" : "暗色"}
                </button>
                <div className="flex items-center gap-2">
                  <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-muted-foreground transition-colors hover:text-foreground">
                    <Github className="h-3.5 w-3.5" />
                  </a>
                  <button onClick={() => setCollapsed(true)} className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground" aria-label="收起侧边栏">
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground/60">
                {APP_VERSION} · 不荐股 · 不预测 · 无倾向
              </p>
            </>
          )}
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
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

        {/* Mobile Drawer */}
        {mobileMenuOpen && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
              onClick={() => setMobileMenuOpen(false)}
              aria-hidden="true"
            />
            <div className="fixed inset-y-0 left-0 z-50 w-64 glass md:hidden">
              <div className="flex h-full flex-col">
                <div className="border-b border-border/50 p-4">
                  <Link to="/daily-review" onClick={() => setMobileMenuOpen(false)} className="flex items-center gap-2">
                    <LineChart className="h-6 w-6 text-primary" />
                    <span className="font-extrabold">Vibe-Research</span>
                  </Link>
                </div>
                <nav className="flex-1 overflow-auto p-4">
                  {NAV_GROUPS.map((group) => {
                    const Icon = group.icon;
                    const isExpanded = expandedGroup === group.name;
                    return (
                      <div key={group.name} className="mb-2">
                        <button
                          onClick={() => setExpandedGroup(isExpanded ? "" : group.name)}
                          className="flex w-full items-center gap-2 py-2 text-sm font-medium text-foreground"
                        >
                          <Icon className="h-4 w-4" />
                          <span className="flex-1">{group.name}</span>
                          <span className={cn("text-xs transition-transform", isExpanded && "rotate-90")}>›</span>
                        </button>
                        {isExpanded && (
                          <div className="ml-6 space-y-1">
                            {group.tabs.map((tab) => {
                              const active = pathname === tab.to || pathname.startsWith(tab.to);
                              return (
                                <Link
                                  key={tab.to}
                                  to={tab.to}
                                  onClick={() => setMobileMenuOpen(false)}
                                  className={cn(
                                    "block py-1.5 text-sm",
                                    active ? "font-medium text-primary" : "text-muted-foreground"
                                  )}
                                >
                                  {tab.label}
                                </Link>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </nav>
              </div>
            </div>
          </>
        )}

        <div className="mx-auto max-w-6xl px-6 py-6">
          {subTabs && (
            <nav className="mb-4 flex flex-wrap items-center gap-1 rounded-lg bg-muted/20 p-1" aria-label="二级导航">
              {subTabs.tabs.map((tab) => {
                const tabTo = tab.to ?? `${subTabs.prefix === "/stock/" ? pathname : subTabs.prefix}${tab.key ? `?tab=${tab.key}` : ""}`;
                const isActive = tab.to
                  ? pathname === tab.to
                  : (new URLSearchParams(window.location.search).get("tab") ?? subTabs.tabs[0]?.key) === tab.key;
                if (tab.to) {
                  return (
                    <Link
                      key={tab.key}
                      to={tab.to}
                      className={cn(
                        "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                        isActive
                          ? "bg-primary/15 text-primary"
                          : "text-muted-foreground hover:text-foreground hover:bg-muted/30",
                      )}
                    >
                      {tab.label}
                    </Link>
                  );
                }
                return (
                  <Link
                    key={tab.key}
                    to={tabTo}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                      isActive
                        ? "bg-primary/15 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/30",
                    )}
                  >
                    {tab.label}
                  </Link>
                );
              })}
            </nav>
          )}
          <Outlet />
        </div>
      </main>
    </div>
  );
}
