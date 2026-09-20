import { useEffect, useState } from "react";
import type { NavGroup } from "./navigation";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  LineChart, Menu, Sun, Moon, ChevronsLeft, ChevronsRight, Github, Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CommandPalette } from "@/components/command-palette/CommandPalette";
import { useTheme } from "@/hooks/useDarkMode";
import { NAV_GROUPS, APP_VERSION, REPO_URL } from "./navigation";

// Phase 1（2026-09-20）：5 线扁平 + 系统折叠，遍历 NAV_GROUPS 渲染
// 删 LEGACY 折叠区（已合并进 NAV_GROUPS）+ 移动 drawer 全 reach + 侧边栏移动端隐藏
const LINE_GROUPS = NAV_GROUPS.slice(0, 5);  // 5 线
const SYS_GROUP = NAV_GROUPS[5];  // 系统

export function Layout() {
  const { pathname } = useLocation();
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = () => setTheme(dark ? "light" : "dark");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showSystem, setShowSystem] = useState(false);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

  const isTabActive = (to: string) =>
    pathname === to || pathname.startsWith(to + "/") || pathname.startsWith(to + "?");

  // 5 线 hub active 特殊处理（/workspace?phase= 也算 /workspace active）
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

  // 5 线扁平渲染（hub tab 1 跳直达 + 其余 tab 扁平）
  const renderLine = (group: NavGroup) => (
    <div key={group.name} className="space-y-0.5">
      {group.tabs.map((tab, i) => renderNavTab(tab, i === 0))}
    </div>
  );

  const SidebarContent = () => (
    <nav className="flex-1 overflow-auto" aria-label="主导航">
      <div className="space-y-2">
        {LINE_GROUPS.map(group => renderLine(group))}
      </div>
      {/* 系统折叠 */}
      <div className="mt-4 mb-1">
        <button
          onClick={() => setShowSystem(!showSystem)}
          className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
          aria-expanded={showSystem}
          aria-controls="sys-nav"
        >
          <Settings className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="flex-1 text-left">系统</span>
          <span className={cn("text-xs transition-transform", showSystem && "rotate-90")}>›</span>
        </button>
        {showSystem && (
          <div id="sys-nav" className="ml-3 space-y-0.5 border-l border-border/30 pl-2">
            {SYS_GROUP.tabs.map(tab => renderNavTab(tab))}
          </div>
        )}
      </div>
    </nav>
  );

  return (
    <div className="flex h-screen">
      {/* Sidebar - 桌面可见，移动端隐藏（hidden md:flex 修预存吃屏宽 bug） */}
      <aside className={cn(
        "glass z-10 m-2 hidden shrink-0 flex-col rounded-2xl transition-all duration-200 md:flex",
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
          /* collapsed: 5 线 icon 全可见（修 N1 只露今日）+ 系统 icon */
          <div className="flex flex-col items-center gap-2 py-4">
            {LINE_GROUPS.map(group => {
              const Icon = group.icon;
              const hubTab = group.tabs[0];
              return (
                <Link key={group.name} to={hubTab.to} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-primary" title={group.name} aria-label={group.name}>
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </Link>
              );
            })}
            <Link to={SYS_GROUP.tabs[0].to} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-primary" title="系统" aria-label="系统">
              <Settings className="h-4 w-4" aria-hidden="true" />
            </Link>
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
                  <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-muted-foreground transition-colors hover:text-foreground" aria-label="GitHub 仓库">
                    <Github className="h-3.5 w-3.5" aria-hidden="true" />
                  </a>
                  <button onClick={() => setCollapsed(true)} className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground" aria-label="收起侧边栏">
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
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

        {/* Mobile Drawer - 全 NAV_GROUPS 渲染（修 P2 移动 reach 不到旧页） */}
        {mobileMenuOpen && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
              onClick={() => setMobileMenuOpen(false)}
              aria-hidden="true"
            />
            <div className="fixed inset-y-0 left-0 z-50 w-64 glass md:hidden" role="dialog" aria-modal="true" aria-label="导航菜单">
              <div className="flex h-full flex-col">
                <div className="border-b border-border/50 p-4">
                  <Link to="/today" onClick={() => setMobileMenuOpen(false)} className="flex items-center gap-2">
                    <LineChart className="h-6 w-6 text-primary" />
                    <span className="font-extrabold">Vibe-Research</span>
                  </Link>
                </div>
                <nav className="flex-1 overflow-auto p-4">
                  {/* 5 线 + 子 tab 全 reach */}
                  {LINE_GROUPS.map(group => (
                    <div key={group.name} className="mb-3">
                      <p className="mb-1 px-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.name}</p>
                      <div className="space-y-0.5">
                        {group.tabs.map((tab, i) => renderNavTab(tab, i === 0))}
                      </div>
                    </div>
                  ))}
                  {/* 系统折叠 */}
                  <div className="mt-2">
                    <button
                      onClick={() => setShowSystem(!showSystem)}
                      className="flex w-full items-center gap-2 py-2 text-sm font-medium text-foreground"
                      aria-expanded={showSystem}
                    >
                      <Settings className="h-4 w-4" aria-hidden="true" />
                      <span className="flex-1 text-left">系统</span>
                      <span className={cn("text-xs transition-transform", showSystem && "rotate-90")}>›</span>
                    </button>
                    {showSystem && (
                      <div className="ml-6 space-y-1">
                        {SYS_GROUP.tabs.map(tab => renderNavTab(tab))}
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
