// Track E A3: 财报季日历 view — honest-empty shell。
// 后端无 /api/earnings-calendar 聚合 endpoint（grep 确认 stock_financial.py /
// stock_data.py 仅有 per-code /api/financials、/api/dragon-tiger、/api/disclosure、
// /api/lockup 等散端点，无全市场财报季日历聚合）。不臆造数据，标"待接线"。
// 排雷规则（1/4/8 月雷区标红 + 未披露预警 + 财报异常防一字跌停）待 M5
// ReportSeasonCircuitBreaker 实现。
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { Link } from "react-router-dom";
import { CalendarDays, AlertTriangle, ArrowLeft } from "lucide-react";

// A 股财报披露窗口：1/4/8 月为强制披露雷区（业绩预告/快报 + 定期报告集中披露期）。
// 1 月：三季报 + 年度业绩预告/快报 deadline（1.31）
// 4 月：年报 deadline（4.30）+ 一季报
// 8 月：中报 deadline（8.31）
const DANGER_MONTHS = [
  { month: 1, label: "1 月", reason: "三季报 + 年度业绩预告/快报（1.31 deadline）" },
  { month: 4, label: "4 月", reason: "年报（4.30 deadline）+ 一季报" },
  { month: 8, label: "8 月", reason: "中报（8.31 deadline）" },
];

const ALL_MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

function isDangerMonth(m: number): boolean {
  return DANGER_MONTHS.some((d) => d.month === m);
}

export function EarningsCalendarPage() {
  return (
    <div>
      <PageHeader
        title="财报季日历"
        subtitle="1/4/8 月雷区标红 · 披露日历 + 未披露预警 · 排雷规则待 M5 实现"
      />

      {/* honest-empty：后端无 earnings-calendar 聚合 endpoint */}
      <GlassCard tier="sub" className="mb-4 border-amber-500/30">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <div className="text-sm text-muted-foreground">
            <p className="font-medium text-amber-600">待接线 earnings-calendar endpoint</p>
            <p className="mt-1">
              后端无全市场财报季日历聚合 API（仅有 per-code <code className="font-mono text-xs">/api/financials</code>、
              <code className="font-mono text-xs">/api/disclosure</code>、
              <code className="font-mono text-xs">/api/lockup</code> 等散端点）。
              日历数据待后端建 <code className="font-mono text-xs">/api/earnings-calendar</code> 聚合后填充。
            </p>
          </div>
        </div>
      </GlassCard>

      {/* 雷区月份标注 */}
      <GlassCard tier="primary" className="mb-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <CalendarDays className="h-4 w-4 text-muted-foreground" />
          财报季雷区（强制披露窗口）
        </h2>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-12">
          {ALL_MONTHS.map((m) => {
            const danger = isDangerMonth(m);
            const meta = DANGER_MONTHS.find((d) => d.month === m);
            return (
              <div
                key={m}
                title={meta ? `${meta.label}：${meta.reason}` : `${m} 月`}
                className={`flex flex-col items-center rounded-lg border p-2 text-center ${
                  danger
                    ? "border-red-500/40 bg-red-500/10"
                    : "border-border/40 bg-muted/10"
                }`}
              >
                <span className={`text-xs font-medium ${danger ? "text-red-500" : "text-muted-foreground"}`}>
                  {m}月
                </span>
                {danger && (
                  <span className="mt-0.5 text-[9px] text-red-500/70">雷区</span>
                )}
              </div>
            );
          })}
        </div>
        <div className="mt-3 space-y-1">
          {DANGER_MONTHS.map((d) => (
            <div key={d.month} className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="h-2 w-2 shrink-0 rounded-full bg-red-500/60" />
              <span className="font-medium text-red-500">{d.label}</span>
              <span>{d.reason}</span>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* 披露日历 + 未披露预警（honest-empty） */}
      <GlassCard className="mb-4 p-4">
        <h2 className="mb-2 text-sm font-semibold">披露日历 + 未披露预警</h2>
        <p className="text-sm text-muted-foreground">
          持仓股 / 自选股 的财报披露日期 + 未披露预警（临近 deadline 仍未披露）待
          <code className="mx-1 font-mono text-xs">/api/earnings-calendar</code>
          endpoint 接线后填充。当前可经
          <Link to="/stock-data" className="ml-1 text-primary hover:underline">数据层</Link>
          按个股查 <code className="font-mono text-xs">/api/financials</code> + <code className="font-mono text-xs">/api/disclosure</code>。
        </p>
      </GlassCard>

      {/* M5 排雷规则标注 */}
      <GlassCard tier="sub" className="mb-4 p-4">
        <h2 className="mb-2 text-sm font-semibold">排雷规则</h2>
        <p className="text-xs text-muted-foreground">
          排雷规则待 <strong>M5 ReportSeasonCircuitBreaker</strong> 实现：
          雷区月份（1/4/8）未披露财务报告的标的拉黑 + 财务异常防一字跌停 +
          预披露窗口降仓。当前为占位，不阻塞交易但不提示雷区风险。
        </p>
      </GlassCard>

      <Link
        to="/workspace?phase=premarket"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
      >
        <ArrowLeft className="h-4 w-4" /> 返回盘面
      </Link>
    </div>
  );
}
