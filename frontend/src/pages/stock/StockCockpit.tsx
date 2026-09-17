// S179 Phase 1: 个股 cockpit 页——SplitLayout（左图表中心 + 右侧面板 8 图标 toggle）
// + currentStock 联动（Bloomberg linking）。替代 StockDeep 纵向堆叠范式。
// 无 code：currentStock.browsedAt fallback 或 HonestEmptyState「请先选股」（grill #13）。
// 8 图标面板内容 deferred（Phase 2 接线）；图表中心复用 useStockDeep 12 源聚合。
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { SplitLayout } from "@/components/layout/SplitLayout";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { GlassCard } from "@/components/ui/GlassCard";
import { ErrorState, PageSkeleton } from "@/components/ui/State";
import { KLineChart } from "@/components/charts/KLineChart";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { StrategySignalsView } from "@/components/stock/StrategySignalsView";
import { NewsPanel } from "@/components/stock/NewsPanel";
import { FinancialsPanel } from "@/components/stock/FinancialsPanel";
import { FundFlowPanel } from "@/components/stock/FundFlowPanel";
import { TechScoreCard } from "@/components/stock/TechScoreCard";
import { useCurrentStock, useSelectStock } from "@/stores/currentStock";
import { useStockDeep } from "@/lib/query/stock";
import type { Quote, StockDeep as StockDeepData } from "@/lib/api";
import { api } from "@/lib/api";
import { cn, pctColor } from "@/lib/utils";
import { RightPanel, type PanelKey } from "./RightPanel";
import { StockSeatCard } from "@/components/seat/StockSeatCard";

// ─── 格式化（A 股红涨绿跌，复用 StockDeep 范式）──────────────────────────

const fmtPrice = (v: number | null | undefined): string =>
  v == null ? "—" : v.toFixed(2);

const fmtPct = (v: number | null | undefined): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

// ─── 基本信息卡 ──────────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="font-mono text-sm">{value}</p>
    </div>
  );
}

function BasicInfoCard({ quote }: { quote: Quote | null }) {
  if (!quote) {
    return (
      <GlassCard className="p-4">
        <p className="py-3 text-center text-sm text-muted-foreground">
          暂无行情数据
        </p>
      </GlassCard>
    );
  }
  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-baseline gap-3">
        <span className="text-2xl font-bold font-mono">
          {fmtPrice(quote.price)}
        </span>
        <span className={cn("text-sm font-mono", pctColor(quote.change_pct))}>
          {fmtPct(quote.change_pct)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-x-4 gap-y-2">
        <Metric label="昨收" value={fmtPrice(quote.last_close)} />
        <Metric label="PE(TTM)" value={fmtPrice(quote.pe_ttm)} />
        <Metric label="PB" value={fmtPrice(quote.pb)} />
        <Metric
          label="换手率"
          value={
            quote.turnover_pct != null
              ? `${quote.turnover_pct.toFixed(2)}%`
              : "—"
          }
        />
        <Metric label="涨停价" value={fmtPrice(quote.limit_up_price)} />
        <Metric label="跌停价" value={fmtPrice(quote.limit_down_price)} />
      </div>
    </GlassCard>
  );
}

// ─── 信号区（主区，战法匹配）─────────────────────────────────────────────

function SignalArea({ code, date }: { code: string; date: string }) {
  return (
    <GlassCard className="p-4">
      <h3 className="mb-3 text-sm font-semibold">信号区</h3>
      <StrategySignalsView code={code} date={date} variant="full" />
    </GlassCard>
  );
}

// ─── 图表中心（SplitLayout 左栏）──────────────────────────────────────────

// ─── K 线卡片（多时间维度切换：日K/周K/月K/60min）──────────────────────────
const KLINE_DIMS = [
  { c: 1, label: "5min", src: "baostock 5min" },
  { c: 15, label: "15min", src: "5min 聚合" },
  { c: 30, label: "30min", src: "5min 聚合" },
  { c: 11, label: "60min", src: "5min 聚合" },
  { c: 4, label: "日K", src: "baostock回退" },
  { c: 5, label: "周K", src: "日K resample" },
  { c: 6, label: "月K", src: "日K resample" },
];

/** 日K → 周K(5)/月K(6) resample（前端纯函数，仿后端 _resample_daily_to_period）。
 * 周K 按所在周周一分组，月K 按 year-month。open=首/high=max/low=min/close=末/volume=sum。不臆造。 */
