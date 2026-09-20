// 财务面板——调 /api/financials + /api/valuation + /api/valuation/percentile
// 渲染财报指标 + 估值快览 + 历史分位。用于 RightPanel「财务」tab。
// Promise.allSettled 独立容错：一源挂不影响其余（诚实呈现，不臆造）。
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Financials, Valuation, ValPercentile, ValMetric } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  code: string;
}

// 数字格式化：null/NaN → "—"（不臆造、不补 0）
function fmtNum(v: number | null | undefined, suffix = "", digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

// 字符串格式化：null/空/"--"/"None" → "—"（财报字段为预格式化字符串）
function fmtStr(v: string | null | undefined): string {
  if (v == null || v === "" || v === "--" || v === "-" || v === "None") return "—";
  return v;
}

// YoY 着色：负→红，正→橙，空→muted
function yoyClass(v: string | null | undefined): string {
  if (!v || v === "—") return "text-muted-foreground";
  return v.trim().startsWith("-") ? "text-danger" : "text-primary";
}

// 单指标卡片——label / 值(font-mono) / 可选 sub（同比等）
function MetricCard({
  label,
  value,
  sub,
  subClass,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  subClass?: string;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/10 px-2.5 py-1.5">
      <p className="text-xs leading-tight text-muted-foreground">{label}</p>
      <p
        className={cn(
          "font-mono text-sm leading-relaxed",
          highlight ? "text-primary" : "text-foreground",
        )}
      >
        {value}
      </p>
      {sub && sub !== "—" && (
        <p className={cn("text-xs leading-tight", subClass ?? "text-muted-foreground")}>
          {sub}
        </p>
      )}
    </div>
  );
}

// 分位卡片——当前分位% + 当前值 + 历史范围
function PercentileCard({ label, m }: { label: string; m: ValMetric }) {
  const pctStr =
    m.percentile != null && !Number.isNaN(m.percentile)
      ? `${m.percentile.toFixed(0)}%`
      : "—";
  return (
    <div className="rounded-lg border border-border/60 bg-muted/10 px-2.5 py-1.5">
      <p className="text-xs leading-tight text-muted-foreground">{label}</p>
      <p className="font-mono text-sm leading-relaxed text-primary">{pctStr}</p>
      <p className="text-xs leading-tight text-muted-foreground">
        当前 {fmtNum(m.current)} · 区间 {fmtNum(m.min)}~{fmtNum(m.max)}
      </p>
    </div>
  );
}

// 检查财报是否有实质数据（全 null → 视为空）
function hasFinData(fin: Financials | null): boolean {
  if (!fin) return false;
  return Boolean(
    fin.revenue || fin.net_profit || fin.eps || fin.roe ||
    fin.gross_margin || fin.net_margin || fin.op_cf_ps || fin.bvps,
  );
}

// 检查估值是否有实质数据
function hasValData(val: Valuation | null): boolean {
  if (!val) return false;
  return Boolean(val.pe_ttm || val.pb || val.mcap_yi);
}

export function FinancialsPanel({ code }: Props) {
  const [fin, setFin] = useState<Financials | null>(null);
  const [val, setVal] = useState<Valuation | null>(null);
  const [pct, setPct] = useState<ValPercentile | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setFin(null);
    setVal(null);
    setPct(null);

    Promise.allSettled([
      api.financials(code),
      api.valuation(code),
      api.percentile(code),
    ]).then((results) => {
      if (cancelled) return;
      const [finR, valR, pctR] = results;
      const failures: string[] = [];

      if (finR.status === "fulfilled") setFin(finR.value);
      else failures.push("财务");

      if (valR.status === "fulfilled") setVal(valR.value);
      else failures.push("估值");

      if (pctR.status === "fulfilled") setPct(pctR.value);
      else failures.push("分位");

      // 全部失败 → 显错误
      if (failures.length === 3) {
        const reason =
          finR.status === "rejected" ? finR.reason
          : valR.status === "rejected" ? valR.reason
          : pctR.status === "rejected" ? pctR.reason
          : "unknown";
        setErr(reason instanceof Error ? reason.message : String(reason));
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [code]);

  const showFin = hasFinData(fin);
  const showVal = hasValData(val);
  const showPct = Boolean(pct && pct.metrics && (pct.metrics.pe_ttm || pct.metrics.pb));
  const allEmpty = !showFin && !showVal && !showPct;

  return (
    <div className="space-y-3">
      {loading && (
        <p className="text-xs text-muted-foreground">加载财务数据…</p>
      )}
      {err && (
        <p className="text-xs text-danger">加载失败：{err}</p>
      )}

      {!loading && !err && allEmpty && (
        <p className="text-xs text-muted-foreground">
          暂无财务数据（次新股或数据源未返回）
        </p>
      )}

      {/* 估值快览 */}
      {showVal && (
        <div className="space-y-1.5">
          <h5 className="text-xs font-semibold text-muted-foreground">估值快览</h5>
          <div className="grid grid-cols-3 gap-1.5">
            <MetricCard label="PE-TTM" value={fmtNum(val!.pe_ttm)} highlight />
            <MetricCard label="PB" value={fmtNum(val!.pb)} highlight />
            <MetricCard label="总市值" value={fmtNum(val!.mcap_yi, "亿")} />
            <MetricCard label="前向PE 26E" value={fmtNum(val!.pe_26e)} />
            <MetricCard label="PEG" value={fmtNum(val!.peg)} />
            <MetricCard label="消化年数" value={fmtNum(val!.digest_years, "年", 1)} />
            <MetricCard label="EPS 26E" value={fmtNum(val!.eps_26e)} />
            <MetricCard label="EPS 27E" value={fmtNum(val!.eps_27e)} />
            <MetricCard label="分析师" value={fmtNum(val!.analyst_count, "家", 0)} />
          </div>
          {val!.forecast_note && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {val!.forecast_note}
            </p>
          )}
        </div>
      )}

      {/* 历史分位 */}
      {showPct && (
        <div className="space-y-1.5">
          <h5 className="text-xs font-semibold text-muted-foreground">
            历史分位
            {pct!.period && (
              <span className="ml-1 font-normal">（{pct!.period}）</span>
            )}
          </h5>
          <div className="grid grid-cols-2 gap-1.5">
            {pct!.metrics.pe_ttm && (
              <PercentileCard label="PE 分位" m={pct!.metrics.pe_ttm} />
            )}
            {pct!.metrics.pb && (
              <PercentileCard label="PB 分位" m={pct!.metrics.pb} />
            )}
          </div>
        </div>
      )}

      {/* 财务指标 */}
      {showFin && (
        <div className="space-y-1.5">
          <h5 className="text-xs font-semibold text-muted-foreground">
            财务指标
            {fin!.period && (
              <span className="ml-1 font-normal">（{fin!.period}）</span>
            )}
          </h5>
          <div className="grid grid-cols-2 gap-1.5">
            <MetricCard
              label="营收"
              value={fmtStr(fin!.revenue)}
              sub={fmtStr(fin!.revenue_yoy)}
              subClass={yoyClass(fin!.revenue_yoy)}
            />
            <MetricCard
              label="净利润"
              value={fmtStr(fin!.net_profit)}
              sub={fmtStr(fin!.net_profit_yoy)}
              subClass={yoyClass(fin!.net_profit_yoy)}
            />
            <MetricCard label="EPS" value={fmtStr(fin!.eps)} />
            <MetricCard label="BVPS" value={fmtStr(fin!.bvps)} />
            <MetricCard label="ROE" value={fmtStr(fin!.roe)} highlight />
            <MetricCard label="毛利率" value={fmtStr(fin!.gross_margin)} />
            <MetricCard label="净利率" value={fmtStr(fin!.net_margin)} />
            <MetricCard label="每股经营现金流" value={fmtStr(fin!.op_cf_ps)} />
          </div>
        </div>
      )}
    </div>
  );
}
