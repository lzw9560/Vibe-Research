/**
 * S206 Pipeline 管线视图（N8N 风格节点图，React Flow + dagre 布局）
 *
 * 9 主节点环形布局（数据采集→图谱注入M7→因子计算→策略生成→回测验证§44v2→模拟盘→实盘→风控M4M5→反馈闭环→回数据采集）
 * 34 scheduled task 映射到 9 步子节点；点击主节点展开 subflow；点击子节点弹 Drawer 看 run history + 日志。
 * 参考：N8N（状态色+点击弹日志）/ LangFlow（子流程 group）/ Dify（连线数据流标注）/ ComfyUI（minimap）
 * 双语节点标题（对齐图谱 MOC quantitative-system/ 双语）。
 */
import { useState, useMemo, useCallback, type ReactNode } from "react";
import ReactFlow, {
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { Drawer, Collapse, Timeline, Badge, Tooltip } from "antd";
import {
  Database, Network, Calculator, Target, FlaskConical,
  TrendingUp, Send, ShieldCheck, RefreshCw, ChevronDown, ChevronRight,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { useScheduledTasks, useScheduledTaskRuns } from "@/lib/query";
import type { ScheduledTask, TaskRun } from "@/lib/api/types";

// ── 34 task 中文映射（补全 ScheduledTasks.tsx 的 TASK_TYPE_LABELS）──
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
  // S193 R4 + S206 新增
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

// ── 9 步流程定义（双语标题 + icon + 子 task 映射）──
interface PipelineStep {
  id: string;
  title: string;       // 中文
  titleEn: string;     // 英文注释
  icon: typeof Database;
  taskTypes: string[]; // 映射的 scheduled task type
}

const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: "data-collect", title: "数据采集", titleEn: "Data Collection",
    icon: Database,
    taskTypes: ["daily_full_pull", "kline_refresh", "baostock_5min_freeze", "ofi_collect", "intraday_microstructure_snapshot", "intraday_auction_dense"],
  },
  {
    id: "kg-inject", title: "图谱注入M7", titleEn: "Graph Inject (LLM Agent)",
    icon: Network,
    taskTypes: ["daily_kg_sync", "daily_kg_audit"],
  },
  {
    id: "factor-calc", title: "因子计算", titleEn: "Factor Calculation (AlphaEngine)",
    icon: Calculator,
    taskTypes: ["limitup_precompute", "candidate_funnel_precompute"],
  },
  {
    id: "strategy-gen", title: "策略生成", titleEn: "Strategy Generation",
    icon: Target,
    taskTypes: ["premarket_t1_review", "st_play_radar", "weekly_brainstorm_remind"],
  },
  {
    id: "backtest-verify", title: "回测验证§44v2", titleEn: "Backtest Verify (§44v2)",
    icon: FlaskConical,
    taskTypes: ["evaluation_backtest", "daily_backtest_run", "s066_validation_checkpoint"],
  },
  {
    id: "paper-trade", title: "模拟盘", titleEn: "Paper Trading",
    icon: TrendingUp,
    taskTypes: ["trade_journal_daily", "forward_test_daily"],
  },
  {
    id: "live-exec", title: "实盘执行", titleEn: "Live Execution (S192 不开户)",
    icon: Send,
    taskTypes: [], // S192 不开户，暂空
  },
  {
    id: "risk-mgmt", title: "风控M4M5", titleEn: "Risk Control (Circuit Breaker)",
    icon: ShieldCheck,
    taskTypes: ["scan_price_alerts", "scan_watchlist_gaps", "premarket_auction_notify", "premarket_open_notify"],
  },
  {
    id: "feedback-loop", title: "反馈闭环", titleEn: "Feedback Loop",
    icon: RefreshCw,
    taskTypes: ["daily_ai_summary", "daily_review_notify", "turso_sync", "healthcheck_ping", "cleanup_old_runs"],
  },
];

// ── 状态聚合：子 task 状态 → 主节点状态 ──
type StepStatus = "idle" | "running" | "done" | "failed";

function aggregateStatus(tasks: ScheduledTask[], taskTypes: string[]): StepStatus {
  const matched = tasks.filter((t) => taskTypes.includes(t.task_type));
  if (matched.length === 0) return "idle";
  const statuses = matched.map((t) => t.last_run_status);
  if (statuses.some((s) => s === "failed")) return "failed";
  if (statuses.some((s) => s === "running" || s === "timeout")) return "running";
  if (statuses.every((s) => s === "success")) return "done";
  return "idle";
}

const STATUS_COLOR: Record<StepStatus, string> = {
  idle: "#94a3b8",      // slate-400
  running: "#3b82f6",    // blue-500
  done: "#22c55e",      // green-500
  failed: "#ef4444",    // red-500
};

const STATUS_TEXT: Record<StepStatus, string> = {
  idle: "空闲", running: "运行中", done: "完成", failed: "失败",
};

