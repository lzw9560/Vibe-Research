import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  Activity, Radar, LayoutGrid, Wallet, Settings, Search, NotebookPen,
  Moon, Sun, ChevronsLeft, ChevronsRight, LineChart, Github, UserRound,
  Cog, Cpu, Database, Cable, Rocket, FlaskConical, Star, FileText, Flame,
  Menu, Target, Zap, Shield, History, Cloud, BarChart3, HeartPulse, Calendar, Building2,
  Dna, Gavel, Car,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";

const APP_VERSION = "v0.1.3";
const REPO_URL = "https://github.com/simonlin1212/Vibe-Research";
const SITE_URL = "https://www.simonlin.net"; // 作者主页

const NAV = [
  { to: "/daily-review", icon: Activity, label: "每日复盘" },
  { to: "/intel", icon: Radar, label: "资讯雷达" },
  { to: "/sectors", icon: LayoutGrid, label: "板块中心" },
  { to: "/stock-data", icon: Search, label: "个股数据" },
  { to: "/watchlist", icon: Star, label: "自选股" },
  { to: "/portfolio", icon: Wallet, label: "我的持仓" },
  { to: "/my-reports", icon: FileText, label: "我的研报" },
  { to: "/notes", icon: NotebookPen, label: "研究记录" },
  { to: "/recommendation", icon: Target, label: "智能推荐" },
  { to: "/strategy-signals", icon: Zap, label: "策略信号" },
  { to: "/risk-dashboard", icon: Shield, label: "风险看板" },
  { to: "/sector-divergence", icon: BarChart3, label: "板块分化度" },
  { to: "/backtest", icon: History, label: "回测验证" },
  { to: "/sentiment/weather", icon: Cloud, label: "情绪天气" },
  { to: "/workflow", icon: LineChart, label: "打板工作流" },
  { to: "/metrics", icon: BarChart3, label: "指标中心" },
  { to: "/health", icon: HeartPulse, label: "系统健康" },
  { to: "/scheduled-tasks", icon: Calendar, label: "定时任务" },
  { to: "/industry", icon: Building2, label: "行业分析" },
  { to: "/limitup", icon: Flame, label: "打板策略" },
  { to: "/settings", icon: Settings, label: "接入 AI" },
];

// 常看的板块，作为「板块中心」下的快捷入口（缩进显示）。
const SECTOR_LINKS = [
  { to: "/sectors/humanoid", icon: Cog, label: "人形机器人" },
  { to: "/sectors/ai-computing", icon: Cpu, label: "AI 算力" },
  { to: "/sectors/hbm", icon: Database, label: "HBM" },
  { to: "/sectors/cpo", icon: Cable, label: "光互联" },
  { to: "/sectors/business-space", icon: Rocket, label: "商业航天" },
  { to: "/sectors/ai-pharma", icon: FlaskConical, label: "生物医药" },
];

// 打板工作流快捷入口
const LIMITUP_LINKS = [
  { to: "/limitup/gene", icon: Dna, label: "基因筛选" },
  { to: "/limitup/auction", icon: Gavel, label: "竞价筛选" },
  { to: "/limitup/seats", icon: Car, label: "席位引擎" },
];

