// S092 T8：TaskStatusCard——盘后采集任务状态卡片（公共区常驻）。
// 过渡窗（stage === "post_transition"）展开完整时间线 + 60s 轮询；
// 就绪态/盘前/盘中折叠为摘要条；非交易日显示"非交易日"。
// today_status 颜色：pending=灰空心 / running=蓝脉冲 / done=绿实心+载入按钮 / error=红半实心。
// 设计原型：specs/S092-三视图交易日锚与时段推进/ui-prototype.html + design-notes.md §3.1。
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useScheduledTasksStatus, type ScheduledTaskStatus } from "@/lib/query/scheduledTasks";

interface TaskStatusCardProps {
  /** dateTriplet.stage：决定展开/折叠 + 是否轮询 */
  stage: string;
  /** 是否交易日：非交易日显示"盘后采集任务休眠" */
  isTradingDay?: boolean;
}

/** today_status → 颜色语义类名映射（复刻 design-notes §3.1 + 原型 .t-item.{status}） */
const STATUS_STYLES: Record<
  ScheduledTaskStatus["today_status"],
  { node: string; pill: string; label: string }
> = {
  pending: {
    node: "border-muted-foreground/50 bg-muted/50",
    pill: "bg-muted/50 text-muted-foreground",
    label: "待运行",
  },
  running: {
    node: "border-[hsl(199_89%_58%)] bg-[hsl(199_89%_58%/0.2)] animate-pulse shadow-[0_0_10px_hsl(199_89%_58%/0.6)]",
    pill: "bg-[hsl(199_89%_58%/0.12)] text-[hsl(199_89%_58%)]",
    label: "运行中",
  },
  done: {
    node: "border-[hsl(145_62%_47%)] bg-[hsl(145_62%_47%)]",
    pill: "bg-[hsl(145_62%_47%/0.12)] text-[hsl(145_62%_47%)]",
    label: "已完成",
  },
  error: {
    node: "border-[hsl(0_74%_60%)] bg-[hsl(0_74%_60%/0.3)]",
    pill: "bg-[hsl(0_74%_60%/0.12)] text-[hsl(0_74%_60%)]",
    label: "错误",
  },
};

/**
 * cron_expr 解析为计划时间显示（简单版）。
 * "30 15 * * 1-5" → "15:30"（分钟=段0，小时=段1）。
 * 解析失败回退原 cron 串。
 */
function cronToTime(cronExpr: string): string {
  const parts = cronExpr.trim().split(/\s+/);
  if (parts.length >= 2 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
    const hh = parts[1].padStart(2, "0");
    const mm = parts[0].padStart(2, "0");
    return `${hh}:${mm}`;
  }
  return cronExpr;
}

/** 按计划时间排序（早 → 晚）；解析不出时间的排末尾。 */
function sortByCronTime(tasks: ScheduledTaskStatus[]): ScheduledTaskStatus[] {
  return [...tasks].sort((a, b) => {
    const ta = cronToTime(a.cron_expr);
    const tb = cronToTime(b.cron_expr);
    // 只比较 "HH:MM" 格式，非该格式（解析失败回退原串）排后
    const timeRe = /^\d{2}:\d{2}$/;
    const ea = timeRe.test(ta) ? 0 : 1;
    const eb = timeRe.test(tb) ? 0 : 1;
    if (ea !== eb) return ea - eb;
    return ta.localeCompare(tb);
  });
}