function resampleDailyToPeriod(daily: any[], category: number): any[] {
  if (!daily.length) return [];
  const groups = new Map<string, any[]>();
  for (const b of daily) {
    const d: string = b?.date ?? "";
    const parts = d.split("-");
    if (parts.length < 3) continue;
    const y = +parts[0], m = +parts[1], dd = +parts[2];
    let key: string;
    if (category === 5) {
      const dt = new Date(Date.UTC(y, m - 1, dd));
      const dow = dt.getUTCDay() || 7;
      const mon = new Date(dt);
      mon.setUTCDate(dt.getUTCDate() - dow + 1);
      key = mon.toISOString().slice(0, 10);
    } else {
      key = `${y}-${String(m).padStart(2, "0")}`;
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(b);
  }
  const out: any[] = [];
  for (const grp of groups.values()) {
    if (!grp.length) continue;
    const highs = grp.map((r) => r.high).filter((v) => v != null);
    const lows = grp.map((r) => r.low).filter((v) => v != null);
    const vols = grp.map((r) => r.volume).filter((v) => v != null);
    out.push({
      date: grp[grp.length - 1].date,
      open: grp[0].open,
      high: highs.length ? Math.max(...highs) : null,
      low: lows.length ? Math.min(...lows) : null,
      close: grp[grp.length - 1].close,
      volume: vols.length ? vols.reduce((a: number, b: number) => a + b, 0) : null,
      amount: null,
    });
  }
  return out;
}

/** 5min bars → 15/30/60min 聚合（前端纯函数，仿后端 _aggregate_5min_to_period）。
 * 按 timestamp floor 到 period_min 窗口分组。open=首/high=max/low=min/close=末/volume=sum。
 * 5min 直接返（已含 timestamp）。不臆造。 */
const _MIN_SPAN: Record<number, number> = { 1: 5, 15: 15, 30: 30, 11: 60 };
function aggregate5minToPeriod(bars5min: any[], category: number): any[] {
  if (!bars5min.length) return [];
  const periodMin = _MIN_SPAN[category] ?? 5;
  if (periodMin === 5) return bars5min; // 5min 直接返
  const periodMs = periodMin * 60 * 1000;
  const groups = new Map<number, any[]>();
  for (const b of bars5min) {
    const ts = b.timestamp ?? 0;
    if (!ts) continue;
    const key = Math.floor(ts / periodMs) * periodMs;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(b);
  }
  const out: any[] = [];
  for (const [key, grp] of groups) {
    if (!grp.length) continue;
    const highs = grp.map((r) => r.high).filter((v) => v != null);
    const lows = grp.map((r) => r.low).filter((v) => v != null);
    const vols = grp.map((r) => r.volume).filter((v) => v != null);
    out.push({
      date: grp[0].date,
      timestamp: key,
      open: grp[0].open,
      high: highs.length ? Math.max(...highs) : null,
      low: lows.length ? Math.min(...lows) : null,
      close: grp[grp.length - 1].close,
      volume: vols.length ? vols.reduce((a: number, b: number) => a + b, 0) : null,
    });
  }
  return out;
}

function KlineCard({ code, initialBars }: { code: string; initialBars: any[] }) {
  const [category, setCategory] = useState(4);
  const [bars, setBars] = useState<any[]>(initialBars);
  const [loading, setLoading] = useState(false);
  const [showMA, setShowMA] = useState(true);

  useEffect(() => {
    if (category === 4) {
      setBars(initialBars);
      return;
    }
    // 周/月K 前端从日K resample（秒出，不 fetch——避免 /api/kline 多源串行 60s 超时）
    if (category === 5 || category === 6) {
      setBars(resampleDailyToPeriod(initialBars, category));
      return;
    }
    // 分钟K（1/15/30/11）: fetch 5min 一次，15/30/60 前端聚合（避免 baostock 多次 login/logout 在线程池串调失败）
    if ([1, 15, 30, 11].includes(category)) {
      let cancelled = false;
      setLoading(true);
      api
        .kline(code, 1, 1)  // 永远 fetch 5min（category=1），前端聚合到 15/30/60
        .then((r) => {
          if (!cancelled) {
            const bars5min = Array.isArray(r) ? r : [];
            setBars(aggregate5minToPeriod(bars5min, category));
          }
        })
        .catch(() => { if (!cancelled) setBars([]); })
        .finally(() => { if (!cancelled) setLoading(false); });
      return () => { cancelled = true; };
    }
  }, [code, category, initialBars]);

  const dim = KLINE_DIMS.find((d) => d.c === category) ?? KLINE_DIMS[0];
  return (
    <GlassCard className="p-4">
      {/* 头部：标题 + 维度 segmented control + MA toggle */}
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h3 className="text-sm font-semibold">K 线图</h3>
          {/* 信息密度：当前维度 + bars 数 + 数据源 */}
          <span className="text-[10px] text-muted-foreground">
            {dim.label} · {bars.length} 根 · {dim.src}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* MA 显隐 toggle */}
          <button
            type="button"
            onClick={() => setShowMA((v) => !v)}
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] transition-colors",
              showMA ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted/40",
            )}
            title="MA5/MA10/MA20 均线显隐"
          >
            MA
          </button>
          {/* 维度 segmented control（一体感） */}
          <div className="flex rounded-md border border-border/60 bg-muted/10 p-0.5">
            {KLINE_DIMS.map((d) => (
              <button
                key={d.c}
                type="button"
                onClick={() => setCategory(d.c)}
                className={cn(
                  "rounded px-2 py-0.5 text-[11px] transition-colors",
                  category === d.c
                    ? "bg-primary/15 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {/* 图区 */}
      {loading ? (
        <div className="flex h-[400px] items-center justify-center">
          {/* skeleton 骨架屏（非纯文字） */}
          <div className="w-full space-y-2 px-2">
            <div className="h-4 w-3/4 animate-pulse rounded bg-muted/40" />
            <div className="h-[300px] w-full animate-pulse rounded bg-muted/20" />
            <div className="h-4 w-1/2 animate-pulse rounded bg-muted/40" />
          </div>
        </div>
      ) : bars.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center">
          {/* empty honest：标根因非空白 */}
          <div className="text-center text-xs text-muted-foreground">
            <p className="font-medium">{dim.label} 暂无数据</p>
            <p className="mt-1 text-[10px]">
              {dim.c === 11
                ? "mootdx intraday 故障 + baostock 无 60min 分时——需 mootdx 修复或换分时源"
                : "数据源未取到，可能是非交易时段或端点未通"}
            </p>
          </div>
        </div>
      ) : (
        <KLineChart bars={bars} height={420} showMA={showMA} category={category} />
      )}
    </GlassCard>
  );
}

function ChartCenter({ code, data, date, activePanel }: { code: string; data: StockDeepData; date: string; activePanel: PanelKey | null }) {
  const quote = data.quote;
  const name = quote?.name ?? "";
  // 主区 panel slot：点右侧图标 → 主区这里渲染对应 panel（宽敞，非右侧窄栏）。
  // signals/null=信号区（默认）；dragonTiger=指针（下方席位卡）；其余 tab=对应 panel 或 stub。
  const slot =
    activePanel === "news" ? (
      <GlassCard className="p-4">
        <h3 className="mb-3 text-sm font-semibold">资讯</h3>
        <NewsPanel code={code} />
      </GlassCard>
    ) : activePanel === "financials" ? (
      <GlassCard className="p-4">
        <h3 className="mb-3 text-sm font-semibold">财务</h3>
        <FinancialsPanel code={code} />
      </GlassCard>
    ) : activePanel === "fundflow" ? (
      <GlassCard className="p-4">
        <h3 className="mb-3 text-sm font-semibold">资金</h3>
        <FundFlowPanel code={code} />
      </GlassCard>
    ) : activePanel === "techScore" ? (
      <TechScoreCard code={code} />
    ) : activePanel === "watchlist" || activePanel === "notes" || activePanel === "ai" ? (
      <GlassCard className="p-4">
        <HonestEmptyState
          message={`「${activePanel === "watchlist" ? "自选" : activePanel === "notes" ? "笔记" : "AI 问答"}」面板·待接线`}
          hint="Phase 2 接线，点右侧其他图标切换"
        />
      </GlassCard>
    ) : activePanel === "dragonTiger" ? (
      <GlassCard className="p-4">
        <p className="py-2 text-xs text-muted-foreground">
          龙虎榜已在下方「席位活动」卡片展示，向下滚动查看
        </p>
      </GlassCard>
    ) : (
      <SignalArea code={code} date={date} />
    );
  return (
    <div className="space-y-4 p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold tracking-tight">{code}</h2>
        {name && (
          <span className="text-base text-muted-foreground">{name}</span>
        )}
      </div>
      <KlineCard code={code} initialBars={data.kline ?? []} />
      <BasicInfoCard quote={quote} />
      {slot}
      {/* M1 per-stock 席位活动：龙虎榜记录 + 买卖席位 + 机构净额（cross-cutting 席位 view） */}
      <StockSeatCard dragonTiger={data.dragon_tiger ?? null} code={code} />
      <Disclaimer compact />
    </div>
  );
}

// ─── SplitLayout 高度容器 ────────────────────────────────────────────────
// Layout 的 Outlet 包裹层（mx-auto max-w-6xl px-6 py-6）是 auto 高度，
// SplitLayout 的 h-full 无确定参照。用 viewport 相对高度 + min-h 保底。
const COCKPIT_HEIGHT = "h-[calc(100vh-10rem)] min-h-[480px]";

// ─── 页面 ─────────────────────────────────────────────────────────────────

export function StockCockpit() {
  const { code: urlCode } = useParams<{ code: string }>();
  const { code: curCode, browsedAt } = useCurrentStock();
  const selectStock = useSelectStock();

  // 解析有效 code：URL param > currentStock.code > browsedAt[0]（grill #13 fallback）
  const code = urlCode || curCode || browsedAt[0] || null;

  // Bloomberg linking：URL code 同步进 currentStock（侧边栏/其他页联动）
  // 只同步 code（name 由 API quote.name 取，不从 store 读，避免 deep-link 旧 name 污染）
  useEffect(() => {
    if (urlCode && urlCode !== curCode) {
      selectStock(urlCode);
    }
  }, [urlCode, curCode, selectStock]);

  // 无 code：EmptyState「请先选股」
  if (!code) {
    return (
      <div className={cn("flex items-center justify-center p-6", COCKPIT_HEIGHT)}>
        <HonestEmptyState
          message="请先选股"
          hint="从选股页 / 自选列表 / 盘中看板选择一只股票后进入"
          className="max-w-sm"
        />
      </div>
    );
  }

  return <StockCockpitContent code={code} />;
}

/**
 * StockCockpitContent — 有确定 code 的 cockpit 主体（独立组件避免条件 hook）。
 * useStockDeep 在此调用（code 非 null 保证），父组件 StockCockpit 处理无 code 空态。
 */
function StockCockpitContent({ code }: { code: string }) {
  const { data, isLoading, error, refetch } = useStockDeep(code);
  // 页面级日期：默认今日（北京时区）；影响信号区战法匹配。
  const [date, setDate] = useState(() => {
    const d = new Date(Date.now() + 8 * 3600 * 1000);
    return d.toISOString().slice(0, 10);
  });
  // 默认日期填上一个有K线的交易日（deep kline 最后 bar date）——今日可能盘前/非交易日无数据
  const dateInitedRef = useRef(false);
  useEffect(() => {
    if (data?.kline?.length && !dateInitedRef.current) {
      dateInitedRef.current = true;
      setDate(data.kline[data.kline.length - 1].date);
    }
  }, [data]);
  // 活跃 panel：点右侧图标 → 主区渲染对应 panel。null=信号区（默认）。
  const [activePanel, setActivePanel] = useState<PanelKey | null>(null);

  if (isLoading) return <PageSkeleton />;
  if (error) {
    return (
      <ErrorState
        message={`加载失败：${error instanceof Error ? error.message : "未知错误"}`}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) {
    return <ErrorState message="未取到数据" onRetry={() => refetch()} />;
  }

  return (
    <div className={cn(COCKPIT_HEIGHT, "flex flex-col")}>
      <div className="flex flex-none items-center gap-2 border-b border-border/40 bg-muted/10 px-4 py-2">
        <span className="text-xs font-medium text-muted-foreground">观测日期</span>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded border border-border/60 bg-background px-2 py-1 text-xs text-foreground"
        />
        <span className="text-[10px] text-muted-foreground">
          默认今日；影响下方「信号区」战法匹配
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <SplitLayout
          left={<ChartCenter code={code} data={data} date={date} activePanel={activePanel} />}
          right={<RightPanel active={activePanel} onActiveChange={setActivePanel} />}
          storageKey="vr-stock-cockpit-chart"
          defaultWidth={880}
          minLeft={480}
          maxLeft={1280}
        />
      </div>
    </div>
  );
}

export default StockCockpit;
