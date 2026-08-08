// S039: 个股深度页——消费 GET /stock/{code}/deep（12 源聚合），渲染核心四块：
// 行情摘要(quote) / K 线图(kline) / 资金流(fund_flow) / 财务速览(financials+valuation+percentile)。
// 后端已实现（routers/stock_data.py:213），本页纯前端接线，后端零改动。
// 各块字段 null 时显示「暂无数据」占位（_safe_call 单源失败是正常降级），不崩溃。
// 合规：只客观呈现行情/K线/财务/资金流，无方向性研判；底部保留 Disclaimer。
import { useParams } from "react-router-dom";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { ErrorState, PageSkeleton } from "@/components/ui/State";
import { KLineChart } from "@/components/charts/KLineChart";
import { EarningsSnapshot } from "@/components/ui/EarningsSnapshot";
import { useStockDeep } from "@/lib/query";
import type { FundFlowRow, Quote, Valuation, Financials, ValPercentile } from "@/lib/api";

// ─── 格式化（A 股红涨绿跌口径）──────────────────────────────────────────

const fmtPrice = (v: number | null | undefined): string =>
  v == null ? "—" : v.toFixed(2);

const fmtPct = (v: number | null | undefined): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

// 资金额元 → 万元（主力净流入常用单位）
const fmtWan = (yuan: number | null | undefined): string => {
  if (yuan == null) return "—";
  return (yuan / 10000).toFixed(0);
};

const pctColor = (v: number | null | undefined): string =>
  v == null ? "text-muted-foreground" : v >= 0 ? "text-danger" : "text-success";

// ─── 子块 ────────────────────────────────────────────────────────────────

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-mono">{value}</p>
    </div>
  );
}

function EmptyBlock({ text }: { text: string }) {
  return (
    <GlassCard className="p-6">
      <p className="text-center text-sm text-muted-foreground/60">{text}</p>
    </GlassCard>
  );
}

function QuoteSummary({ quote }: { quote: Quote | null }) {
  if (!quote) return <EmptyBlock text="暂无行情数据" />;
  return (
    <GlassCard className="p-4">
      <h3 className="mb-3 text-sm font-semibold">行情摘要</h3>
      <div className="mb-4 flex items-baseline gap-3">
        <span className="text-2xl font-bold font-mono">{fmtPrice(quote.price)}</span>
        <span className={`text-sm font-mono ${pctColor(quote.change_pct)}`}>
          {fmtPct(quote.change_pct)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <Metric label="市盈率(TTM)" value={fmtPrice(quote.pe_ttm)} />
        <Metric label="市净率" value={fmtPrice(quote.pb)} />
        <Metric
          label="换手率"
          value={quote.turnover_rate != null ? `${quote.turnover_rate.toFixed(2)}%` : "—"}
        />
        <Metric label="涨停价" value={fmtPrice(quote.limit_up_price)} />
        <Metric label="跌停价" value={fmtPrice(quote.limit_down_price)} />
        <Metric label="昨收" value={fmtPrice(quote.last_close)} />
      </div>
    </GlassCard>
  );
}

function FinancialsBlock({
  val,
  fin,
  pctl,
}: {
  val: Valuation | null;
  fin: Financials | null;
  pctl: ValPercentile | null;
}) {
  // EarningsSnapshot 要求 val 非空且 fin 有营收/净利润才渲染，否则占位
  if (!val || !fin || (!fin.revenue && !fin.net_profit)) {
    return <EmptyBlock text="暂无财务数据" />;
  }
  return <EarningsSnapshot val={val} fin={fin} pctl={pctl} />;
}

function FundFlowTable({ rows }: { rows: FundFlowRow[] | null }) {
  if (!rows || rows.length === 0) return <EmptyBlock text="暂无资金流数据" />;
  // 最近 30 日，新在上
  const recent = rows.slice(-30).reverse();
  const cell = (v: number | null) => (
    <td className={`px-2 py-2 font-mono ${pctColor(v)}`}>{fmtWan(v)}</td>
  );
  return (
    <GlassCard className="p-4">
      <h3 className="mb-3 text-sm font-semibold">资金流向</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
              <th className="px-2 py-2">日期</th>
              <th className="px-2 py-2">主力净流入</th>
              <th className="px-2 py-2">超大单</th>
              <th className="px-2 py-2">大单</th>
              <th className="px-2 py-2">中单</th>
              <th className="px-2 py-2">小单</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((r) => (
              <tr key={r.date} className="border-b border-border/30">
                <td className="px-2 py-2 font-mono text-xs">{r.date}</td>
                {cell(r.main_net)}
                {cell(r.super_net)}
                {cell(r.large_net)}
                {cell(r.mid_net)}
                {cell(r.small_net)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground/50">单位：万元（红=净流入，绿=净流出）</p>
    </GlassCard>
  );
}

// ─── 页面 ─────────────────────────────────────────────────────────────────

export function StockDeep() {
  const { code } = useParams<{ code: string }>();
  const { data, isLoading, error, refetch } = useStockDeep(code ?? "");

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

  const quote = data.quote;
  const name = quote?.name ?? "";

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${code ?? ""} ${name}`}
        subtitle="个股深度"
        actions={
          quote ? (
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold font-mono">{fmtPrice(quote.price)}</span>
              <span className={`text-sm font-mono ${pctColor(quote.change_pct)}`}>
                {fmtPct(quote.change_pct)}
              </span>
            </div>
          ) : undefined
        }
      />

      <GlassCard className="p-4">
        <h3 className="mb-3 text-sm font-semibold">K 线图</h3>
        <KLineChart bars={data.kline ?? []} height={420} />
      </GlassCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <QuoteSummary quote={quote} />
        <FinancialsBlock val={data.valuation} fin={data.financials} pctl={data.percentile} />
      </div>

      <FundFlowTable rows={data.fund_flow} />

      <Disclaimer />
    </div>
  );
}

export default StockDeep;