// ── dagre 布局 ──
function layoutNodesEdges(steps: PipelineStep[], tasks: ScheduledTask[]) {
  const g = new dagre.daglib.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 80 });

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  steps.forEach((step, i) => {
    const status = aggregateStatus(tasks, step.taskTypes);
    const matchedTasks = tasks.filter((t) => step.taskTypes.includes(t.task_type));
    g.setNode(step.id, { width: 220, height: 100 });
    nodes.push({
      id: step.id,
      type: "pipelineStep",
      position: { x: 0, y: 0 },
      data: { step, status, taskCount: matchedTasks.length, tasks: matchedTasks },
    });
    // 连线到下一步
    if (i < steps.length - 1) {
      g.setEdge(step.id, steps[i + 1].id);
      edges.push({
        id: `e-${step.id}-${steps[i + 1].id}`,
        source: step.id,
        target: steps[i + 1].id,
        type: "smoothstep",
        animated: status === "running",
        style: { stroke: STATUS_COLOR[status], strokeWidth: 2 },
      });
    }
  });
  // 反馈闭环 → 数据采集（环形）
  g.setEdge(steps[steps.length - 1].id, steps[0].id);
  edges.push({
    id: "e-feedback",
    source: steps[steps.length - 1].id,
    target: steps[0].id,
    type: "bezier",
    animated: true,
    style: { stroke: "#6366f1", strokeWidth: 2, strokeDasharray: "5 5" },
    label: "反馈",
  });

  dagre.daglib.layout(g);
  const positioned = nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 110, y: pos.y - 50 } };
  });
  return { nodes: positioned, edges };
}

// ── 自定义主节点 ──
function PipelineStepNode({ data }: NodeProps) {
  const { step, status, taskCount } = data as {
    step: PipelineStep;
    status: StepStatus;
    taskCount: number;
  };
  const Icon = step.icon;
  return (
    <div
      className="rounded-xl border-2 bg-white/90 dark:bg-slate-800/90 shadow-lg backdrop-blur-sm transition-all hover:shadow-xl"
      style={{ borderColor: STATUS_COLOR[status], width: 220 }}
    >
      <Handle type="target" position={Position.Left} style={{ background: STATUS_COLOR[status] }} />
      <div className="flex items-center gap-2 p-3">
        <div
          className="flex h-9 w-9 items-center justify-center rounded-lg"
          style={{ backgroundColor: STATUS_COLOR[status] + "20" }}
        >
          <Icon className="h-5 w-5" style={{ color: STATUS_COLOR[status] }} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">
            {step.title}
          </div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
            {step.titleEn}
          </div>
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-slate-200/50 px-3 py-1.5">
        <Badge
          color={status === "done" ? "green" : status === "failed" ? "red" : status === "running" ? "blue" : "default"}
          text={<span className="text-[10px]">{STATUS_TEXT[status]}</span>}
        />
        <span className="text-[10px] text-slate-500">{taskCount} task</span>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: STATUS_COLOR[status] }} />
    </div>
  );
}

// ── 子节点 run history Drawer ──
function TaskRunDrawer({
  task,
  open,
  onClose,
}: {
  task: ScheduledTask | null;
  open: boolean;
  onClose: () => void;
}) {
  const { data: runs } = useScheduledTaskRuns(task?.id ?? 0, 20, {
    enabled: open && !!task,
  });

  const runList = runs ?? [];
  const cnTitle = task ? TASK_TYPE_CN[task.task_type] ?? task.name : "";

  return (
    <Drawer
      title={task ? `${cnTitle}（${task.task_type}）` : ""}
      open={open}
      onClose={onClose}
      width={480}
    >
      {task && (
        <div className="mb-3 text-xs text-slate-500">
          <p>cron: <code>{task.cron_expr}</code></p>
          <p>{task.description || "无描述"}</p>
          <p>启用: {task.enabled ? "是" : "否"} | 上次: {task.last_run_status ?? "—"}</p>
        </div>
      )}
      <h4 className="mb-2 text-sm font-medium">最近运行记录</h4>
      {runList.length > 0 ? (
        <Timeline
          items={runList.map((run: TaskRun) => ({
            color: run.status === "success" ? "green" : run.status === "failed" ? "red" : "blue",
            children: (
              <div key={run.id}>
                <div className="flex items-center gap-2">
                  <Badge
                    status={run.status === "success" ? "success" : run.status === "failed" ? "error" : "processing"}
                    text={run.status === "success" ? "成功" : run.status === "failed" ? "失败" : "运行中"}
                  />
                  <span className="text-xs text-slate-400">
                    {new Date(run.started_at).toLocaleString("zh-CN")}
                  </span>
                </div>
                {run.error && (
                  <pre className="mt-1 overflow-x-auto rounded bg-red-50 dark:bg-red-950/30 p-2 text-[11px] text-red-600 dark:text-red-400">
                    {run.error}
                  </pre>
                )}
                {run.result && Object.keys(run.result).length > 0 && (
                  <Collapse
                    size="small"
                    className="mt-1"
                    items={[{
                      key: "result",
                      label: "执行结果（result）",
                      children: (
                        <pre className="overflow-x-auto text-[11px]">
                          {JSON.stringify(run.result, null, 2)}
                        </pre>
                      ),
                    }]}
                  />
                )}
              </div>
            ),
          }))}
        />
      ) : (
        <p className="text-xs text-slate-400">暂无运行记录</p>
      )}
    </Drawer>
  );
}

