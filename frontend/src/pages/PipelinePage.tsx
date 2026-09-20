// 多维度 IA: PipelinePage — fork-aware 图（9步骨架+5线横穿+fork岔路）
// supersede Track B flat 表: @xyflow/react + @dagrejs/dagre
// 9步骨架(数据→图谱M7→因子→策略→§44→模拟→实盘→风控→反馈)
// fork 岔路: §44 validated/待验证/证否; 策略 短线/中线/长线
// 当前路径高亮, 点 fork 看分支; 5 线横穿(各走一段+绕回起点)
// 下方保留 task 健康表(折叠, 保 Track B 功能)
import { useState, useMemo } from "react";
import { ReactFlow, Background, Controls, MiniMap, type Node, type Edge, type NodeProps, Handle, Position } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { ChevronDown, ChevronRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { useScheduledTasks, useScheduledTaskRuns } from "@/lib/query";
import type { ScheduledTask, TaskRun } from "@/lib/api/types";
import { cn } from "@/lib/utils";

// ── 9步骨架定义 ──────────────────────────────────────────────────────────────
interface StepDef {
  id: string;
  label: string;
  taskTypes: string[];
  fork?: "s44" | "strategy";  // fork 节点标记
}

const BACKBONE_STEPS: readonly StepDef[] = [
  { id: "data-collect", label: "数据采集", taskTypes: ["daily_full_pull", "kline_refresh", "baostock_5min_freeze", "ofi_collect", "intraday_microstructure_snapshot", "intraday_auction_dense"] },
  { id: "kg-inject", label: "图谱注入M7", taskTypes: ["daily_kg_sync", "daily_kg_audit"] },
  { id: "factor-calc", label: "因子计算", taskTypes: ["limitup_precompute", "candidate_funnel_precompute"] },
  { id: "strategy-gen", label: "策略生成", taskTypes: ["premarket_t1_review", "st_play_radar", "weekly_brainstorm_remind"], fork: "strategy" },
  { id: "backtest-verify", label: "回测验证§44", taskTypes: ["evaluation_backtest", "daily_backtest_run", "s066_validation_checkpoint"], fork: "s44" },
  { id: "paper-trade", label: "模拟盘", taskTypes: ["trade_journal_daily", "forward_test_daily"] },
  { id: "live-exec", label: "实盘执行", taskTypes: [] },
  { id: "risk-mgmt", label: "风控M4M5", taskTypes: ["scan_price_alerts", "scan_watchlist_gaps", "premarket_auction_notify", "premarket_open_notify"] },
  { id: "feedback-loop", label: "反馈闭环", taskTypes: ["daily_ai_summary", "daily_review_notify", "turso_sync", "healthcheck_ping", "cleanup_old_runs"] },
] as const;

// ── fork 分支节点 ────────────────────────────────────────────────────────────
interface ForkDef {
  id: string;
  parentId: string;
  label: string;
  status: "validated" | "pending" | "falsified" | "short" | "mid" | "long";
  target?: string;  // 连回的目标节点
  detail: string;
}

const FORK_NODES: readonly ForkDef[] = [
  // §44 fork
  { id: "s44-validated", parentId: "backtest-verify", label: "validated", status: "validated", target: "paper-trade", detail: "§44 lift≥2x · 可执行交易" },
  { id: "s44-pending", parentId: "backtest-verify", label: "待验证", status: "pending", target: "paper-trade", detail: "lift<2x 或 n不足 · 记日志待复验" },
  { id: "s44-falsified", parentId: "backtest-verify", label: "已证否", status: "falsified", target: "factor-calc", detail: "§44 证否 · 调因子回炉" },
  // 策略 fork
  { id: "strategy-short", parentId: "strategy-gen", label: "短线打板", status: "short", target: "backtest-verify", detail: "selection 层 S168" },
  { id: "strategy-mid", parentId: "strategy-gen", label: "中线event", status: "mid", target: "backtest-verify", detail: "event 层 S169+S170" },
  { id: "strategy-long", parentId: "strategy-gen", label: "长线价值", status: "long", target: "backtest-verify", detail: "long_value 层 S171" },
] as const;

// ── 5 线横穿定义 ────────────────────────────────────────────────────────────
interface LinePathDef {
  key: string;
  label: string;
  color: string;
  steps: string[];  // 走过的 backbone 节点 id
}

const LINE_PATHS: readonly LinePathDef[] = [
  { key: "time", label: "时间线", color: "#3b82f6", steps: ["data-collect", "kg-inject", "factor-calc", "strategy-gen", "backtest-verify", "paper-trade", "feedback-loop"] },
  { key: "selection", label: "选股线", color: "#8b5cf6", steps: ["data-collect", "factor-calc", "strategy-gen"] },
  { key: "validation", label: "验证线", color: "#f59e0b", steps: ["factor-calc", "backtest-verify", "feedback-loop"] },
  { key: "strategy", label: "策略线", color: "#10b981", steps: ["strategy-gen", "backtest-verify", "paper-trade", "feedback-loop"] },
  { key: "cognition", label: "认知线", color: "#ec4899", steps: ["data-collect", "kg-inject", "feedback-loop"] },
] as const;

// ── dagre auto-layout ─────────────────────────────────────────────────────────
function useLayoutedNodes(): { nodes: Node[]; edges: Edge[] } {
  return useMemo(() => {
    const nodeWidth = 160;
    const nodeHeight = 48;
    const forkWidth = 130;
    const forkHeight = 36;

    // 构建所有节点
    const allNodes: { id: string; width: number; height: number }[] = [
      ...BACKBONE_STEPS.map(s => ({ id: s.id, width: nodeWidth, height: nodeHeight })),
      ...FORK_NODES.map(f => ({ id: f.id, width: forkWidth, height: forkHeight })),
    ];

    // 构建所有边
    const allEdges: { source: string; target: string; id: string }[] = [];

    // backbone 顺序边
    for (let i = 0; i < BACKBONE_STEPS.length - 1; i++) {
      allEdges.push({ source: BACKBONE_STEPS[i].id, target: BACKBONE_STEPS[i + 1].id, id: `e-${BACKBONE_STEPS[i].id}-${BACKBONE_STEPS[i + 1].id}` });
    }
    // feedback → data (loop back)
    allEdges.push({ source: "feedback-loop", target: "data-collect", id: "e-feedback-loop-data-collect" });

    // fork 边
    FORK_NODES.forEach(f => {
      allEdges.push({ source: f.parentId, target: f.id, id: `e-fork-${f.id}` });
      if (f.target) {
        allEdges.push({ source: f.id, target: f.target, id: `e-forkret-${f.id}` });
      }
    });

    // dagre layout
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 80, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    allNodes.forEach(n => g.setNode(n.id, { width: n.width, height: n.height }));
    allEdges.forEach(e => g.setEdge(e.source, e.target));
    dagre.layout(g);

    // 构建 ReactFlow nodes
    const nodes: Node[] = [
      ...BACKBONE_STEPS.map((s, i) => {
        const pos = g.node(s.id);
        return {
          id: s.id,
          type: "backbone",
          position: { x: pos.x - nodeWidth / 2, y: pos.y - nodeHeight / 2 },
          data: { label: s.label, step: i + 1, taskTypes: s.taskTypes, fork: s.fork },
        };
      }),
      ...FORK_NODES.map(f => {
        const pos = g.node(f.id);
        return {
          id: f.id,
          type: "fork",
          position: { x: pos.x - forkWidth / 2, y: pos.y - forkHeight / 2 },
          data: { label: f.label, status: f.status, detail: f.detail, parentId: f.parentId, target: f.target },
        };
      }),
    ];

    // 构建 edges（fork 边用虚线, loop 用弯曲）
    const edges: Edge[] = [
      // backbone 边
      ...BACKBONE_STEPS.slice(0, -1).map((s, i) => ({
        id: `e-${s.id}-${BACKBONE_STEPS[i + 1].id}`,
        source: s.id,
        target: BACKBONE_STEPS[i + 1].id,
        type: "smoothstep",
        animated: false,
        style: { stroke: "#64748b", strokeWidth: 1.5 },
      })),
      // loop back
      {
        id: "e-feedback-loop-data-collect",
        source: "feedback-loop",
        target: "data-collect",
        type: "smoothstep",
        animated: true,
        style: { stroke: "#64748b", strokeWidth: 1, strokeDasharray: "5 5" },
        label: "loop",
      },
      // fork 边
      ...FORK_NODES.flatMap(f => {
        const edges: Edge[] = [{
          id: `e-fork-${f.id}`,
          source: f.parentId,
          target: f.id,
          type: "smoothstep",
          style: { stroke: forkColor(f.status), strokeWidth: 1.5, strokeDasharray: "4 4" },
        }];
        if (f.target) {
          edges.push({
            id: `e-forkret-${f.id}`,
            source: f.id,
            target: f.target,
            type: "smoothstep",
            style: { stroke: forkColor(f.status), strokeWidth: 1, opacity: 0.5 },
          });
        }
        return edges;
      }),
    ];

    return { nodes, edges };
  }, []);
}

function forkColor(status: string): string {
  switch (status) {
    case "validated": return "#10b981";
    case "pending": return "#f59e0b";
    case "falsified": return "#ef4444";
    case "short": return "#ef4444";
    case "mid": return "#f59e0b";
    case "long": return "#3b82f6";
    default: return "#64748b";
  }
}

// ── 自定义节点组件 ───────────────────────────────────────────────────────────

function BackboneNode({ data }: NodeProps) {
  const d = data as { label: string; step: number; taskTypes: string[]; fork?: string };
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border px-3 py-2 transition-all",
        d.fork === "s44" ? "border-amber-500/60"
        : d.fork === "strategy" ? "border-emerald-500/60"
        : "border-border/60",
      )}
      style={{ width: 160 }}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-muted-foreground" />
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
        {d.step}
      </span>
      <span className="text-sm font-bold text-primary">{d.label}</span>
      {d.fork && (
        <span className="ml-auto text-[9px] text-foreground/70">fork</span>
      )}
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-muted-foreground" />
    </div>
  );
}