export function TaskStatusCard({ stage, isTradingDay }: TaskStatusCardProps) {
  // 过渡窗启用查询 + 60s 轮询（hook 内部门控）
  const isTransition = stage === "post_transition";
  const { data: tasks } = useScheduledTasksStatus(isTransition);
  const queryClient = useQueryClient();

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, any>>({});

  // 非交易日保持盘后就绪态（不显示空状态——用户仍可复盘/看简报/看选股）
  // tasks 可能为空（hook 未启用查询）。
  const list = tasks ?? [];
  const sorted = sortByCronTime(list);
  const doneCount = list.filter((t) => t.today_status === "done").length;
  const total = list.length;
  const firstTaskTime = sorted[0] ? cronToTime(sorted[0].cron_expr) : null;

  // 点击任务项展开详情（调 api.scheduledTask(id)）
  async function toggleDetail(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!detailCache[id]) {
      try {
        const detail = await api.scheduledTask(id);
        setDetailCache((prev) => ({ ...prev, [id]: detail }));
      } catch (e) {
        // 加载失败不阻塞展开，详情区显示失败提示
        setDetailCache((prev) => ({ ...prev, [id]: { __error: true } }));
      }
    }
  }

  // done 项的"载入"按钮：全量 invalidate 触发所有视图 refetch（P2 修复：原 ["workflow"] key 打不中视图数据）
  function handleLoad(e: React.MouseEvent, taskName: string) {
    e.stopPropagation();
    console.log("[TaskStatusCard] 载入任务产出:", taskName);
    void queryClient.invalidateQueries();  // 全量 invalidate——过渡窗场景成本可忽略
  }

  return (
    <GlassCard className="mb-3" data-testid="task-status-card">
      {/* Header：标题 + 进度徽章 + 摘要 + 折叠箭头 */}
      <div
        className="flex items-center justify-between gap-3"
        data-testid="task-card-head"
      >
        <h3 className="flex items-center gap-2 font-serif text-[15px] font-bold">
          <span>盘后采集任务</span>
          {total > 0 && (
            <span className="rounded-full bg-muted/40 px-2 py-0.5 font-mono text-[11px] text-muted-foreground" data-testid="task-progress">
              {doneCount}/{total}
            </span>
          )}
        </h3>
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          {isTransition ? (
            <span data-testid="task-summary">
              {doneCount} 项已完成
              {firstTaskTime ? ` · ${firstTaskTime} 开始` : ""}
            </span>
          ) : (
            <span data-testid="task-summary">
              {total > 0
                ? `盘后采集 ${firstTaskTime ?? ""} 开始 · ${doneCount}/${total}`
                : "盘后采集任务"}
            </span>
          )}
          <span
            className={cn(
              "text-muted-foreground transition-transform",
              isTransition ? "rotate-0" : "-rotate-90",
            )}
          >
            ▾
          </span>
        </div>
      </div>

      {/* Body：过渡窗展开完整时间线；其他时段折叠摘要条 */}
      {isTransition && (
        <div className="mt-3" data-testid="task-timeline">
          {sorted.length === 0 ? (
            <div className="py-4 text-center text-sm text-muted-foreground">
              加载中…
            </div>
          ) : (
            <div className="relative pl-[22px]">
              {/* 时间线竖线 */}
              <div className="absolute left-[7px] top-1.5 bottom-1.5 w-0.5 bg-border" />
              {sorted.map((t) => {
                const style = STATUS_STYLES[t.today_status];
                const time = cronToTime(t.cron_expr);
                const isExpanded = expandedId === t.id;
                return (
                  <div
                    key={t.id}
                    onClick={() => toggleDetail(t.id)}
                    className={cn(
                      "relative grid grid-cols-1 gap-2 py-1.5 pl-3.5 sm:grid-cols-[1fr_auto_auto] sm:items-center",
                      isExpanded && "bg-muted/20 rounded-md",
                    )}
                    data-testid={`task-item-${t.id}`}
                    data-today-status={t.today_status}
                  >
                    {/* 节点圆 */}
                    <span
                      className={cn(
                        "absolute -left-[19px] top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2",
                        style.node,
                      )}
                    />
                    {/* 左：时间 + 名称 */}
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[12px] font-semibold text-muted-foreground min-w-[42px]">
                        {time}
                      </span>
                      <span className="text-[13px]">{t.name}</span>
                    </div>
                    {/* 中：ETA */}
                    <span className="hidden text-[11px] font-mono text-muted-foreground/70 sm:block">
                      {t.today_status === "pending"
                        ? `预计 ${time}`
                        : t.today_status === "running"
                          ? "运行中"
                          : t.today_status === "done"
                            ? "已完成"
                            : "错误"}
                    </span>
                    {/* 右：状态徽章 + 载入按钮 */}
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 font-mono text-[11px]",
                          style.pill,
                        )}
                      >
                        {style.label}
                      </span>
                      {t.today_status === "done" && (
                        <button
                          onClick={(e) => handleLoad(e, t.name)}
                          className="rounded bg-primary px-2 py-0.5 text-[11px] font-bold text-primary-foreground hover:shadow-[0_0_12px_hsl(15_89%_56%/0.45)]"
                          data-testid={`load-btn-${t.id}`}
                        >
                          载入
                        </button>
                      )}
                    </div>
                    {/* 展开详情 */}
                    {isExpanded && (
                      <div className="col-span-1 mt-1.5 rounded-md bg-muted/25 p-2 text-[11px] text-muted-foreground sm:col-span-3">
                        {detailCache[t.id]?.__error ? (
                          <span className="text-[hsl(0_74%_60%)]">详情加载失败</span>
                        ) : detailCache[t.id] ? (
                          <span>
                            <strong>{t.name}</strong> · cron:{" "}
                            <span className="font-mono">{t.cron_expr}</span> · 状态:{" "}
                            {style.label}
                            <br />
                            上次执行:{" "}
                            <span className="font-mono">
                              {t.last_run_at ?? "—"}
                            </span>
                          </span>
                        ) : (
                          <span>加载中…</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 折叠态（非过渡窗）：摘要条，无时间线
          P10 修复：非交易日显示"盘后采集任务休眠"文案（design-notes §3.2） */}
      {!isTransition && (isTradingDay === false || total > 0) && (
        <div className="mt-2 text-[12px] text-muted-foreground" data-testid="task-collapsed-summary">
          {isTradingDay === false
            ? "非交易日 · 盘后采集任务休眠"
            : `盘后采集 ${firstTaskTime ?? ""} 开始 · 已完成 ${doneCount}/${total}`}
        </div>
      )}
    </GlassCard>
  );
}