const nodeTypes = { pipelineStep: PipelineStepNode };

function PipelineFlow() {
  const { data: tasks, isLoading } = useScheduledTasks();
  const [drawerTask, setDrawerTask] = useState<ScheduledTask | null>(null);
  const [expandedStep, setExpandedStep] = useState<string | null>(null);

  const taskList = tasks ?? [];
  const { nodes, edges } = useMemo(
    () => layoutNodesEdges(PIPELINE_STEPS, taskList),
    [taskList],
  );

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    const step = PIPELINE_STEPS.find((s) => s.id === node.id);
    if (!step) return;
    // 切换展开 subflow
    setExpandedStep(expandedStep === step.id ? null : step.id);
  }, [expandedStep]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="流程管线"
        subtitle="9 步端到端流程 + 34 定时任务状态（N8N 风格节点图）"
      />

      {/* 展开的 subflow 列表 */}
      {expandedStep && (
        <GlassCard className="p-4">
          <SubflowPanel
            stepId={expandedStep}
            tasks={taskList}
            onSelectTask={setDrawerTask}
          />
        </GlassCard>
      )}

      <GlassCard className="p-2">
        <div style={{ height: 600 }}>
          {isLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              加载定时任务…
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodeClick={onNodeClick}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
              <Controls showInteractive={false} />
              <MiniMap
                nodeColor={(n) => {
                  const status = (n.data as { status?: StepStatus })?.status;
                  return status ? STATUS_COLOR[status] : "#94a3b8";
                }}
                nodeStrokeWidth={3}
                className="rounded-lg"
              />
            </ReactFlow>
          )}
        </div>
      </GlassCard>

      {/* 图例 */}
      <div className="flex items-center gap-4 text-xs text-slate-500">
        {(["idle", "running", "done", "failed"] as StepStatus[]).map((s) => (
          <div key={s} className="flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-full" style={{ backgroundColor: STATUS_COLOR[s] }} />
            {STATUS_TEXT[s]}
          </div>
        ))}
        <span className="ml-auto">点击节点展开子工作流 | 反馈闭环虚线=环形回流</span>
      </div>

      <TaskRunDrawer
        task={drawerTask}
        open={!!drawerTask}
        onClose={() => setDrawerTask(null)}
      />
    </div>
  );
}

// ── 子工作流面板（展开的 task 列表）──
function SubflowPanel({
  stepId,
  tasks,
  onSelectTask,
}: {
  stepId: string;
  tasks: ScheduledTask[];
  onSelectTask: (t: ScheduledTask) => void;
}) {
  const step = PIPELINE_STEPS.find((s) => s.id === stepId);
  if (!step) return null;
  const Icon = step.icon;
  const matched = tasks.filter((t) => step.taskTypes.includes(t.task_type));

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-5 w-5 text-indigo-500" />
        <h3 className="text-sm font-semibold">{step.title} <span className="text-xs text-slate-400">({step.titleEn})</span></h3>
        <span className="text-xs text-slate-400">{matched.length} 个子任务</span>
      </div>
      {matched.length === 0 ? (
        <p className="text-xs text-slate-400">暂无映射任务（{step.title} 此步暂空）</p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {matched.map((t) => (
            <button
              key={t.id}
              onClick={() => onSelectTask(t)}
              className="flex items-center justify-between rounded-lg border border-slate-200/60 bg-slate-50/50 dark:bg-slate-800/50 p-2.5 text-left hover:border-indigo-300 hover:shadow-sm transition-all"
            >
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium truncate">{TASK_TYPE_CN[t.task_type] ?? t.name}</div>
                <div className="text-[10px] text-slate-400 truncate">{t.task_type}</div>
              </div>
              <Badge
                status={
                  t.last_run_status === "success" ? "success"
                  : t.last_run_status === "failed" ? "error"
                  : t.last_run_status === "running" ? "processing"
                  : "default"
                }
              />
            </button>
          ))}
        </div>
      )}
      <p className="mt-2 text-[10px] text-slate-400">点击任务卡查看运行记录 + 执行日志（result/error）</p>
    </div>
  );
}

export function PipelinePage() {
  return (
    <ReactFlowProvider>
      <PipelineFlow />
    </ReactFlowProvider>
  );
}