function ForkNode({ data }: NodeProps) {
  const d = data as { label: string; status: string; detail: string };
  const color = forkColor(d.status);
  return (
    <div
      className="flex items-center gap-1.5 rounded-full border-2 px-2.5 py-1 shadow-sm"
      style={{ width: 130, borderColor: color }}
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0" style={{ background: color }} />
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      <span className="text-xs font-medium" style={{ color }}>{d.label}</span>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0" style={{ background: color }} />
    </div>
  );
}

const nodeTypes = { backbone: BackboneNode, fork: ForkNode } as const;

// ── 线横穿图例 ───────────────────────────────────────────────────────────────

function LineLegend({ activeLine, setActiveLine }: { activeLine: string | null; setActiveLine: (k: string | null) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {LINE_PATHS.map(line => (
        <button
          key={line.key}
          onClick={() => setActiveLine(activeLine === line.key ? null : line.key)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
            activeLine === line.key ? "border-foreground/30 bg-foreground/5" : "border-border/40 hover:bg-muted/20",
          )}
        >
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: line.color }} />
          {line.label}
          <span className="opacity-80">({line.steps.length}步)</span>
        </button>
      ))}
    </div>
  );
}

// ── PipelinePage 主组件 ──────────────────────────────────────────────────────

export function PipelinePage() {
  const { nodes: layoutedNodes, edges: layoutedEdges } = useLayoutedNodes();
  const [activeLine, setActiveLine] = useState<string | null>(null);
  const [showTaskTable, setShowTaskTable] = useState(false);

  // 高亮当前线的边
  const edges = useMemo(() => {
    if (!activeLine) return layoutedEdges;
    const lineDef = LINE_PATHS.find(l => l.key === activeLine);
    if (!lineDef) return layoutedEdges;

    return layoutedEdges.map(e => {
      const srcIdx = lineDef.steps.indexOf(e.source);
      const tgtIdx = lineDef.steps.indexOf(e.target);
      // 如果边连接的两个节点都在线的步骤中且相邻, 高亮
      if (srcIdx >= 0 && tgtIdx >= 0 && Math.abs(srcIdx - tgtIdx) === 1) {
        return { ...e, style: { ...e.style, stroke: lineDef.color, strokeWidth: 3 }, animated: true };
      }
      // 暗化非当前线的边
      return { ...e, style: { ...e.style, opacity: 0.15 } };
    });
  }, [layoutedEdges, activeLine]);

  // 高亮当前线的节点
  const nodes = useMemo(() => {
    if (!activeLine) return layoutedNodes;
    const lineDef = LINE_PATHS.find(l => l.key === activeLine);
    if (!lineDef) return layoutedNodes;
    return layoutedNodes.map(n => {
      if (lineDef.steps.includes(n.id)) {
        return { ...n, style: { ...n.style, boxShadow: `0 0 0 2px ${lineDef.color}40` } };
      }
      return { ...n, style: { ...n.style, opacity: 0.3 } };
    });
  }, [layoutedNodes, activeLine]);

  return (
    <div>
      <PageHeader
        title="流程管线"
        subtitle="9步骨架 + 5线横穿 + fork 岔路（§44 validated/待验证/证否 · 策略 短线/中线/长线）"
      />

      {/* 线横穿图例 */}
      <div className="mb-3">
        <LineLegend activeLine={activeLine} setActiveLine={setActiveLine} />
      </div>

      {/* fork-aware 图 */}
      <GlassCard className="mb-4 p-0">
        <div style={{ height: 400 }} className="rounded-lg">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            minZoom={0.3}
            maxZoom={1.5}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#94a3b8" gap={20} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) => {
                if (n.type === "fork") {
                  const d = n.data as { status: string };
                  return forkColor(d.status);
                }
                return "#64748b";
              }}
              className="!bg-muted/30"
            />
          </ReactFlow>
        </div>
      </GlassCard>

      {/* fork 说明 */}
      <GlassCard tier="sub" className="mb-4">
        <h3 className="mb-2 text-xs font-semibold">fork 岔路说明</h3>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <p className="text-xs font-medium text-amber-500">§44 验证 fork</p>
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              <li><span className="text-emerald-500">●</span> validated: lift≥2x → 模拟盘可执行</li>
              <li><span className="text-amber-500">●</span> 待验证: lift&lt;2x 或 n不足 → 记日志待复验</li>
              <li><span className="text-red-500">●</span> 已证否: 调因子回炉</li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-medium text-emerald-500">策略 fork</p>
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              <li><span className="text-red-500">●</span> 短线打板: selection 层 S168</li>
              <li><span className="text-amber-500">●</span> 中线event: event 层 S169+S170</li>
              <li><span className="text-blue-500">●</span> 长线价值: long_value 层 S171</li>
            </ul>
          </div>
        </div>
      </GlassCard>

      {/* task 健康表（折叠, 保 Track B 功能） */}
      <div>
        <button
          onClick={() => setShowTaskTable(!showTaskTable)}
          className="flex w-full items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          {showTaskTable ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          任务健康表（{BACKBONE_STEPS.reduce((acc, s) => acc + s.taskTypes.length, 0)} 定时任务）
        </button>
        {showTaskTable && (
          <div className="mt-2">
            <TaskHealthTable />
          </div>
        )}
      </div>
    </div>
  );
}

