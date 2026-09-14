// 多维度 IA: /graph — 认知线（M7 LLM 图谱智能体）
// M7 读公告→JSON→inbox 待审→reference→反哺策略→新信号，图谱闭环
// 数据源: useScheduledTasks(daily_kg_sync/daily_kg_audit) + honest-empty 21 实体 browse
// 图谱本体在 Obsidian Vault（私有），前端看注入/同步状态 + 实体列表占位
import { Link } from "react-router-dom";
import { Brain, FileSearch, Inbox, BookMarked, RefreshCw, ArrowRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { LineLoopCard } from "@/components/lines/LineLoopCard";
import { LineStatusLight } from "@/components/lines/LineStatusLight";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { useScheduledTasks } from "@/lib/query";
import { LINES } from "@/components/lines/lines";
import { cn } from "@/lib/utils";

// 21 实体类（投研知识图谱，Obsidian Vault）
const ENTITY_TYPES = [
  { key: "strategies", label: "战法", count: null as number | null },
  { key: "data-sources", label: "数据源", count: null },
  { key: "signals", label: "信号", count: null },
  { key: "factors", label: "因子", count: null },
  { key: "indicators", label: "指标", count: null },
  { key: "regimes", label: "市场状态", count: null },
  { key: "risks", label: "风险", count: null },
  { key: "edges", label: "关系", count: null },
  { key: "logic-rules", label: "逻辑规则", count: null },
  { key: "actions", label: "动作", count: null },
  { key: "reviews", label: "审查报告", count: null },
  { key: "specs", label: "规范", count: null },
  { key: "portfolios", label: "组合", count: null },
  { key: "positions", label: "持仓", count: null },
  { key: "sectors", label: "板块", count: null },
  { key: "concepts", label: "概念", count: null },
  { key: "events", label: "事件", count: null },
  { key: "announcements", label: "公告", count: null },
  { key: "instruments", label: "标的", count: null },
  { key: "trades", label: "交易", count: null },
  { key: "journals", label: "日志", count: null },
] as const;

// kg 同步任务状态
function useKgSyncStatus() {
  const { data: tasks } = useScheduledTasks();
  const taskList = tasks ?? [];
  const syncTask = taskList.find(t => t.task_type === "daily_kg_sync");
  const auditTask = taskList.find(t => t.task_type === "daily_kg_audit");
  return { syncTask, auditTask, taskList };
}

export function CognitionPage() {
  const { syncTask, auditTask } = useKgSyncStatus();
  const cognitionLine = LINES[4];

  // 注入状态: sync task 上次成功 = ok, 失败 = alert, 无 = idle
  const syncStatus = syncTask?.last_run_status === "success" ? "ok"
    : syncTask?.last_run_status === "failed" ? "alert"
    : "idle";
  const auditStatus = auditTask?.last_run_status === "success" ? "ok"
    : auditTask?.last_run_status === "failed" ? "alert"
    : "idle";

  return (
    <div>
      <PageHeader
        title="图谱"
        subtitle="认知线 · M7 LLM 读公告→JSON→inbox→reference→反哺策略→新信号"
        actions={<RefreshCw className="h-4 w-4 text-muted-foreground" />}
      />

      {/* 认知线闭环卡 */}
      <div className="mb-4">
        <LineLoopCard
          title="认知线闭环"
          subtitle="M7读公告→JSON注入→inbox待审→reference→反哺策略→新信号→(loop)"
          steps={cognitionLine.steps}
          currentStep={2}
          icon={<Brain className="h-3.5 w-3.5 text-muted-foreground" />}
        />
      </div>

      {/* M7 注入状态 */}
      <GlassCard tier="primary" className="mb-4">
        <div className="mb-3 flex items-center gap-2">
          <FileSearch className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">M7 注入状态</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {/* 图谱同步 */}
          <LineStatusLight
            lineKey="kg-sync"
            label="图谱日同步"
            status={syncStatus}
            detail={syncTask?.last_run_at ? `上次: ${new Date(syncTask.last_run_at).toLocaleString("zh-CN")}` : "待接线"}
            link="/pipeline"
          />
          {/* 图谱审计 */}
          <LineStatusLight
            lineKey="kg-audit"
            label="图谱日审计"
            status={auditStatus}
            detail={auditTask?.last_run_at ? `上次: ${new Date(auditTask.last_run_at).toLocaleString("zh-CN")}` : "待接线"}
            link="/pipeline"
          />
        </div>
        <div className="mt-3">
          <p className="text-xs text-muted-foreground">
            M7 = LLM 图谱智能体（DeepSeek 公告→JSON→图谱注入，捕获暗线概念股）。
            图谱本体在 Obsidian Vault（私有，GitHub 同步仓 lzw9560/knowledge），前端看注入/同步状态。
          </p>
        </div>
      </GlassCard>

      {/* inbox 待审 + reference 流转 */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <GlassCard>
          <div className="mb-2 flex items-center gap-2">
            <Inbox className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-semibold">inbox 待审</h3>
          </div>
          <HonestEmptyState
            message="M7 注入的公告 JSON 待审队列"
            hint="需后端 /api/kg/inbox endpoint，当前无 direct API。图谱注入后 inbox 待审状态由 Obsidian Vault reviews/ 目录管理"
          />
        </GlassCard>
        <GlassCard>
          <div className="mb-2 flex items-center gap-2">
            <BookMarked className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">reference 流转</h3>
          </div>
          <HonestEmptyState
            message="inbox→active→reference 流转状态"
            hint="四构件（实体/关系/逻辑规则/动作）中的动作构件管理流转，当前由 Obsidian Vault 管理"
          />
        </GlassCard>
      </div>

      {/* 21 实体 browse */}
      <GlassCard className="mb-4">
        <h3 className="mb-3 text-sm font-semibold">21 实体类（图谱 browse）</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {ENTITY_TYPES.map(ent => (
            <div
              key={ent.key}
              className="flex items-center gap-2 rounded-lg border border-border/30 bg-muted/10 px-2.5 py-2"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
              <span className="text-xs font-medium">{ent.label}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">待接线</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">
          实体类对应 Obsidian Vault investing/ 子目录。前端 browse 需后端 /api/kg/entities endpoint（待接线），
          当前看图谱本体去 Obsidian Vault。
        </p>
      </GlassCard>

      {/* 图谱闭环状态 */}
      <GlassCard tier="sub" className="mb-4">
        <h3 className="mb-2 text-xs font-semibold">图谱闭环状态</h3>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className={cn("h-1.5 w-1.5 rounded-full", syncStatus === "ok" ? "bg-emerald-500" : "bg-amber-500")} />
            同步{syncStatus === "ok" ? "正常" : "待查"}
          </span>
          <ArrowRight className="h-2.5 w-2.5" />
          <span>注入→inbox→reference→反哺策略→新信号</span>
          <ArrowRight className="h-2.5 w-2.5" />
          <Link to="/review?tab=strategy" className="text-primary">→ 策略</Link>
          <Link to="/review?tab=validation" className="text-primary">→ 验证</Link>
        </div>
      </GlassCard>

      {/* CTA 脊 */}
      <NextStepBar pageCtx="cognition" />
    </div>
  );
}
