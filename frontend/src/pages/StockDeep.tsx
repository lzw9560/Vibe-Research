import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, TrendingUp, Dna, Banknote, Brain, Loader2, AlertCircle } from "lucide-react";
import { api, type StockDeep, type ValMetric } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { TabBar } from "@/components/ui/TabBar";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { KLineChart } from "@/components/charts/KLineChart";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { useBreadcrumbs } from "@/components/ui/BreadcrumbContext";
import { cn } from "@/lib/utils";

// --- Tab definitions ---
type TabKey = "quote" | "gene" | "fund" | "ai";
const TABS: { key: TabKey; label: string; icon: typeof TrendingUp }[] = [
  { key: "quote", label: "行情", icon: TrendingUp },
  { key: "gene", label: "基因", icon: Dna },
  { key: "fund", label: "资金", icon: Banknote },
  { key: "ai", label: "AI", icon: Brain },
];

// --- Helpers ---
const fmt = (v: number | null | undefined, suffix = "") =>
  v === null || v === undefined ? "—" : `${v}${suffix}`;

const pctColor = (p: number | null | undefined) =>
  p != null && p > 0 ? "text-danger" : p != null && p < 0 ? "text-success" : "text-muted-foreground";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined || !Number.isFinite(Number(v)) ? "—" : `${Number(v).toFixed(2)}%`;

/** Strip leading issuer prefix like "东方财富:公告标题" */
const stripTitle = (t: string) => t.replace(/^[^:：]*[:：]/, "");

// Factor bar for GeneTab
function FactorBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pctVal = max > 0 ? Math.abs(value) / max : 0;
  const positive = value >= 0;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 shrink-0 text-muted-foreground">{label}</span>
      <div className="flex-1 h-3 overflow-hidden rounded bg-muted/40">
        <div
          className={cn("h-full rounded transition-all", positive ? "bg-danger" : "bg-success")}
          style={{ width: `${Math.min(100, pctVal * 100)}%`, marginLeft: positive ? "50%" : `${50 - pctVal * 50}%` }}
        />
      </div>
      <span className={cn("w-14 shrink-0 text-right font-mono", positive ? "text-danger" : "text-success")}>{fmt(value)}</span>
    </div>
  );
}

// --- Tab components ---