export function Layout() {
  const { pathname } = useLocation();
  const { dark, toggle } = useDarkMode();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("vr-sidebar") === "collapsed");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem("vr-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  // 移动端菜单锁定滚动
  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

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
          {!collapsed && <p className="mt-1 text-[11px] text-muted-foreground">个人 AI 投研系统 · A股/美股/港股</p>}
        </div>

        {/* Nav */}
        <nav className={cn("flex-1 space-y-1 overflow-auto", collapsed ? "p-1.5" : "p-2.5")} aria-label="主导航">
          {NAV.map(({ to, icon: Icon, label }) => {
            const active = pathname === to;
            return (
              <div key={to}>
                <Link
                  to={to}
                  title={collapsed ? label : undefined}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center rounded-lg text-sm transition-colors",
                    collapsed ? "justify-center p-2.5" : "gap-2.5 px-3 py-2.5",
                    active
                      ? "bg-primary/15 font-medium text-primary shadow-glow"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && label}
                </Link>

                 {/* 板块中心下方：常看板块的快捷入口（缩进） */}
                 {to === "/sectors" && (
                   <div className={cn("mt-1 space-y-0.5", !collapsed && "ml-4 border-l border-border/40 pl-1.5")}>
                     {SECTOR_LINKS.map(({ to: st, icon: SIcon, label: slabel }) => {
                       const sactive = pathname === st;
                       return (
                         <Link
                           key={st}
                           to={st}
                           title={collapsed ? slabel : undefined}
                           className={cn(
                             "flex items-center rounded-lg transition-colors",
                             collapsed ? "justify-center p-2" : "gap-2 px-2.5 py-1.5 text-[13px]",
                             sactive
                               ? "bg-primary/10 font-medium text-primary"
                               : "text-muted-foreground/80 hover:bg-muted/40 hover:text-foreground",
                           )}
                         >
                           <SIcon className="h-3.5 w-3.5 shrink-0" />
                           {!collapsed && slabel}
                         </Link>
                       );
                     })}
                   </div>
                 )}

                 {/* 打板工作流下方：快捷入口（缩进） */}
                 {to === "/limitup" && (
                   <div className={cn("mt-1 space-y-0.5", !collapsed && "ml-4 border-l border-border/40 pl-1.5")}>
                     {LIMITUP_LINKS.map(({ to: st, icon: SIcon, label: slabel }) => {
                       const sactive = pathname === st;
                       return (
                         <Link
                           key={st}
                           to={st}
                           title={collapsed ? slabel : undefined}
                           className={cn(
                             "flex items-center rounded-lg transition-colors",
                             collapsed ? "justify-center p-2" : "gap-2 px-2.5 py-1.5 text-[13px]",
                             sactive
                               ? "bg-primary/10 font-medium text-primary"
                               : "text-muted-foreground/80 hover:bg-muted/40 hover:text-foreground",
                           )}
                         >
                           <SIcon className="h-3.5 w-3.5 shrink-0" />
                           {!collapsed && slabel}
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
              <button onClick={toggle} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" aria-label={dark ? "切换到亮色" : "切换到暗色"} title={dark ? "亮色" : "暗色"}>
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
              <a href={SITE_URL} target="_blank" rel="noreferrer" className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" aria-label="联系作者" title="联系作者">
                <UserRound className="h-4 w-4" />
              </a>
              <button onClick={() => setCollapsed(false)} className="rounded p-1.5 text-muted-foreground transition-colors hover:text-foreground" aria-label="展开侧边栏" title="展开">
                <ChevronsRight className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <button onClick={toggle} className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground" aria-label={dark ? "切换到亮色" : "切换到暗色"}>
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                  {dark ? "亮色" : "暗色"}
                </button>
                <div className="flex items-center gap-2">
                  <a href={SITE_URL} target="_blank" rel="noreferrer" className="text-muted-foreground transition-colors hover:text-foreground" aria-label="联系作者" title="联系作者">
                    <UserRound className="h-3.5 w-3.5" />
                  </a>
                  <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-muted-foreground transition-colors hover:text-foreground" aria-label="GitHub 仓库" title="GitHub">
                    <Github className="h-3.5 w-3.5" />
                  </a>
                  <button onClick={() => setCollapsed(true)} className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground" aria-label="收起侧边栏" title="收起">
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <a href={SITE_URL} target="_blank" rel="noreferrer" className="block text-[11px] text-primary/80 transition-colors hover:text-primary">
                联系作者 · simonlin.net
              </a>
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

        {/* Mobile Backdrop */}
        {mobileMenuOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
            onClick={() => setMobileMenuOpen(false)}
            aria-hidden="true"
          />
        )}

        {/* Primary Tab Bar - Mobile only */}
        <div className="border-b border-border/40 bg-background/60 backdrop-blur-sm md:hidden">
          <div className="mx-auto max-w-6xl px-4">
            <div className="flex items-center gap-1 overflow-x-auto py-2" role="tablist">
              {NAV.map(({ to, label }) => {
                const isActive = pathname === to;
                return (
                  <Link
                    key={to}
                    to={to}
                    onClick={() => setMobileMenuOpen(false)}
                    className={cn(
                      "relative whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-medium transition-all",
                      isActive
                        ? "text-primary"
                        : "text-muted-foreground/60 hover:text-foreground hover:bg-muted/30",
                    )}
                    aria-current={isActive ? "page" : undefined}
                  >
                    {isActive && (
                      <span
                        className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-primary"
                        style={{ boxShadow: "0 0 8px hsl(var(--primary) / 0.5)" }}
                      />
                    )}
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        </div>

        <div className="mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
