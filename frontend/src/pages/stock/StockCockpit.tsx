// S179 Phase 1: 个股 cockpit 页——SplitLayout（左图表中心 + 右侧面板 8 图标 toggle）
// + currentStock 联动（Bloomberg linking）。替代 StockDeep 纵向堆叠范式。
// 无 code：currentStock.browsedAt fallback 或 HonestEmptyState「请先选股」（grill #13）。
// 8 图标面板内容 deferred（Phase 2 接线）；图表中心复用 useStockDeep 12 源聚合。
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { SplitLayout } from "@/components/layout/SplitLayout";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { GlassCard } from "@/components/ui/GlassCard";
import { ErrorState, PageSkeleton } from "@/components/ui/State";
import { KLineChart } from "@/components/charts/KLineChart";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useCurrentStock, useSelectStock } from "@/stores/currentStock";
import { useStockDeep } from "@/lib/query/stock";
import type { Quote, StockDeep as StockDeepData } from "@/lib/api";
import { cn, pctColor } from "@/lib/utils";
import { RightPanel } from "./RightPanel";
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
        <p className="py-3 text-center text-sm text-muted-foreground/60">
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

// ─── 信号区 stub ─────────────────────────────────────────────────────────

function SignalArea({ code }: { code: string }) {
  return (
    <GlassCard className="p-4">
      <h3 className="mb-2 text-sm font-semibold">信号区</h3>
      <HonestEmptyState
        message="信号面板·Phase 2 接线"
        hint={
          <span>
            策略信号{" "}
            <code className="font-mono">/api/strategy/signals/{code}</code>{" "}
            待接入
          </span>
        }
      />
    </GlassCard>
  );
}

// ─── 图表中心（SplitLayout 左栏）──────────────────────────────────────────

function ChartCenter({ code, data }: { code: string; data: StockDeepData }) {
  const quote = data.quote;
  const name = quote?.name ?? "";
  return (
    <div className="space-y-4 p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xl font-bold tracking-tight">{code}</h2>
        {name && (
          <span className="text-base text-muted-foreground">{name}</span>
        )}
      </div>
      <GlassCard className="p-4">
        <h3 className="mb-3 text-sm font-semibold">K 线图</h3>
        <KLineChart bars={data.kline ?? []} height={420} />
      </GlassCard>
      <BasicInfoCard quote={quote} />
      <SignalArea code={code} />
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
    <div className={COCKPIT_HEIGHT}>
      <SplitLayout
        left={<ChartCenter code={code} data={data} />}
        right={<RightPanel code={code} />}
        storageKey="vr-stock-cockpit-chart"
        defaultWidth={880}
        minLeft={480}
        maxLeft={1280}
      />
    </div>
  );
}

export default StockCockpit;
