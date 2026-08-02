import { useState } from "react";
import { Plus, Play, Trash2, RefreshCw, Clock, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { toast } from "sonner";
import {
  createScheduledTask,
  updateScheduledTask,
  deleteScheduledTask,
  runScheduledTaskNow,
  type ScheduledTask,
} from "@/lib/api";
import { useScheduledTasks, useScheduledTaskRuns } from "@/lib/query";

const TASK_TYPE_LABELS: Record<string, string> = {
  daily_data_refresh: "每日数据刷新",
  daily_review_notify: "每日复盘通知",
  limitup_precompute: "盘后预计算",
  portfolio_refresh: "持仓刷新",
  market_data_sync: "市场数据同步",
  cleanup_old_runs: "清理旧运行记录",
};

export function ScheduledTasks() {
  // T9：原 useState/useEffect + getScheduledTasks/getScheduledTaskRuns
  //   → useScheduledTasks / useScheduledTaskRuns。写操作保留直接调用，
  //   成功后用 hook 的 refetch 刷新。runs hook 在 expandedTaskId 为空时
  //   由其 enabled: !!id 自动禁用（传 0 即 falsy）。
  // 注：hook 的 queryFn 返回 Promise<ScheduledTask[]>/Promise<TaskRun[]>，
  //   但 options 透传泛型摩擦使 useQuery 推断为 {}，就地窄→宽 cast（同 Health.tsx 模板）。
  const [runningId, setRunningId] = useState<number | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<number | null>(null);

  const {
    data: tasks,
    isLoading: loading,
    error: tasksError,
    refetch: refetchTasks,
  } = useScheduledTasks();
  const { data: runs, refetch: refetchRuns } = useScheduledTaskRuns(
    expandedTaskId ?? 0,
    20,
  );

  // Form state
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formType, setFormType] = useState("daily_data_refresh");
  const [formCron, setFormCron] = useState("0 17 * * *");
  const [formNotifySuccess, setFormNotifySuccess] = useState(false);
  const [formNotifyFailure, setFormNotifyFailure] = useState(true);
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    if (!formName.trim() || !formCron.trim()) {
      toast.error("请填写任务名称和 cron 表达式");
      return;
    }
    setSaving(true);
    try {
      await createScheduledTask({
        name: formName.trim(),
        description: formDesc.trim(),
        task_type: formType,
        cron_expr: formCron.trim(),
        payload: {},
        enabled: true,
        notify_on_success: formNotifySuccess,
        notify_on_failure: formNotifyFailure,
      });
      toast.success("任务已创建");
      setShowForm(false);
      setFormName("");
      setFormDesc("");
      setFormCron("0 17 * * *");
      setFormNotifySuccess(false);
      setFormNotifyFailure(true);
      await refetchTasks();
    } catch {
      toast.error("创建任务失败");
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (task: ScheduledTask) => {
    try {
      await updateScheduledTask(task.id, { enabled: !task.enabled });
      await refetchTasks();
      toast.success(task.enabled ? "任务已禁用" : "任务已启用");
    } catch {
      toast.error("更新任务状态失败");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("确定删除此任务？")) return;
    try {
      await deleteScheduledTask(id);
      await refetchTasks();
      toast.success("任务已删除");
    } catch {
      toast.error("删除任务失败");
    }
  };

  const handleRunNow = async (id: number) => {
    setRunningId(id);
    try {
      await runScheduledTaskNow(id);
      toast.success("任务已触发执行");
      await refetchTasks();
      // 仅当被触发的任务正处于展开态时刷新可见运行记录；hook 禁用时 refetch 为 no-op。
      if (expandedTaskId === id) {
        await refetchRuns();
      }
    } catch {
      toast.error("触发任务失败");
    } finally {
      setRunningId(null);
    }
  };

  const toggleExpand = (taskId: number) => {
    if (expandedTaskId === taskId) {
      setExpandedTaskId(null);
      return;
    }
    setExpandedTaskId(taskId);
    // runs hook 在 expandedTaskId 变为真值时自动发起请求。
  };

  const formatCron = (cron: string) => {
    const parts = cron.split(" ");
    if (parts.length !== 5) return cron;
    const [minute, hour, , , weekday] = parts;
    const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    const wd = weekday === "*" ? "每天" : weekday.split(",").map((w) => weekdays[parseInt(w)]).join(",");
    const time = hour === "*" ? `${minute}分` : `${hour}:${minute.padStart(2, "0")}`;
    return `${time} ${wd}`;
  };

  const taskList = tasks ?? [];
  const runList = runs ?? [];

  return (
    <div>
      <PageHeader title="定时任务" subtitle="管理每日数据刷新、复盘通知等自动化任务" />

      <div className="mb-4 flex items-center justify-between">
        <div className="text-xs text-muted-foreground">
          共 {taskList.length} 个任务，{taskList.filter((t) => t.enabled).length} 个已启用
        </div>
        <Button onClick={() => setShowForm(!showForm)} className="gap-2">
          <Plus className="h-4 w-4" />
          新建任务
        </Button>
      </div>

      {showForm && (
        <GlassCard className="mb-4">
          <h3 className="text-sm font-semibold mb-3">新建定时任务</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium">任务名称</label>
              <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="例如：每日数据刷新" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium">任务类型</label>
                <select
                  value={formType}
                  onChange={(e) => setFormType(e.target.value)}
                  className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
                >
                  {Object.entries(TASK_TYPE_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </select>
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-medium">Cron 表达式</label>
              <Input value={formCron} onChange={(e) => setFormCron(e.target.value)} placeholder="分 时 日 月 周，例如 0 17 * * *" />
              <p className="mt-1 text-[11px] text-muted-foreground">示例：0 17 * * * = 每天 17:00；0 18 * * 1-5 = 工作日 18:00</p>
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs font-medium">描述（可选）</label>
              <Input value={formDesc} onChange={(e) => setFormDesc(e.target.value)} placeholder="任务用途说明" />
            </div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={formNotifySuccess} onChange={(e) => setFormNotifySuccess(e.target.checked)} />
                成功时通知
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={formNotifyFailure} onChange={(e) => setFormNotifyFailure(e.target.checked)} />
                失败时通知
              </label>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <Button onClick={handleCreate} disabled={saving}>
              {saving ? "创建中..." : "创建任务"}
            </Button>
            <Button variant="ghost" onClick={() => setShowForm(false)}>取消</Button>
          </div>
        </GlassCard>
      )}

      {tasksError && (
        <GlassCard>
          <div className="p-4 text-sm text-rose-600 dark:text-rose-400">
            加载定时任务失败：{tasksError instanceof Error ? tasksError.message : String(tasksError)}
          </div>
        </GlassCard>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中...
        </div>
      ) : taskList.length === 0 ? (
        <GlassCard>
          <div className="py-8 text-center text-sm text-muted-foreground">
            暂无定时任务，点击右上角「新建任务」创建。
          </div>
        </GlassCard>
      ) : (
        <div className="space-y-3">
          {taskList.map((task) => (
            <GlassCard key={task.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold truncate">{task.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${task.enabled ? "bg-success/15 text-success" : "bg-muted/40 text-muted-foreground"}`}>
                      {task.enabled ? "已启用" : "已禁用"}
                    </span>
                    {task.last_run_status && (
                      <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        task.last_run_status === "success" ? "bg-success/15 text-success" :
                        task.last_run_status === "failed" ? "bg-destructive/15 text-destructive" :
                        "bg-muted/40 text-muted-foreground"
                      }`}>
                        {task.last_run_status === "success" ? <CheckCircle className="h-3 w-3" /> :
                         task.last_run_status === "failed" ? <XCircle className="h-3 w-3" /> :
                         <Clock className="h-3 w-3" />}
                        {task.last_run_status === "success" ? "成功" :
                         task.last_run_status === "failed" ? "失败" : "运行中"}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground line-clamp-1">{task.description || TASK_TYPE_LABELS[task.task_type] || task.task_type}</p>
                  <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatCron(task.cron_expr)}
                    </span>
                    {task.last_run_at && (
                      <span>上次运行：{new Date(task.last_run_at).toLocaleString("zh-CN")}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <Button variant="ghost" size="sm" onClick={() => toggleExpand(task.id)} title="查看运行记录">
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleRunNow(task.id)} disabled={runningId === task.id || !task.enabled} title="立即运行">
                    {runningId === task.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleToggle(task)} title={task.enabled ? "禁用" : "启用"}>
                    {task.enabled ? "禁用" : "启用"}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(task.id)} title="删除">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </div>

              {expandedTaskId === task.id && (
                <div className="mt-4 border-t border-border/60 pt-3">
                  <h4 className="text-xs font-medium text-muted-foreground mb-2">最近运行记录</h4>
                  {runList.length > 0 ? (
                    <div className="space-y-2">
                      {runList.map((run) => (
                        <div key={run.id} className="flex items-start justify-between rounded-lg border border-border/40 bg-muted/10 p-2.5 text-xs">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className={`font-medium ${run.status === "success" ? "text-success" : run.status === "failed" ? "text-destructive" : "text-muted-foreground"}`}>
                                {run.status === "success" ? "成功" : run.status === "failed" ? "失败" : "运行中"}
                              </span>
                              <span className="text-muted-foreground">{new Date(run.started_at).toLocaleString("zh-CN")}</span>
                            </div>
                            {run.error && <p className="mt-1 text-destructive">{run.error}</p>}
                            {run.result && Object.keys(run.result).length > 0 && (
                              <pre className="mt-1 overflow-x-auto rounded bg-black/20 p-2 text-[11px] text-muted-foreground">
                                {JSON.stringify(run.result, null, 2)}
                              </pre>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">暂无运行记录</p>
                  )}
                </div>
              )}
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
}
