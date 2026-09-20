import { useEffect, useRef, useState } from "react";
import type { NavGroup } from "./navigation";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  LineChart, Menu, Sun, Moon, ChevronsLeft, ChevronsRight, Github, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CommandPalette } from "@/components/command-palette/CommandPalette";
import { useTheme } from "@/hooks/useDarkMode";
import { NAV_GROUPS, APP_VERSION, REPO_URL } from "./navigation";

// Phase 2（2026-09-21）：5 线 collapsible 子组嵌套（活跃线自动展开 + 用户 toggle + localStorage 记忆）
// 代替 Phase 1 扁平——专业 IA：hub 1 跳直达 + 子组折叠（非全平铺）
// 前缀匹配：精确 === 优先，其次 p+"/" 子路径 + p+"?" 查询；不用裸 startsWith(p)（会误匹配 /database→/data）
const isPathActive = (pathname: string, prefixes: string[]) =>
  prefixes.some(p => pathname === p || pathname.startsWith(p + "/") || pathname.startsWith(p + "?"));

export function Layout() {
  const { pathname } = useLocation();
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = () => setTheme(dark ? "light" : "dark");
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // 活跃线自动展开（matchPrefix 命中）+ 用户手动 toggle + localStorage 记忆
  // try-catch + Array.isArray：防 localStorage 损坏/非数组 JSON 致白屏
  const [expandedLines, setExpandedLines] = useState<Set<string>>(() => {
    const saved = localStorage.getItem("vr-nav-expanded");
    let s: Set<string>;
    try {
      const parsed = saved ? JSON.parse(saved) : [];
      s = new Set<string>(Array.isArray(parsed) ? parsed : []);
    } catch {
      s = new Set<string>();
    }
    NAV_GROUPS.forEach(g => {
      if (isPathActive(pathname, g.matchPrefix)) s.add(g.name);
    });
    return s;
  });

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    localStorage.setItem("vr-nav-expanded", JSON.stringify([...expandedLines]));
  }, [expandedLines]);

  // 活跃线随导航自动展开（不只首次挂载——useState 初始化只跑一次，导航后须 effect 追）
  useEffect(() => {
    setExpandedLines(prev => {
      const next = new Set(prev);
      NAV_GROUPS.forEach(g => {
        if (isPathActive(pathname, g.matchPrefix)) next.add(g.name);
      });
      return next;
    });
  }, [pathname]);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

  // 移动 drawer 打开时焦点进入（a11y：屏幕阅读器用户知道 dialog 出现）
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (mobileMenuOpen) dialogRef.current?.focus();
  }, [mobileMenuOpen]);

  const isTabActive = (to: string) =>
    pathname === to || pathname.startsWith(to + "/") || pathname.startsWith(to + "?");

  const toggleLine = (name: string) => {
    setExpandedLines(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const renderNavTab = (tab: { to: string; label: string }) => {
    const active = isTabActive(tab.to);
    return (
      <Link
        key={tab.to}
        to={tab.to}
        onClick={() => setMobileMenuOpen(false)}
        className={cn(
          "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors",
          active
            ? "bg-primary/10 font-medium text-primary"
            : "text-muted-foreground/80 hover:bg-muted/40 hover:text-foreground",
        )}
      >
        {tab.label}
      </Link>
    );
  };

  // 线 collapsible：标题（icon + hub link + ▸ 展开）+ subGroups 折叠
  const renderLine = (group: NavGroup) => {
    const expanded = expandedLines.has(group.name);
    const isActive = isPathActive(pathname, group.matchPrefix);
    return (
      <div key={group.name} className="space-y-0.5">
        <div className="flex items-center">
          <Link
            to={group.hub.to}
            onClick={() => setMobileMenuOpen(false)}
            className={cn(
              "flex flex-1 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive ? "bg-primary/10 text-primary" : "text-foreground hover:bg-muted/40",
            )}
          >
            <group.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            {group.hub.label}
          </Link>
          <button
            onClick={() => toggleLine(group.name)}
            className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground"
            aria-label={expanded ? `收起 ${group.name}` : `展开 ${group.name}`}
            aria-expanded={expanded}
            aria-controls={`line-${group.name}`}
          >
            <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")} aria-hidden="true" />
          </button>
        </div>
        {expanded && (
          <div id={`line-${group.name}`} className="ml-3 space-y-1 border-l border-border/30 pl-2">
            {group.subGroups.map(sg => (
              <div key={sg.name} className="space-y-0.5">
                <p className="px-3 py-0.5 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">{sg.name}</p>
                {sg.tabs.map(tab => renderNavTab(tab))}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const SidebarContent = () => (
    <nav className="flex-1 overflow-auto" aria-label="主导航">
      <div className="space-y-1">
        {NAV_GROUPS.map(group => renderLine(group))}
      </div>
    </nav>
  );

  return (
    <div className="flex h-screen">
      {/* Sidebar - 桌面可见，移动端隐藏 */}
      <aside className={cn(
        "glass relative z-10 m-2 hidden shrink-0 flex-col rounded-2xl transition-all duration-200 md:flex",
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
          /* collapsed: icon 全可见 + hover/focus 弹 flyout 列子组（a11y：focus-within 键盘可达；移动用 drawer accordion） */
          <div className="flex flex-col items-center gap-1 py-4">
            {NAV_GROUPS.map(group => {
              const Icon = group.icon;
              const isActive = isPathActive(pathname, group.matchPrefix);
              return (
                <div key={group.name} className="group/fly relative">
                  <Link
                    to={group.hub.to}
                    onClick={() => setMobileMenuOpen(false)}
                    className={cn(
                      "flex items-center justify-center rounded-lg p-2 transition-colors",
                      isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                    )}
                    title={group.name}
                    aria-label={group.name}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </Link>
                  {/* hover/focus 弹 flyout（桌面 collapsed 模式专有；max-h 防低视窗溢出） */}
                  <div
                    role="group"
                    aria-label={`${group.name} 子组`}
                    className="invisible absolute left-full top-0 z-50 ml-2 max-h-[calc(100vh-2rem)] w-56 overflow-auto rounded-lg border border-border/60 bg-popover/95 p-2 opacity-0 shadow-xl backdrop-blur transition-opacity group-hover/fly:visible group-hover/fly:opacity-100 group-focus-within/fly:visible group-focus-within/fly:opacity-100"
                  >
                    <Link to={group.hub.to} onClick={() => setMobileMenuOpen(false)} className="block px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground/70 hover:text-foreground">
                      {group.name}
                    </Link>
                    {group.subGroups.map(sg => (
                      <div key={sg.name} className="space-y-0.5">
                        <p className="px-2 py-0.5 text-xs text-muted-foreground/60">{sg.name}</p>
                        {sg.tabs.map(tab => {
                          const active = isTabActive(tab.to);
                          return (
                            <Link
                              key={tab.to}
                              to={tab.to}
                              onClick={() => setMobileMenuOpen(false)}
                              className={cn(
                                "block rounded-md px-2 py-1 text-sm transition-colors",
                                active ? "bg-primary/10 font-medium text-primary" : "text-foreground/90 hover:bg-muted/40",
                              )}
                            >
                              {tab.label}
                            </Link>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
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

        {/* Mobile Drawer - accordion（5 线 + 系统，点击展开子组，活跃线默认展开） */}
        {mobileMenuOpen && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
              onClick={() => setMobileMenuOpen(false)}
              aria-hidden="true"
            />
            <div
              ref={dialogRef}
              className="fixed inset-y-0 left-0 z-50 w-64 glass md:hidden"
              role="dialog"
              aria-modal="true"
              aria-label="导航菜单"
              tabIndex={-1}
              onKeyDown={(e) => { if (e.key === "Escape") setMobileMenuOpen(false); }}
            >
              <div className="flex h-full flex-col">
                <div className="border-b border-border/50 p-4">
                  <Link to="/today" onClick={() => setMobileMenuOpen(false)} className="flex items-center gap-2">
                    <LineChart className="h-6 w-6 text-primary" />
                    <span className="font-extrabold">Vibe-Research</span>
                  </Link>
                </div>
                <nav className="flex-1 overflow-auto p-3">
                  {NAV_GROUPS.map(group => renderLine(group))}
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