// ── task 健康表（Track B 保留功能, 折叠在图下方）─────────────────────────────

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
                      <pre className="mt-1 overflow-x-auto rounded bg-red-50 dark:bg-red-950/30 p-2 text-xs text-red-600 dark:text-red-400">
                        {run.error}
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

function TaskHealthTable() {
  const { data: tasks, isLoading } = useScheduledTasks();
  const taskList = (tasks ?? []) as ScheduledTask[];
  const failedCount = taskList.filter(t => t.last_run_status === "failed").length;

  if (isLoading) {
    return <GlassCard className="py-12 text-center text-sm text-muted-foreground">加载定时任务…</GlassCard>;
  }

  return (
    <div className="space-y-4">
      {failedCount > 0 && (
        <GlassCard tier="primary">
          <h2 className="text-sm font-semibold text-red-500">失败告警 ({failedCount})</h2>
          <div className="mt-2 space-y-1">
            {taskList.filter(t => t.last_run_status === "failed").map(t => (
              <p key={t.id} className="text-xs text-red-500">
                ⚠ {TASK_TYPE_CN[t.task_type] ?? t.name} · 点击下方表格行查看日志
              </p>
            ))}
          </div>
        </GlassCard>
      )}
      {BACKBONE_STEPS.map(step => {
        const matched = taskList.filter(t => step.taskTypes.some(tt => tt === t.task_type));
        if (matched.length === 0) return null;
        const stepFailed = matched.some(t => t.last_run_status === "failed");
        return (
          <div key={step.id}>
            <h3 className={cn("mb-2 text-sm font-medium", stepFailed ? "text-red-500" : "text-muted-foreground")}>
              {step.label}
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
                  {matched.map(task => <TaskRow key={task.id} task={task} />)}
                </tbody>
              </table>
            </GlassCard>
          </div>
        );
      })}
    </div>
  );
}
