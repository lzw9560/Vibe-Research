// S166: 诊断区——MFE/MAE 行情回吐 + 判断/执行归因（⚠️ 暂降级）+ 异常收件箱。fresh-impl。
// 读 GET /api/risk/excursion + /api/risk/attribution + /api/risk/inbox。
// 不臆造：attribution available:False 如实呈现 reason（Vibe-Research 暂无 reflection/预测命中数据源），
// 不假装有命中；excursion bias_note 如实呈现捕获率被系统性低估。
import { GlassCard } from "@/components/ui/GlassCard";
import { useExcursion, useAttribution, useInbox } from "@/lib/query";
import type { ExcursionSummary, AttributionResponse, InboxResponse } from "@/lib/journal-contract";

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function ExcursionCard({ data }: { data: ExcursionSummary | undefined }) {
  if (!data) return <div className="text-xs text-muted-foreground">加载中…（首次逐笔拉行情会慢）</div>;
  if (!data.available) return <div className="text-xs text-muted-foreground">{data.reason}</div>;
  return (
    <div className="space-y-2 text-xs">
      {!data.enough_samples && (
        <div className="rounded bg-amber-500/10 p-2 text-amber-600">
          ⚠️ 只有 {data.trades} 笔，样本太少，别下结论
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <span>捕获率中位数 {data.median_capture_rate != null ? `${(data.median_capture_rate * 100).toFixed(0)}%` : "—"}（{data.capture_samples} 笔有讨论价值）</span>
        <span>盈利回吐中位数 {pct(data.median_give_back)}</span>
        <span>最大浮亏中位数 {pct(data.median_mae)}</span>
      </div>
      {data.capture_note && (
        <div className="text-red-500">{data.capture_note}</div>
      )}
      <div className="text-muted-foreground">⚠️ {data.bias_note}</div>
      <details>
        <summary className="cursor-pointer text-blue-500">逐笔明细（{data.items.length}）</summary>
        <div className="mt-1 overflow-x-auto">
          <table className="w-full">
            <thead><tr className="text-muted-foreground">
              <th className="px-2 text-left">日期</th><th className="px-2 text-left">代码</th>
              <th className="px-2">实际</th><th className="px-2">MFE</th><th className="px-2">MAE</th>
              <th className="px-2">回吐</th><th className="px-2">捕获率</th>
              <th className="px-2">精度</th>
            </tr></thead>
            <tbody>
              {data.items.map((it, i) => (
                <tr key={i} className="border-t">
                  <td className="px-2">{it.date}</td>
                  <td className="px-2 font-mono">{it.code}</td>
                  <td className="px-2 text-center">{pct(it.realized_pct)}</td>
                  <td className="px-2 text-center text-emerald-600">{pct(it.mfe_pct)}</td>
                  <td className="px-2 text-center text-red-500">{pct(it.mae_pct)}</td>
                  <td className="px-2 text-center">{pct(it.give_back_pct)}</td>
                  <td className="px-2 text-center">
                    {it.capture_rate != null ? `${(it.capture_rate * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-2 text-[10px] text-muted-foreground">{it.precision}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function AttributionCard({ data }: { data: AttributionResponse | undefined }) {
  if (!data) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!data.available) {
    return (
      <div className="space-y-1 text-xs">
        <div className="text-muted-foreground">{data.reason}</div>
        <div className="text-muted-foreground">
          函数结构已就位，待接预测命中数据源后激活——不臆造判断命中。
        </div>
      </div>
    );
  }
  const labels = data.quadrant_labels ?? {};
  const q = data.quadrants ?? {};
  return (
    <div className="space-y-2 text-xs">
      {!data.enough_samples && (
        <div className="rounded bg-amber-500/10 p-2 text-amber-600">⚠️ 只有 {data.days_counted} 天，样本太少</div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(labels).map(([key, label]) => {
          const c = q[key];
          return (
            <div key={key} className="rounded border p-2">
              <div className="font-medium">{label}</div>
              <div className="text-muted-foreground">{c?.days ?? 0} 天，{c?.pnl != null ? `${c.pnl.toFixed(0)} 元` : "—"}</div>
            </div>
          );
        })}
      </div>
      {data.note && <div className="text-muted-foreground">{data.note}</div>}
    </div>
  );
}

function InboxCard({ data }: { data: InboxResponse | undefined }) {
  if (!data) return <div className="text-xs text-muted-foreground">加载中…</div>;
  if (!data.available) return <div className="text-xs text-muted-foreground">{data.reason}</div>;
  return (
    <div className="space-y-2 text-xs">
      <div className="text-muted-foreground">扫了 {data.scanned} 笔，筛出 {data.count} 笔值得回头看</div>
      {data.excursion_hint && (
        <div className="rounded bg-amber-500/10 p-2 text-amber-600">{data.excursion_hint}</div>
      )}
      {data.items.length === 0 ? (
        <div className="text-muted-foreground">没有异常交易</div>
      ) : (
        <div className="space-y-1">
          {data.items.map((it) => (
            <div key={it.id} className="rounded border p-2">
              <div className="flex items-center justify-between">
                <span className="font-mono">{it.code}</span>
                <span>{it.date}</span>
                <span className={it.pnl_pct != null && it.pnl_pct < 0 ? "text-red-500" : "text-emerald-600"}>
                  {it.pnl_pct != null ? pct(it.pnl_pct) : "—"}
                </span>
              </div>
              <ul className="mt-1 list-inside list-disc space-y-0.5 text-muted-foreground">
                {it.flags.map((f, i) => <li key={i}>{f.text}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}
      <div className="text-muted-foreground">{data.note}</div>
    </div>
  );
}

export function DiagnosticsSection() {
  const exc = useExcursion(300);
  const attr = useAttribution(500);
  const inbox = useInbox(500);
  return (
    <div className="space-y-3">
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">MFE/MAE（最大浮盈/浮亏 + 盈利回吐）</div>
        <ExcursionCard data={exc.data} />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">判断/执行归因（四格：判对+亏钱=执行问题）</div>
        <AttributionCard data={attr.data} />
      </GlassCard>
      <GlassCard className="space-y-2 p-3">
        <div className="text-sm font-medium">异常交易收件箱</div>
        <InboxCard data={inbox.data} />
      </GlassCard>
    </div>
  );
}
