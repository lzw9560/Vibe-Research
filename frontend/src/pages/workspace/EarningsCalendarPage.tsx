// S216 P2 接线：财报季日历接 /api/earnings-calendar 聚合 endpoint。
// DANGER_MONTHS 从后端来（监管强制披露窗口公开知识非硬编码臆造），
// 可选 codes 参数聚合 per-code 披露/解禁。缺数据 HonestEmptyState。
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CalendarDays, AlertTriangle, ArrowLeft, Search } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { api } from "@/lib/api";
import type { EarningsCalendarResponse } from "@/lib/api";

const ALL_MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

export function EarningsCalendarPage() {
  const [codesInput, setCodesInput] = useState("");
  const [codesQuery, setCodesQuery] = useState("");

  const { data, isLoading, error, refetch } = useQuery<EarningsCalendarResponse>({
    queryKey: ["earnings-calendar", codesQuery] as const,
    queryFn: () => api.earningsCalendar(codesQuery || undefined),
    refetchInterval: 30 * 60 * 1000, // 30min
  });

  const dangerMonths = data?.danger_months ?? [];
  const perCode = data?.per_code;
  const status = data?.data_status;

  const submitCodes = () => {
    const trimmed = codesInput.trim().replace(/[，\s]+/g, ",");
    setCodesQuery(trimmed);
    void refetch();
  };

  return (
    <div>
      <PageHeader
        title="财报季日历"
        subtitle="1/4/8 月雷区标红 · 披露日历 + 未披露预警 · 聚合 /api/earnings-calendar"
      />

      {/* codes 输入 */}
      <GlassCard tier="sub" className="mb-4 p-4">
        <h2 className="mb-2 text-sm font-semibold">个股聚合查询（可选）</h2>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={codesInput}
            onChange={(e) => setCodesInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitCodes()}
            placeholder="逗号分隔 6 位代码，如 600519,000001"
            className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
          />
          <button
            onClick={submitCodes}
            className="inline-flex items-center gap-1 rounded bg-primary px-3 py-1 text-sm text-primary-foreground hover:opacity-90"
          >
            <Search className="h-3 w-3" /> 查询
          </button>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          留空只看监管雷区日历；填代码聚合 per-code 公告 + 解禁。
        </p>
      </GlassCard>

      {isLoading && (
        <GlassCard className="mb-4 p-4 text-sm text-muted-foreground">加载中…</GlassCard>
      )}
      {error && !isLoading && (
        <GlassCard className="mb-4 border-red-500/30 p-4 text-sm text-red-500">
          加载失败：{error instanceof Error ? error.message : "未知错误"}
        </GlassCard>
      )}

      {/* 雷区月份标注 */}
      {dangerMonths.length > 0 && (
        <GlassCard tier="primary" className="mb-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
            财报季雷区（强制披露窗口）
          </h2>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-12">
            {ALL_MONTHS.map((m) => {
              const danger = dangerMonths.find((d) => d.month === m);
              return (
                <div
                  key={m}
                  title={danger ? `${danger.label}：${danger.reason}` : `${m} 月`}
                  className={`flex flex-col items-center rounded-lg border p-2 text-center ${
                    danger ? "border-red-500/40 bg-red-500/10" : "border-border/40 bg-muted/10"
                  }`}
                >
                  <span
                    className={`text-xs font-medium ${danger ? "text-red-500" : "text-muted-foreground"}`}
                  >
                    {m}月
                  </span>
                  {danger && <span className="mt-0.5 text-[9px] text-red-500/70">雷区</span>}
                </div>
              );
            })}
          </div>
          <div className="mt-3 space-y-1">
            {dangerMonths.map((d) => (
              <div
                key={d.month}
                className="flex items-center gap-2 text-xs text-muted-foreground"
              >
                <span className="h-2 w-2 shrink-0 rounded-full bg-red-500/60" />
                <span className="font-medium text-red-500">{d.label}</span>
                <span>{d.reason}</span>
                <span className="text-[10px] text-red-500/70">deadline {d.deadline}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* per-code 聚合 */}
      {perCode && perCode.length > 0 && (
        <GlassCard className="mb-4 p-4">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            个股披露 + 解禁聚合
            {status === "partial" && (
              <span className="text-[10px] text-amber-600">部分源缺数据</span>
            )}
          </h2>
          <ul className="space-y-2">
            {perCode.map((p) => (
              <li key={p.code} className="border border-border rounded-lg p-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{p.code}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                      p.data_status === "ok"
                        ? "bg-emerald-500/10 text-emerald-600"
                        : p.data_status === "partial"
                        ? "bg-amber-500/10 text-amber-600"
                        : "bg-red-500/10 text-red-600"
                    }`}
                  >
                    {p.data_status}
                  </span>
                </div>
                {p.announcements.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {p.announcements.slice(0, 5).map((a, i) => (
                      <li key={i} className="text-xs text-muted-foreground">
                        {a.date} · {a.title} {a.type && `(${a.type})`}
                      </li>
                    ))}
                  </ul>
                )}
                {p.lockup_expiries.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {p.lockup_expiries.map((l, i) => (
                      <li key={i} className="text-xs text-amber-600">
                        解禁 {l.date} · {l.type} · {l.shares} 股
                      </li>
                    ))}
                  </ul>
                )}
                {p.announcements.length === 0 && p.lockup_expiries.length === 0 && (
                  <span className="text-xs text-muted-foreground">无近期公告/解禁</span>
                )}
              </li>
            ))}
          </ul>
        </GlassCard>
      )}

      {perCode && perCode.length === 0 && codesQuery && !isLoading && (
        <HonestEmptyState
          message={`codes=${codesQuery} 无聚合数据`}
          hint="源可能返空或全部失败，检查代码格式或重试"
        />
      )}

      {data?.note && (
        <p className="mb-4 text-xs text-muted-foreground">{data.note}</p>
      )}

      <Link
        to="/workspace?phase=premarket"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
      >
        <ArrowLeft className="h-4 w-4" /> 返回盘面
      </Link>
    </div>
  );
}