function QuoteTab({ data, code }: { data: StockDeep | null; code: string }) {
  const q = data?.quote;
  const kline = data?.kline;
  const val = data?.valuation;
  const pctVal = data?.percentile;
  const fin = data?.financials;

  return (
    <div className="space-y-5">
      {/* Price header */}
      {q && (
        <div className="flex flex-wrap items-baseline gap-3">
          <div>
            <span className="text-2xl font-bold">{q.name}</span>
            <span className="ml-2 font-mono text-sm text-muted-foreground">{code}</span>
          </div>
          <span className={cn("text-3xl font-bold font-mono", pctColor(q.change_pct))}>
            {fmt(q.price)}
          </span>
          <span className={cn("font-mono text-sm", pctColor(q.change_pct))}>
            {q.change_pct != null ? `${q.change_pct > 0 ? "+" : ""}${q.change_pct}%` : "—"}
          </span>
        </div>
      )}

      {/* Price summary grid */}
      {q && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label="昨收" value={fmt(q.last_close)} />
          <MetricCard label="涨停" value={fmt(q.limit_up_price)} trendUp={true} />
          <MetricCard label="跌停" value={fmt(q.limit_down_price)} trendUp={false} />
          <MetricCard label="换手率" value={pct(q.turnover_rate)} />
        </div>
      )}

      {/* KLineChart */}
      {kline && kline.length > 0 ? (
        <GlassCard>
          <SectionHeader title="K线图" icon={<TrendingUp className="h-4 w-4 text-primary" />} />
          <KLineChart bars={kline} />
        </GlassCard>
      ) : (
        <GlassCard>
          <SectionHeader title="K线图" icon={<TrendingUp className="h-4 w-4 text-primary" />} />
          <p className="py-8 text-center text-sm text-muted-foreground">暂无K线数据</p>
        </GlassCard>
      )}

      {/* Valuation */}
      {val && (
        <GlassCard>
          <SectionHeader title="估值指标" icon={<TrendingUp className="h-4 w-4 text-primary" />} />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard label="PE(TTM)" value={fmt(val.pe_ttm)} />
            <MetricCard label="PB" value={fmt(val.pb)} />
            <MetricCard label="总市值" value={fmt(val.mcap_yi)} unit="亿" />
            <MetricCard label="EPS(26E)" value={fmt(val.eps_26e)} />
            <MetricCard label="前向PE" value={fmt(val.pe_26e)} />
            <MetricCard label="PEG" value={fmt(val.peg)} />
            <MetricCard label="消化年" value={fmt(val.digest_years)} unit="年" />
            <MetricCard label="机构覆盖" value={fmt(val.analyst_count)} unit="家" />
          </div>
        </GlassCard>
      )}

      {/* Valuation percentile band */}
      {pctVal && (pctVal.metrics.pe_ttm || pctVal.metrics.pb) && (
        <GlassCard>
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">估值历史分位 · {pctVal.period}</h3>
          <div className="space-y-4">
            {pctVal.metrics.pe_ttm && <ValBand label="PE-TTM" m={pctVal.metrics.pe_ttm} />}
            {pctVal.metrics.pb && <ValBand label="市净率 PB" m={pctVal.metrics.pb} />}
          </div>
        </GlassCard>
      )}


      {/* Financials */}
      {fin && (fin.revenue || fin.roe) && (
        <GlassCard>
          <SectionHeader title="财务关键指标" subtitle={fin.period ? `· ${fin.period}` : undefined} />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard label="营收" value={fin.revenue || "—"} sub={fin.revenue_yoy ? `同比 ${fin.revenue_yoy}` : undefined} />
            <MetricCard label="净利润" value={fin.net_profit || "—"} sub={fin.net_profit_yoy ? `同比 ${fin.net_profit_yoy}` : undefined} />
            <MetricCard label="EPS" value={fin.eps || "—"} />
            <MetricCard label="ROE" value={fin.roe || "—"} />
            <MetricCard label="毛利率" value={fin.gross_margin || "—"} />
            <MetricCard label="净利率" value={fin.net_margin || "—"} />
            <MetricCard label="每股净资产" value={fin.bvps || "—"} />
            <MetricCard label="每股经营现金流" value={fin.op_cf_ps || "—"} />
          </div>
        </GlassCard>
      )}

      {/* Reports */}
      {data?.reports && data.reports.length > 0 && (
        <GlassCard>
          <SectionHeader title={`近期研报（${data.reports.length}）`} />
          <div className="space-y-2">
            {data.reports.slice(0, 12).map((r, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-sm last:border-0">
                <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">{(r.publishDate || "").slice(0, 10)}</span>
                <span className="w-24 shrink-0 truncate text-xs text-muted-foreground">{r.orgSName}</span>
                <span className="flex-1 truncate">{r.title}</span>
                {r.emRatingName && <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{r.emRatingName}</span>}
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Announcements */}
      {data?.announcements && data.announcements.length > 0 && (
        <GlassCard>
          <SectionHeader title={`近期公告（${data.announcements.length}）`} />
          <div className="space-y-2">
            {data.announcements.slice(0, 12).map((a, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-sm last:border-0">
                <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">{a.date}</span>
                {a.type && <span className="w-24 shrink-0 truncate text-xs text-muted-foreground">{a.type}</span>}
                <span className="flex-1 truncate">{stripTitle(a.title)}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function GeneTab({ data }: { data: StockDeep | null }) {
  const lu = data?.limitup;
  const gene = lu?.gene_score;
  const strat = lu?.strategy_logic;
  const risks = lu?.risk_rules;

  if (!gene) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        暂无基因评分数据
      </div>
    );
  }

   return (
     <div className="space-y-5">
       {/* Score overview */}
       <GlassCard>
         <SectionHeader title="基因评分" icon={<Dna className="h-4 w-4 text-primary" />} />
         <div className="mb-4 flex items-center gap-6">
           <div className="text-center">
             <div className={cn("text-4xl font-bold font-mono", gene.total_score >= 60 ? "text-danger" : gene.total_score >= 40 ? "text-warning" : "text-muted-foreground")}>
               {gene.total_score}
             </div>
             <p className="mt-1 text-xs text-muted-foreground">总分 (0-100)</p>
           </div>
           <div className="flex-1 space-y-3">
             <div className="flex items-center gap-2 text-xs">
               <span className="w-16 text-muted-foreground">Qualify</span>
               <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", gene.qualify ? "bg-success/20 text-success" : "bg-muted/40 text-muted-foreground")}>
                 {gene.qualify ? "达标" : "未达标"}
               </span>
             </div>
             <div className="flex items-center gap-2 text-xs">
               <span className="w-16 text-muted-foreground">High Gene</span>
               <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", gene.high_gene ? "bg-danger/20 text-danger" : "bg-muted/40 text-muted-foreground")}>
                 {gene.high_gene ? "高基因" : "普通"}
               </span>
             </div>
             <div className="flex items-center gap-2 text-xs">
               <span className="w-16 text-muted-foreground">Wilson分</span>
               <span className="font-mono">{fmt(gene.wilson_adjusted)}</span>
             </div>
             <div className="flex items-center gap-2 text-xs">
               <span className="w-16 text-muted-foreground">250日涨停</span>
               <span className="font-mono">{gene.zt_count_250d} 次</span>
             </div>
           </div>
         </div>

         {/* Factors */}
         {Object.keys(gene.factors || {}).length > 0 && (
           <div className="space-y-2">
             <p className="text-xs font-medium text-muted-foreground">五维因子</p>
             {Object.entries(gene.factors).map(([k, v]) => (
               <FactorBar key={k} label={k} value={v} max={100} />
             ))}
           </div>
         )}
       </GlassCard>

       {/* Strategy logic matches */}
       {strat && strat.matches && strat.matches.length > 0 && (
         <GlassCard>
           <SectionHeader title="策略逻辑匹配" />
           <p className="mb-3 text-xs text-muted-foreground">{strat.logic_description}</p>
           <div className="space-y-2">
             {strat.matches.map((m, i) => (
               <div key={i} className="flex items-center gap-3 rounded-md bg-muted/20 p-2 text-xs">
                 <span className="shrink-0 font-medium text-primary">{m.condition}</span>
                 <span className="font-mono text-muted-foreground">{m.value}</span>
                 <span className="flex-1 text-muted-foreground">{m.description}</span>
               </div>
             ))}
           </div>
         </GlassCard>
       )}

        {/* Risk rules */}
        {risks && risks.length > 0 && (
          <GlassCard>
            <SectionHeader title="风控规则" />
            <div className="space-y-2">
              {risks.map((r, i) => (
                <div key={i} className="rounded-md bg-muted/20 p-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-warning">{r.rule_name}</span>
                    {r.configurable && <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">可配置</span>}
                  </div>
                  <p className="mt-1 text-muted-foreground">{r.description}</p>
                  <p className="mt-1 text-muted-foreground/70">示例：{r.example}</p>
                </div>
              ))}
            </div>
          </GlassCard>
        )}

      {/* Backtest mini */}
      {gene.backtest_summary && (
        <GlassCard>
          <SectionHeader title="回测摘要" />
          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="样本数" value={fmt(gene.backtest_summary.samples)} />
            <MetricCard label="连板率" value={pct(gene.backtest_summary.lianban_rate)} />
            <MetricCard label="连板均分" value={fmt(gene.backtest_summary.avg_score_lianban)} />
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function FundTab({ data }: { data: StockDeep | null }) {
  const fundFlow = data?.fund_flow;
  const dt = data?.dragon_tiger;
  const blocks = data?.blocks;
  const hotCon = data?.hot_concepts;

  return (
    <div className="space-y-5">
      {/* Fund flow table */}
      {fundFlow && fundFlow.length > 0 ? (
        <GlassCard>
          <SectionHeader title="主力资金流向" icon={<Banknote className="h-4 w-4 text-primary" />} />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/40 text-left text-muted-foreground">
                  <th className="pb-2 pr-4 font-medium">日期</th>
                  <th className="pb-2 pr-4 font-medium text-right">主力净流入</th>
                  <th className="pb-2 pr-4 font-medium text-right">超大单</th>
                  <th className="pb-2 pr-4 font-medium text-right">大单</th>
                  <th className="pb-2 pr-4 font-medium text-right">中单</th>
                  <th className="pb-2 pr-4 font-medium text-right">小单</th>
                </tr>
              </thead>
              <tbody>
                {fundFlow.slice().reverse().slice(0, 20).map((row, i) => (
                  <tr key={i} className="border-b border-border/20 last:border-0">
                    <td className="py-1.5 pr-4 font-mono text-muted-foreground">{row.date}</td>
                    {[
                      { v: row.main_net, label: "主力" },
                      { v: row.super_net, label: "超大" },
                      { v: row.large_net, label: "大" },
                      { v: row.mid_net, label: "中" },
                      { v: row.small_net, label: "小" },
                    ].map((cell) => (
                      <td key={cell.label} className={cn("py-1.5 pr-4 text-right font-mono", cell.v > 0 ? "text-danger" : cell.v < 0 ? "text-success" : "text-muted-foreground")}>
                        {fmt(cell.v, " 万")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      ) : (
        <GlassCard>
          <SectionHeader title="主力资金流向" icon={<Banknote className="h-4 w-4 text-primary" />} />
          <p className="py-6 text-center text-sm text-muted-foreground">暂无资金流向数据</p>
        </GlassCard>
      )}

      {/* Dragon Tiger */}
      {dt && dt.records && dt.records.length > 0 ? (
        <GlassCard>
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">龙虎榜（近30日 {dt.records.length} 次）</h3>
          <div className="space-y-2">
            {dt.records.slice(0, 6).map((r, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-sm last:border-0">
                <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">{r.date}</span>
                <span className="flex-1 truncate">{r.reason}</span>
                <span className={cn("shrink-0 font-mono text-xs", r.net_buy >= 0 ? "text-danger" : "text-success")}>
                  净买 {r.net_buy} 万
                </span>
              </div>
            ))}
          </div>
          {(dt.seats.buy.length > 0 || dt.seats.sell.length > 0) && (
            <div className="mt-3 grid gap-4 border-t border-border/40 pt-3 sm:grid-cols-2">
              <div>
                <p className="mb-1.5 text-xs font-medium text-danger">买入席位 TOP</p>
                {dt.seats.buy.map((s, i) => (
                  <div key={i} className="flex justify-between gap-2 text-xs text-muted-foreground">
                    <span className="truncate">{s.name}</span>
                    <span className="shrink-0 font-mono">净{s.net}万</span>
                  </div>
                ))}
              </div>
              <div>
                <p className="mb-1.5 text-xs font-medium text-success">卖出席位 TOP</p>
                {dt.seats.sell.map((s, i) => (
                  <div key={i} className="flex justify-between gap-2 text-xs text-muted-foreground">
                    <span className="truncate">{s.name}</span>
                    <span className="shrink-0 font-mono">净{s.net}万</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {dt.institution && (
            <div className="mt-3 border-t border-border/40 pt-3">
              <p className="mb-1.5 text-xs font-medium">机构净额</p>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <span className="text-muted-foreground">买入：</span>
                  <span className="font-mono">{fmt(dt.institution.buy_amt, " 万")}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">卖出：</span>
                  <span className="font-mono">{fmt(dt.institution.sell_amt, " 万")}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">净额：</span>
                  <span className={cn("font-mono", dt.institution.net_amt >= 0 ? "text-danger" : "text-success")}>
                    {fmt(dt.institution.net_amt, " 万")}
                  </span>
                </div>
              </div>
            </div>
          )}
        </GlassCard>
      ) : (
        <GlassCard>
          <SectionHeader title="龙虎榜" />
          <p className="py-6 text-center text-sm text-muted-foreground">暂无龙虎榜数据</p>
        </GlassCard>
      )}

      {/* Blocks */}
      {blocks && blocks.boards && blocks.boards.length > 0 && (
        <GlassCard>
          <SectionHeader title={`板块归属（${blocks.total}）`} />
          <div className="space-y-2">
            {blocks.boards.slice(0, 12).map((b, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span className="w-16 shrink-0 font-mono text-muted-foreground">{b.code}</span>
                <span className="flex-1 truncate">{b.name}</span>
                <span className={cn("shrink-0 font-mono", typeof b.change_pct === "number" ? pctColor(b.change_pct as number) : "text-muted-foreground")}>
                  {typeof b.change_pct === "number" ? `${b.change_pct > 0 ? "+" : ""}${b.change_pct}%` : String(b.change_pct)}
                </span>
                <span className="shrink-0 text-muted-foreground">龙头：{b.lead_stock}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* Hot concepts */}
      {hotCon && hotCon.length > 0 && (
        <GlassCard>
          <SectionHeader title="热门概念" />
          <div className="flex flex-wrap gap-1.5">
            {hotCon.slice(0, 24).map((h, i) => (
              <span key={i} className="rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary">
                {h.concept}
                <span className="ml-1 text-muted-foreground/60">×{h.hit}</span>
              </span>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function AITab({ data: _data }: { data: StockDeep | null }) {
  return (
    <div className="space-y-5">
      <GlassCard>
        <SectionHeader title="AI 洞察" icon={<Brain className="h-4 w-4 text-primary" />} />
        <p className="py-6 text-center text-sm text-muted-foreground">
          暂无 AI 洞察数据。配置 AI 后将自动分析生成。
        </p>
      </GlassCard>
    </div>
  );
}

// --- ValBand (reused from StockData.tsx pattern) ---
function ValBand({ label, m }: { label: string; m: ValMetric }) {
  const span = Math.max(m.max - m.min, 1e-6);
  const pos = (v: number) => Math.min(100, Math.max(0, ((v - m.min) / span) * 100));
  const p20 = pos(m.p20), p80 = pos(m.p80), cur = pos(m.current);
  const zoneColor = m.percentile < 20 ? "text-success" : m.percentile > 80 ? "text-danger" : "text-muted-foreground";
  const zoneLabel = m.percentile < 20 ? "低估区" : m.percentile > 80 ? "高估区" : "合理区";
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-1 text-sm">
        <span className="font-medium">{label} <span className="text-xs text-muted-foreground/60">{m.n} 点</span></span>
        <span className="text-muted-foreground">当前 <b className="font-mono text-foreground">{m.current}</b> · 近5年 <b className={cn("font-mono", zoneColor)}>{m.percentile}%</b> 分位（<span className={zoneColor}>{zoneLabel}</span>）</span>
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full">
        <div className="absolute inset-0 flex">
          <div className="bg-success/35" style={{ width: `${p20}%` }} />
          <div className="bg-muted" style={{ width: `${p80 - p20}%` }} />
          <div className="flex-1 bg-danger/35" />
        </div>
        <div className="absolute top-1/2 h-4 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded bg-foreground shadow" style={{ left: `${cur}%` }} />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground/60">
        <span>低 {m.min}</span><span>20% {m.p20}</span><span>中 {m.p50}</span><span>80% {m.p80}</span><span>高 {m.max}</span>
      </div>
    </div>
  );
}

// --- Main Page ---
export function StockDeep() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const { setItems } = useBreadcrumbs();

  useEffect(() => {
    if (!code) return;
    setItems([
      { label: "个股数据", to: "/stock-data" },
      { label: `${code} 深度分析` },
    ]);
  }, [code, setItems]);

  const [tab, setTab] = useState<TabKey>("quote");
  const [data, setData] = useState<StockDeep | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setErr(null);
    api.stockDeep(code)
      .then(setData)
      .catch((e: unknown) => setErr((e as Error)?.message || "加载失败"))
      .finally(() => setLoading(false));
  }, [code]);

  if (!code) return null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-3 text-sm text-muted-foreground">加载中…</span>
      </div>
    );
  }

  if (err) {
    return (
      <div className="space-y-4">
        <PageHeader
          title={`${code} 深度分析`}
          actions={
            <Button variant="ghost" onClick={() => navigate(-1)}>
              <ArrowLeft className="h-4 w-4" /> 返回
            </Button>
          }
        />
        <GlassCard>
          <div className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {err}
          </div>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={`${code} 深度分析`}
        subtitle={data?.quote?.name || ""}
        actions={
          <Button variant="ghost" onClick={() => navigate(-1)}>
            <ArrowLeft className="h-4 w-4" /> 返回
          </Button>
        }
      />

      {/* Tab bar */}
      <TabBar
        tabs={TABS.map(t => ({ key: t.key, label: t.label, icon: t.icon as any }))}
        activeKey={tab}
        onChange={(key) => setTab(key as TabKey)}
        className="mb-4"
      />

      {/* Tab content */}
      <GlassCard>
        {tab === "quote" && <QuoteTab data={data} code={code} />}
        {tab === "gene" && <GeneTab data={data} />}
        {tab === "fund" && <FundTab data={data} />}
        {tab === "ai" && <AITab data={data} />}
      </GlassCard>

      <Disclaimer />
    </div>
  );
}
