// S064：盯盘教练页——盘中时刻表 + 条件状态 + 教学点 + 降级模式选择。
// MVP 一期（§12.2）：时刻表纵向时间线（当前槽位高亮）+ 条件清单 + attention_mode A/B/C 选择 + 教学点。
import { WorkflowStage } from "./components/WorkflowStage";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { TabBar } from "@/components/ui/TabBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Lightbulb, AlertTriangle, Clock, Activity, Shield } from "lucide-react";
import { useCoachStatus, useCoachTimetable, useCoachAttentionMode, useSetCoachAttentionMode } from "@/lib/query";
import type { CoachTimetableSlot, CoachChecklistItem } from "@/lib/api";

const MODE_TABS = [
  { key: "A", label: "A 全程" },
  { key: "B", label: "B 关键节点" },
  { key: "C", label: "C 缺席" },
];

export default function IntradayCoach() {
  const statusQ = useCoachStatus();
  const timetableQ = useCoachTimetable();
  const modeQ = useCoachAttentionMode();
  const setMode = useSetCoachAttentionMode();

  const state = statusQ.data;
  const slots = timetableQ.data?.slots ?? [];
  const currentSlotId = timetableQ.data?.current_slot_id ?? state?.current_slot?.slot_id ?? null;
  const slotStatus = state?.slot_status ?? "before_open";
  const checklist = state?.checklist ?? [];
  const mode = modeQ.data?.attention_mode ?? "A";
  const modeRules = modeQ.data?.rules ?? { label: "", desc: "" };
  const slot = slots.find((s) => s.slot_id === currentSlotId) ?? null;

  return (
    <WorkflowStage
      title="盯盘教练"
      subtitle="W-C Coach · 高价值时刻表 + 条件状态 + 教学点"
      loading={statusQ.isLoading || modeQ.isLoading || timetableQ.isLoading}
      onRefresh={() => { statusQ.refetch(); modeQ.refetch(); timetableQ.refetch(); }}
    >
      {/* 降级模式选择 */}
      <section className="mb-6">
        <SectionHeader title="关注模式" subtitle="盘前选择当日盯盘强度（跨日自动重置 A）" icon={<Shield className="h-4 w-4" />} />
        <GlassCard className="mt-2 p-4">
          <TabBar
            tabs={MODE_TABS}
            activeKey={mode}
            onChange={(k) => setMode.mutate(k)}
          />
          <p className="mt-3 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{modeRules.label}</span>
            ：{modeRules.desc}
          </p>
        </GlassCard>
      </section>

      {/* 时刻表 */}
      <section className="mb-6">
        <SectionHeader
          title="时刻表"
          subtitle={`当前 ${state?.current_time ?? "--:--"} · ${slotStatusLabel(slotStatus)}`}
          icon={<Clock className="h-4 w-4" />}
        />
        <div className="mt-2 space-y-2">
          {slots.length === 0 && (
            <GlassCard className="p-4 text-sm text-muted-foreground">时刻表加载中…</GlassCard>
          )}
          {slots.length > 0 && (
            <TimetableList slots={slots} currentSlotId={currentSlotId} mode={mode} />
          )}
        </div>
      </section>

      {/* 条件状态清单 */}
      <section className="mb-6">
        <SectionHeader
          title="候选条件状态"
          subtitle="watching / monitoring / holding 逐只核对"
          icon={<Activity className="h-4 w-4" />}
        />
        <GlassCard className="mt-2 p-4">
          {checklist.length === 0 ? (
            <EmptyState
              icon={<Activity className="h-8 w-8 text-muted-foreground/50" />}
              title="暂无候选/持仓"
              description="盘前简报生成候选后，此处逐只显示条件达成度"
            />
          ) : (
            <div className="space-y-2">
              {checklist.map((item) => (
                <ChecklistCard key={item.code} item={item} />
              ))}
            </div>
          )}
        </GlassCard>
      </section>

      {/* 教学点（当前槽位） */}
      {slot && (
        <section className="mb-6">
          <SectionHeader title="当前教学点" subtitle={slot.label} icon={<Lightbulb className="h-4 w-4" />} />
          <GlassCard className="mt-2 p-4">
            <div className="flex items-start gap-3">
              <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <div className="text-sm">
                <p className="text-foreground">{slot.teaching}</p>
                <p className="mt-2 text-muted-foreground">
                  <span className="font-medium">看什么：</span>{slot.watch}
                </p>
                <p className="text-muted-foreground">
                  <span className="font-medium">怎么判断：</span>{slot.judge}
                </p>
                {slot.mode_note?.[mode as "A" | "B" | "C"] && (
                  <p className="mt-2 rounded-lg bg-muted/30 p-2 text-xs text-muted-foreground">
                    <span className="font-medium">本模式行为：</span>{slot.mode_note[mode as "A" | "B" | "C"]}
                  </p>
                )}
              </div>
            </div>
          </GlassCard>
        </section>
      )}

      {/* C 档铁律提醒 */}
      {mode === "C" && (
        <section className="mb-6">
          <GlassCard className="border-red-500/40 p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
              <div className="text-sm text-red-500/90">
                <p className="font-medium">C 档四条铁律</p>
                <p className="mt-1 text-muted-foreground">{modeRules.desc}</p>
              </div>
            </div>
          </GlassCard>
        </section>
      )}

      <Disclaimer />
    </WorkflowStage>
  );
}

