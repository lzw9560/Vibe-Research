// 多维度 IA: /graph — 认知线（M7 LLM 图谱智能体）
// M7 读公告→JSON→inbox 待审→reference→反哺策略→新信号，图谱闭环
// S216 P1 接线：/api/kg/inbox + /api/kg/entities（tab 切换类型）+ /api/kg/flow（输入 code 查关系）
// 复用 kg_tools 读 Obsidian Vault，只返图谱客观数据（实体 frontmatter/关系链接）
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Brain, FileSearch, Inbox, BookMarked, RefreshCw, ArrowRight, Search } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { LineLoopCard } from "@/components/lines/LineLoopCard";
import { LineStatusLight } from "@/components/lines/LineStatusLight";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { useScheduledTasks } from "@/lib/query";
import { LINES } from "@/components/lines/lines";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

// 实体类 tab（kg_tools _FOLDER_MAP 支持的类型）
const ENTITY_TYPES = [
  { key: "stock", label: "股票" },
  { key: "strategy", label: "战法" },
  { key: "concept", label: "概念" },
  { key: "industry", label: "行业" },
  { key: "spec", label: "规范" },
  { key: "data_source", label: "数据源" },
  { key: "event", label: "事件" },
  { key: "analyst", label: "分析师" },
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
  const [selectedType, setSelectedType] = useState<string>("stock");
  const [flowCode, setFlowCode] = useState("600519");

  const syncStatus = syncTask?.last_run_status === "success" ? "ok"
    : syncTask?.last_run_status === "failed" ? "alert"
    : "idle";
  const auditStatus = auditTask?.last_run_status === "success" ? "ok"
    : auditTask?.last_run_status === "failed" ? "alert"
    : "idle";

  // S216 P1: 三 endpoint 接线
  const inboxQ = useQuery({
    queryKey: ["kg", "inbox"] as const,
    queryFn: () => api.kgInbox(),
  });
  const entitiesQ = useQuery({
    queryKey: ["kg", "entities", selectedType] as const,
    queryFn: () => api.kgEntities(selectedType),
  });
  const flowQ = useQuery({
    queryKey: ["kg", "flow", flowCode] as const,
    queryFn: () => api.kgFlow(flowCode),
    enabled: !!flowCode,
  });

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
          <LineStatusLight
            lineKey="kg-sync"
            label="图谱日同步"
            status={syncStatus}
            detail={syncTask?.last_run_at ? `上次: ${new Date(syncTask.last_run_at).toLocaleString("zh-CN")}` : "待接线"}
            link="/pipeline"
          />
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

      {/* inbox 待审 + flow 关系流 */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <GlassCard>
          <div className="mb-2 flex items-center gap-2">
            <Inbox className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-semibold">inbox 待审</h3>
            <span className="ml-auto text-xs text-muted-foreground">
              {inboxQ.data?.count ?? 0} 条
            </span>
          </div>
          {inboxQ.isLoading && (
            <span className="text-xs text-muted-foreground">加载中…</span>
          )}
          {inboxQ.error && !inboxQ.isLoading && (
            <span className="text-xs text-red-500">inbox 加载失败</span>
          )}
          {!inboxQ.isLoading && !inboxQ.error &&
            inboxQ.data && inboxQ.data.count > 0 ? (
            <ul className="space-y-1">
              {inboxQ.data.entities.slice(0, 10).map((e) => (
                <li key={e._filename} className="text-xs">
                  <span className="font-medium">{e._filename}</span>
                  {e.name && <span className="text-muted-foreground"> {e.name}</span>}
                </li>
              ))}
              {inboxQ.data.count > 10 && (
                <li className="text-[11px] text-muted-foreground">
                  …共 {inboxQ.data.count} 条，去 Obsidian Vault 查看
                </li>
              )}
            </ul>
          ) : (
            !inboxQ.isLoading && !inboxQ.error && (
              <HonestEmptyState
                message="inbox 无待审实体"
                hint={inboxQ.data?.note ?? "M7 注入后 inbox 待审状态由图谱管理"}
              />
            )
          )}
        </GlassCard>
        <GlassCard>
          <div className="mb-2 flex items-center gap-2">
            <BookMarked className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">实体关系流</h3>
          </div>
          <div className="mb-2 flex items-center gap-1">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={flowCode}
              onChange={(e) => setFlowCode(e.target.value)}
              placeholder="实体代码，如 600519"
              className="w-full rounded border border-border bg-transparent px-2 py-1 text-xs"
            />
          </div>
          {flowQ.isLoading && (
            <span className="text-xs text-muted-foreground">加载中…</span>
          )}
          {flowQ.error && !flowQ.isLoading && (
            <span className="text-xs text-red-500">关系流加载失败</span>
          )}
          {!flowQ.isLoading && !flowQ.error && flowQ.data && flowQ.data.total > 0 ? (
            <div>
              <p className="text-xs text-muted-foreground">
                {flowQ.data.entity} · {flowQ.data.total} 关联
              </p>
              <ul className="mt-1 space-y-1">
                {flowQ.data.relations.slice(0, 8).map((r) => (
                  <li key={r.target} className="text-xs">
                    <span className="text-primary">{r.target}</span>
                  </li>
                ))}
                {flowQ.data.total > 8 && (
                  <li className="text-[11px] text-muted-foreground">
                    …共 {flowQ.data.total} 关联
                  </li>
                )}
              </ul>
            </div>
          ) : (
            !flowQ.isLoading && !flowQ.error && (
              <HonestEmptyState
                message={flowQ.data?.total === 0 ? `${flowCode} 无关联实体` : "输入实体代码查关系流"}
                hint={flowQ.data?.path ?? "[[]] 链接列表，图谱客观关系"}
              />
            )
          )}
        </GlassCard>
      </div>

      {/* 实体类 browse（tab 切换 type） */}
      <GlassCard className="mb-4">
        <h3 className="mb-3 text-sm font-semibold">实体类（图谱 browse）</h3>
        <div className="mb-3 flex flex-wrap gap-1">
          {ENTITY_TYPES.map((t) => (
            <button
              key={t.key}
              onClick={() => setSelectedType(t.key)}
              className={cn(
                "rounded border px-2 py-0.5 text-xs",
                selectedType === t.key
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        {entitiesQ.isLoading && (
          <span className="text-xs text-muted-foreground">加载中…</span>
        )}
        {entitiesQ.error && !entitiesQ.isLoading && (
          <span className="text-xs text-red-500">实体列表加载失败</span>
        )}
        {!entitiesQ.isLoading && !entitiesQ.error &&
          entitiesQ.data && entitiesQ.data.count > 0 ? (
          <div>
            <p className="mb-2 text-xs text-muted-foreground">
              {selectedType} · {entitiesQ.data.count} 实体
            </p>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
              {entitiesQ.data.entities.slice(0, 50).map((e) => (
                <div
                  key={e._filename}
                  className="rounded border border-border/30 bg-muted/10 px-2 py-1.5"
                >
                  <div className="text-xs font-medium">{e.name || e._filename}</div>
                  {e.code && (
                    <div className="text-[10px] text-muted-foreground">{e.code}</div>
                  )}
                </div>
              ))}
            </div>
            {entitiesQ.data.count > 50 && (
              <p className="mt-2 text-[11px] text-muted-foreground">
                …共 {entitiesQ.data.count} 实体，去 Obsidian Vault 查看
              </p>
            )}
          </div>
        ) : (
          !entitiesQ.isLoading && !entitiesQ.error && (
            <HonestEmptyState
              message={`${selectedType} 无实体`}
              hint="该类型图谱无实体或文件夹为空"
            />
          )
        )}
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
