import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  LineChart, Menu, Sun, Moon, ChevronsLeft, ChevronsRight,
  Github, Home, Settings as SettingsIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CommandPalette } from "@/components/command-palette/CommandPalette";
import { useTheme } from "@/hooks/useDarkMode";
import {
  NAV_GROUPS, LEGACY_NAV_GROUPS, APP_VERSION, REPO_URL,
} from "./navigation";

// flat-4 rail: 4 主入口永久可见(1跳直达), 系统折叠(2跳), 旧页折叠(兼容)
const MAIN_NAV = NAV_GROUPS[0];   // 主入口
const SYS_NAV = NAV_GROUPS[1];    // 系统

export function Layout() {
  const { pathname } = useLocation();
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = () => setTheme(dark ? "light" : "dark");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showLegacy, setShowLegacy] = useState(false);
  const [showSystem, setShowSystem] = useState(false);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

  // active 判定：精确匹配或前缀(参数路由)
  const isTabActive = (to: string) =>
    pathname === to || pathname.startsWith(to + "/") || pathname.startsWith(to + "?");

  // 主入口 active 特殊处理：/workspace?phase= 也算 /workspace active
  const isMainActive = (to: string) => {
    if (to === "/today") return pathname === "/" || pathname === "/today";
    if (to === "/workspace") return pathname.startsWith("/workspace");
    if (to === "/review") return pathname.startsWith("/review");
    if (to === "/graph") return pathname.startsWith("/graph");
    if (to === "/data") return pathname.startsWith("/data");
    return isTabActive(to);
  };

  const renderNavTab = (tab: { to: string; label: string }, isMain = false) => {
    const active = isMain ? isMainActive(tab.to) : isTabActive(tab.to);
    return (
      <Link
        key={tab.to}
        to={tab.to}
        onClick={() => setMobileMenuOpen(false)}
        className={cn(
          "flex items-center gap-2 rounded-lg text-sm transition-colors",
          isMain ? "px-3 py-2 font-medium" : "px-3 py-1.5",
          active
            ? "bg-primary/10 font-medium text-primary"
            : "text-muted-foreground/80 hover:bg-muted/40 hover:text-foreground",
        )}
      >
        {tab.label}
      </Link>
    );
  };

  const SidebarContent = () => (
    <>
      {/* 4 主入口 flat rail — 永久可见, 1 跳直达 */}
      <nav className="flex-1 overflow-auto" aria-label="主导航">
        <div className="space-y-0.5">
          {MAIN_NAV.tabs.map(tab => renderNavTab(tab, true))}
        </div>

        {/* 系统折叠 */}
        <div className="mt-4 mb-1">
          <button
            onClick={() => setShowSystem(!showSystem)}
            className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
          >
            <SettingsIcon className="h-3.5 w-3.5" />
            <span className="flex-1 text-left">系统</span>
            <span className={cn("text-xs transition-transform", showSystem && "rotate-90")}>›</span>
          </button>
          {showSystem && (
            <div className="ml-3 space-y-0.5 border-l border-border/30 pl-2">
              {SYS_NAV.tabs.map(tab => renderNavTab(tab))}
            </div>
          )}
        </div>

        {/* 旧页兼容折叠 */}
        <div className="mt-2 mb-1">
          <button
            onClick={() => setShowLegacy(!showLegacy)}
            className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
          >
            <span className="flex-1 text-left">更多(旧页)</span>
            <span className={cn("text-xs transition-transform", showLegacy && "rotate-90")}>›</span>
          </button>
          {showLegacy && !collapsed && (
            <div className="ml-3 space-y-0.5 border-l border-border/30 pl-2">
              {LEGACY_NAV_GROUPS.flatMap(g => g.tabs).map(tab => renderNavTab(tab))}
            </div>
          )}
        </div>
      </nav>
    </>
  );

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className={cn(
        "glass z-10 m-2 flex shrink-0 flex-col rounded-2xl transition-all duration-200",
        collapsed ? "w-14" : "w-56",
      )}>
        {/* Brand */}
        <div className={cn("border-b border-border/50", collapsed ? "flex justify-center p-3" : "p-4")}>
          <Link to="/today" className={cn("flex items-center", collapsed ? "justify-center" : "gap-2")}>
            <LineChart className="h-6 w-6 shrink-0 text-primary text-glow" />
            {!collapsed && (
              <span className="text-lg font-extrabold tracking-tight">
                Vibe-<span className="text-primary">Research</span>
              </span>
            )}
          </Link>
        </div>

        {collapsed ? (
          <div className="flex flex-col items-center gap-2 py-4">
            <Link to="/today" className="rounded p-1.5 text-muted-foreground transition-colors hover:text-primary" title="今日">
              <Home className="h-4 w-4" />
            </Link>
            {SYS_NAV.tabs.slice(0, 2).map(tab => {
              const Icon = SettingsIcon;
              return (
                <Link key={tab.to} to={tab.to} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-primary" title={tab.label}>
                  <Icon className="h-4 w-4" />
                </Link>
              );
            })}
          </div>
        ) : (
          <SidebarContent />
        )}

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
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {APP_VERSION} · 模拟盘跟踪 · 真盘你定
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
          <Link to="/today" className="flex items-center gap-2">
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
                  <Link to="/today" onClick={() => setMobileMenuOpen(false)} className="flex items-center gap-2">
                    <LineChart className="h-6 w-6 text-primary" />
                    <span className="font-extrabold">Vibe-Research</span>
                  </Link>
                </div>
                <nav className="flex-1 overflow-auto p-4">
                  <div className="space-y-1">
                    {MAIN_NAV.tabs.map(tab => renderNavTab(tab, true))}
                  </div>
                  <div className="mt-4">
                    <button
                      onClick={() => setShowSystem(!showSystem)}
                      className="flex w-full items-center gap-2 py-2 text-sm font-medium text-foreground"
                    >
                      <SettingsIcon className="h-4 w-4" />
                      <span className="flex-1 text-left">系统</span>
                      <span className={cn("text-xs transition-transform", showSystem && "rotate-90")}>›</span>
                    </button>
                    {showSystem && (
                      <div className="ml-6 space-y-1">
                        {SYS_NAV.tabs.map(tab => renderNavTab(tab))}
                      </div>
                    )}
                  </div>
                </nav>
              </div>
            </div>
          </>
        )}

        <div className="mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
      <CommandPalette />
    </div>
  );
}