function slotStatusLabel(s: string): string {
  switch (s) {
    case "active": return "进行中";
    case "gap": return "间隙（等待下一槽位）";
    case "before_open": return "盘前";
    case "after_close": return "盘后";
    case "weekend": return "周末休市";
    default: return s;
  }
}

function TimetableList({ slots, currentSlotId, mode }: { slots: CoachTimetableSlot[]; currentSlotId: string | null; mode: string }) {
  // 排序：按 start 时间升序；lunch_break 放到 11:00 段（已是 start=11:00）
  const sorted = [...slots].sort((a, b) => a.start.localeCompare(b.start));
  return (
    <>
      {sorted.map((s) => {
        const isCurrent = s.slot_id === currentSlotId;
        return (
          <GlassCard
            key={s.slot_id}
            className={`p-3 ${isCurrent ? "border-l-4 border-l-primary" : ""}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">{s.start}–{s.end}</span>
                  <span className={`text-sm font-medium ${isCurrent ? "text-primary" : ""}`}>{s.label}</span>
                  {isCurrent && (
                    <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">当前</span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  <span className="font-medium">看：</span>{s.watch}
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-medium">判：</span>{s.judge}
                </p>
                <p className="mt-1 flex items-center gap-1 text-xs text-amber-600/80">
                  <Lightbulb className="h-3 w-3" />{s.teaching}
                </p>
                {isCurrent && s.mode_note?.[mode as "A" | "B" | "C"] && (
                  <p className="mt-1 rounded bg-muted/30 p-1.5 text-[11px] text-muted-foreground">
                    <span className="font-medium">本模式：</span>{s.mode_note[mode as "A" | "B" | "C"]}
                  </p>
                )}
              </div>
            </div>
          </GlassCard>
        );
      })}
    </>
  );
}

function ChecklistCard({ item }: { item: CoachChecklistItem }) {
  const hasWarning = !!item.max_hold_warning;
  const hasBomb = item.bomb_alerts.length > 0;
  return (
    <div className={`rounded-lg border p-3 ${hasWarning ? "border-red-500/40 bg-red-500/5" : "border-border/60"}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm">{item.code}</span>
          <span className="text-sm text-muted-foreground">{item.name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <StatusBadge status={item.status} />
          {item.strategy_name && (
            <span className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground">{item.strategy_name}</span>
          )}
        </div>
      </div>
      {item.entry_condition && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          <span className="font-medium">入场：</span>{item.entry_condition}
        </p>
      )}
      {item.matched_triggers.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {item.matched_triggers.map((t) => (
            <span key={t} className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{t}</span>
          ))}
        </div>
      )}
      {item.seal_amount !== null && (
        <p className="mt-1 text-xs text-muted-foreground">
          封单额：{(item.seal_amount / 1e4).toFixed(0)} 万
        </p>
      )}
      {hasBomb && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-orange-500">
          <AlertTriangle className="h-3 w-3" />
          {item.bomb_alerts.map((b) => b.rule_id).join(" / ")}
        </div>
      )}
      {item.data_status === "missing" && (
        <p className="mt-1 text-[10px] text-muted-foreground/60">数据缺失（不臆造）</p>
      )}
      {hasWarning && (
        <p className="mt-1.5 text-xs text-red-500">{item.max_hold_warning}</p>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    watching: "bg-blue-500/15 text-blue-500",
    monitoring: "bg-amber-500/15 text-amber-500",
    holding: "bg-green-500/15 text-green-600",
  };
  const cls = colors[status] ?? "bg-muted/40 text-muted-foreground";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${cls}`}>{status}</span>
  );
}
