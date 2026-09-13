/**
 * Track B IA: PipelinePage 重定位 — 479→~150 任务健康表
 * 删 @xyflow/dagre/antd Drawer，移系统次入口
 * 34 task 行 + 列[名称/cron/上次运行/状态/耗时]，失败标红点击展开日志
 * 保留 TASK_TYPE_CN + PIPELINE_STEPS 作分组标题（非图）
 */
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { useScheduledTasks, useScheduledTaskRuns } from "@/lib/query";
import type { ScheduledTask, TaskRun } from "@/lib/api/types";
import { cn } from "@/lib/utils";

// 34 task 中文映射
const TASK_TYPE_CN: Record<string, string> = {
  daily_data_refresh: "每日数据刷新",
  daily_review_notify: "每日复盘通知",
  limitup_precompute: "盘后预计算",
  portfolio_refresh: "持仓刷新",
  market_data_sync: "市场数据同步",
  cleanup_old_runs: "清理旧运行记录",
  candidate_funnel_precompute: "盘后漏斗预计算",
  first_board_filter: "盘后首板筛选",
  kline_refresh: "K线日更",
  forward_test_daily: "前向测试记录",
  forward_test_t1_settle: "T+1收益结算",
  first_board_t1_review: "首板T+1复盘",
  first_board_quote_probe: "首板报价探测",
  zt_history_snapshot: "涨停史快照",
  derived_precompute: "衍生预计算",
  sti_post_market: "STI盘后",
  seal_intraday_collect: "盘中封单采集",
  s066_validation_checkpoint: "§44复验检查点",
  daily_backtest_run: "每日回测快照",
  daily_ai_summary: "AI盘后总结",
  monthly_vacuum: "月度VACUUM",
  premarket_auction_notify: "盘前竞价通知",
  premarket_open_notify: "盘前开盘通知",
  premarket_t1_review: "盘前T+1复盘",
  st_play_radar: "ST异动雷达",
  scan_watchlist_gaps: "缺口变盘扫描",
  scan_price_alerts: "价格预警扫描",
  daily_full_pull: "每日全量拉取",
  weekly_brainstorm_remind: "每周头脑风暴提醒",
  ofi_collect: "OFI订单流采集",
  trade_journal_daily: "交易日志日记",
  daily_kg_sync: "知识图谱日同步",
  daily_kg_audit: "知识图谱日审计",
  intraday_auction_dense: "盘中竞价密集采集",
  baostock_5min_freeze: "baostock 5分钟冻结",
  intraday_microstructure_snapshot: "盘中微观结构快照",
  evaluation_backtest: "评价层回溯",
  healthcheck_ping: "健康检查ping",
  turso_sync: "Turso云同步",
};

// 9 步分组（非图，作可折叠分组标题）
const PIPELINE_STEPS = [
  { id: "data-collect", title: "数据采集", taskTypes: ["daily_full_pull", "kline_refresh", "baostock_5min_freeze", "ofi_collect", "intraday_microstructure_snapshot", "intraday_auction_dense"] },
  { id: "kg-inject", title: "图谱注入M7", taskTypes: ["daily_kg_sync", "daily_kg_audit"] },
  { id: "factor-calc", title: "因子计算", taskTypes: ["limitup_precompute", "candidate_funnel_precompute"] },
  { id: "strategy-gen", title: "策略生成", taskTypes: ["premarket_t1_review", "st_play_radar", "weekly_brainstorm_remind"] },
  { id: "backtest-verify", title: "回测验证§44v2", taskTypes: ["evaluation_backtest", "daily_backtest_run", "s066_validation_checkpoint"] },
  { id: "paper-trade", title: "模拟盘", taskTypes: ["trade_journal_daily", "forward_test_daily"] },
  { id: "live-exec", title: "实盘执行", taskTypes: [] },
  { id: "risk-mgmt", title: "风控M4M5", taskTypes: ["scan_price_alerts", "scan_watchlist_gaps", "premarket_auction_notify", "premarket_open_notify"] },
  { id: "feedback-loop", title: "反馈闭环", taskTypes: ["daily_ai_summary", "daily_review_notify", "turso_sync", "healthcheck_ping", "cleanup_old_runs"] },
] as const;

const STATUS_STYLE: Record<string, string> = {
  success: "text-emerald-500",
  failed: "text-red-500 bg-red-500/5",
  running: "text-blue-500",
  timeout: "text-amber-500",
  idle: "text-muted-foreground",
};

function statusText(s: string | null | undefined): string {
  if (!s) return "—";
  return { success: "成功", failed: "失败", running: "运行中", timeout: "超时" }[s] ?? s;
}

function TaskRow({ task }: { task: ScheduledTask }) {
  const [expanded, setExpanded] = useState(false);
  const { data: runs } = useScheduledTaskRuns(task.id, 5, { enabled: expanded });
  const runList = (runs ?? []) as TaskRun[];
  const isFailed = task.last_run_status === "failed";

  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "cursor-pointer border-b border-border/30 transition-colors hover:bg-muted/20",
          isFailed && "bg-red-500/5",
        )}
      >
        <td className="py-2 pr-3">
          <span className="inline-flex items-center gap-1">
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {TASK_TYPE_CN[task.task_type] ?? task.name}
          </span>
        </td>
        <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">{task.cron_expr}</td>
        <td className="py-2 pr-3 text-xs text-muted-foreground">
          {task.last_run_at ? new Date(task.last_run_at).toLocaleString("zh-CN") : "—"}
        </td>
        <td className={cn("py-2 pr-3 text-xs font-medium", STATUS_STYLE[task.last_run_status ?? "idle"])}>
          {statusText(task.last_run_status)}
        </td>
        <td className="py-2 text-xs text-muted-foreground">
          {task.last_run_duration_ms ? `${(task.last_run_duration_ms / 1000).toFixed(1)}s` : "—"}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={5} className="bg-muted/10 px-6 py-3">
            {runList.length > 0 ? (
              <div className="space-y-2">
                {runList.map((run: TaskRun) => (
                  <div key={run.id} className="text-xs">
                    <div className="flex items-center gap-2">
                      <span className={cn("font-medium", STATUS_STYLE[run.status])}>
                        {statusText(run.status)}
                      </span>
                      <span className="text-muted-foreground">
                        {new Date(run.started_at).toLocaleString("zh-CN")}
                      </span>
                    </div>
                    {run.error && (
                      <pre className="mt-1 overflow-x-auto rounded bg-red-50 dark:bg-red-950/30 p-2 text-[11px] text-red-600 dark:text-red-400">
                        {run.error}
                      </pre>
                    )}
                    {run.result && Object.keys(run.result).length > 0 && (
                      <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                        {JSON.stringify(run.result, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">暂无运行记录</p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function PipelinePage() {
  const { data: tasks, isLoading } = useScheduledTasks();
  const taskList = (tasks ?? []) as ScheduledTask[];
  const failedCount = taskList.filter(t => t.last_run_status === "failed").length;

  return (
    <div>
      <PageHeader
        title="任务健康"
        subtitle={`9 步流程 · ${taskList.length} 定时任务${failedCount > 0 ? ` · ${failedCount} 失败` : ""}`}
      />

      {/* 失败告警 */}
      {failedCount > 0 && (
        <GlassCard tier="primary" className="mb-4">
          <h2 className="text-sm font-semibold text-red-500">失败告警 ({failedCount})</h2>
          <div className="mt-2 space-y-1">
            {taskList.filter(t => t.last_run_status === "failed").map(t => (
              <p key={t.id} className="text-xs text-red-500">
                ⚠ {TASK_TYPE_CN[t.task_type] ?? t.name} · 上次失败 · 点击下方表格行查看日志
              </p>
            ))}
          </div>
        </GlassCard>
      )}

      {/* 按步骤分组的任务表 */}
      {isLoading ? (
        <GlassCard className="py-12 text-center text-sm text-muted-foreground">加载定时任务…</GlassCard>
      ) : (
        <div className="space-y-4">
          {PIPELINE_STEPS.map(step => {
            const matched = taskList.filter(t => step.taskTypes.some(tt => tt === t.task_type));
            if (matched.length === 0) return null;
            const stepFailed = matched.some(t => t.last_run_status === "failed");
            return (
              <div key={step.id}>
                <h3 className={cn(
                  "mb-2 text-sm font-medium",
                  stepFailed ? "text-red-500" : "text-muted-foreground",
                )}>
                  {step.title}
                </h3>
                <GlassCard className="p-0">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                        <th className="py-2 pr-3 pl-4">任务名称</th>
                        <th className="py-2 pr-3">cron</th>
                        <th className="py-2 pr-3">上次运行</th>
                        <th className="py-2 pr-3">状态</th>
                        <th className="py-2 pr-4">耗时</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matched.map(task => (
                        <TaskRow key={task.id} task={task} />
                      ))}
                    </tbody>
                  </table>
                </GlassCard>
              </div>
            );
          })}
        </div>
      )}

      {/* 图例 */}
      <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground">
        {(["success", "failed", "running", "timeout"] as const).map(s => (
          <span key={s} className={cn("font-medium", STATUS_STYLE[s] ?? "")}>
            {statusText(s)}
          </span>
        ))}
        <span className="ml-auto">点击任务行展开运行日志</span>
      </div>
    </div>
  );
}
