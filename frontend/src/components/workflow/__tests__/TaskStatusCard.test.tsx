// S092 T8：TaskStatusCard 测试。
// 覆盖：8 项渲染、4 种状态颜色/图标、折叠/展开、载入按钮 invalidate、非交易日。
// mock useScheduledTasksStatus 返回假数据；useQueryClient 真实，需 QueryClientProvider wrapper。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { TaskStatusCard } from "@/components/workflow/TaskStatusCard";
import type { ScheduledTaskStatus } from "@/lib/query/scheduledTasks";

// ---- mock useScheduledTasksStatus：返回假数据，不真正发请求 ----
const mockData = vi.hoisted(() => ({ current: null as ScheduledTaskStatus[] | null }));
vi.mock("@/lib/query/scheduledTasks", () => ({
  useScheduledTasksStatus: () => ({ data: mockData.current }),
}));

// ---- mock api.scheduledTask：详情接口返回假数据 ----
const mockApi = vi.hoisted(() => ({
  scheduledTask: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: mockApi }));

// ---- 8 项任务假数据（对应原型 TASKS：15:30-17:15）----
const EIGHT_TASKS: ScheduledTaskStatus[] = [
  { id: 1, name: "基因得分", cron_expr: "30 15 * * 1-5", last_run_at: "2026-08-21T15:30:12", last_run_status: "success", today_status: "done", task_type: "daily_data_refresh", enabled: true },
  { id: 2, name: "STI 计算", cron_expr: "35 15 * * 1-5", last_run_at: "2026-08-21T15:35:08", last_run_status: "success", today_status: "done", task_type: "sti_post_market", enabled: true },
  { id: 3, name: "前向结算", cron_expr: "45 15 * * 1-5", last_run_at: "2026-08-21T15:45:10", last_run_status: "success", today_status: "done", task_type: "daily_backtest_run", enabled: true },
  { id: 4, name: "R1 溢价评分", cron_expr: "50 15 * * 1-5", last_run_at: "2026-08-21T15:50:09", last_run_status: "success", today_status: "done", task_type: "limitup_precompute", enabled: true },
  { id: 5, name: "首板9维度评分", cron_expr: "15 16 * * 1-5", last_run_at: "2026-08-21T16:15:00", last_run_status: "running", today_status: "running", task_type: "candidate_funnel_precompute", enabled: true },
  { id: 6, name: "kline日更", cron_expr: "30 16 * * 1-5", last_run_at: null, last_run_status: null, today_status: "pending", task_type: "market_data_sync", enabled: true },
  { id: 7, name: "derived预采集", cron_expr: "0 17 * * 1-5", last_run_at: null, last_run_status: null, today_status: "pending", task_type: "cleanup_old_runs", enabled: true },
  { id: 8, name: "漏斗预计算", cron_expr: "15 17 * * 1-5", last_run_at: "2026-08-21T17:15:00", last_run_status: "failed", today_status: "error", task_type: "first_board_filter", enabled: true },
];

function renderWithProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const spyInvalidate = vi.spyOn(qc, "invalidateQueries");
  const result = render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  );
  // rerender 需重新包裹 Provider，否则 useQueryClient 丢 context
  const rerender = (newUi: ReactNode) =>
    result.rerender(
      <QueryClientProvider client={qc}>{newUi}</QueryClientProvider>,
    );
  return { ...result, rerender, qc, spyInvalidate };
}

describe("TaskStatusCard (S092 T8)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockData.current = null;
    mockApi.scheduledTask.mockReset();
  });

  // 1. 8 项任务渲染
  it("过渡窗渲染 8 项任务（按 cron 时间排序）", async () => {
    mockData.current = EIGHT_TASKS;
    renderWithProviders(<TaskStatusCard stage="post_transition" isTradingDay={true} />);
    // 8 个任务项都渲染
    const items = screen.getAllByTestId(/^task-item-/);
    expect(items).toHaveLength(8);
    // 进度徽章 4/8（4 个 done）
    expect(screen.getByTestId("task-progress").textContent).toBe("4/8");
    // 任务名都出现
    expect(screen.getByText("基因得分")).toBeInTheDocument();
    expect(screen.getByText("kline日更")).toBeInTheDocument();
    expect(screen.getByText("漏斗预计算")).toBeInTheDocument();
    // 摘要文字
    expect(screen.getByTestId("task-summary").textContent).toContain("4 项已完成");
    // 时间线区域存在
    expect(screen.getByTestId("task-timeline")).toBeInTheDocument();
  });

  // 2. 状态颜色/图标：4 种 today_status 各自正确
  it("4 种 today_status 各自渲染对应状态徽章", () => {
    mockData.current = EIGHT_TASKS;
    renderWithProviders(<TaskStatusCard stage="post_transition" isTradingDay={true} />);
    // done → 已完成
    const doneItem = screen.getByTestId("task-item-1");
    expect(doneItem.getAttribute("data-today-status")).toBe("done");
    expect(doneItem.textContent).toContain("已完成");
    // running → 运行中
    const runningItem = screen.getByTestId("task-item-5");
    expect(runningItem.getAttribute("data-today-status")).toBe("running");
    expect(runningItem.textContent).toContain("运行中");
    // pending → 待运行
    const pendingItem = screen.getByTestId("task-item-6");
    expect(pendingItem.getAttribute("data-today-status")).toBe("pending");
    expect(pendingItem.textContent).toContain("待运行");
    // error → 错误
    const errorItem = screen.getByTestId("task-item-8");
    expect(errorItem.getAttribute("data-today-status")).toBe("error");
    expect(errorItem.textContent).toContain("错误");
  });

  // 3. 折叠/展开：stage 切换
  it("stage=post_transition 展开时间线，stage=post_market 折叠为摘要条", () => {
    mockData.current = EIGHT_TASKS;
    const { rerender } = renderWithProviders(
      <TaskStatusCard stage="post_transition" isTradingDay={true} />,
    );
    // 过渡窗：时间线可见
    expect(screen.getByTestId("task-timeline")).toBeInTheDocument();
    expect(screen.queryByTestId("task-collapsed-summary")).not.toBeInTheDocument();

    // 切到盘后就绪：折叠
    rerender(
      <TaskStatusCard stage="post_market" isTradingDay={true} /> as any,
    );
    // 折叠摘要条出现，时间线消失
    expect(screen.queryByTestId("task-timeline")).not.toBeInTheDocument();
    expect(screen.getByTestId("task-collapsed-summary")).toBeInTheDocument();
  });

  // 4. 载入按钮：done 项有，点击触发全量 invalidateQueries（P2 修复：原 ['workflow'] 打不中视图数据）
  it("done 项有载入按钮，点击触发 invalidateQueries（全量）", async () => {
    mockData.current = EIGHT_TASKS;
    const { spyInvalidate } = renderWithProviders(
      <TaskStatusCard stage="post_transition" isTradingDay={true} />,
    );
    // id=1 是 done，有载入按钮
    const loadBtn = screen.getByTestId("load-btn-1");
    expect(loadBtn).toBeInTheDocument();
    // pending/running/error 项无载入按钮
    expect(screen.queryByTestId("load-btn-5")).not.toBeInTheDocument();
    expect(screen.queryByTestId("load-btn-6")).not.toBeInTheDocument();
    expect(screen.queryByTestId("load-btn-8")).not.toBeInTheDocument();

    // 点击载入 → 全量 invalidateQueries 被调用
    fireEvent.click(loadBtn);
    await waitFor(() => {
      expect(spyInvalidate).toHaveBeenCalled();
    });
  });

  // 5. 非交易日：保持盘后就绪态（不显示空状态）
  it("非交易日(stage=post_market) 保持折叠摘要条，不显示空状态", () => {
    mockData.current = EIGHT_TASKS;
    renderWithProviders(
      <TaskStatusCard stage="post_market" isTradingDay={false} />,
    );
    // 不显示"非交易日，无采集任务"空状态
    expect(screen.queryByText("非交易日，无采集任务")).not.toBeInTheDocument();
    // 显示折叠摘要条（盘后就绪态）
    expect(screen.getByTestId("task-collapsed-summary")).toBeInTheDocument();
  });

  // 6. cron 解析：30 15 * * 1-5 → "15:30"
  it("cron_expr 解析为 HH:MM 显示（30 15 → 15:30）", () => {
    mockData.current = EIGHT_TASKS;
    renderWithProviders(<TaskStatusCard stage="post_transition" isTradingDay={true} />);
    // 基因得分 cron "30 15 * * 1-5" → "15:30"
    const item1 = screen.getByTestId("task-item-1");
    expect(item1.textContent).toContain("15:30");
    // derived cron "0 17 * * 1-5" → "17:00"
    const item7 = screen.getByTestId("task-item-7");
    expect(item7.textContent).toContain("17:00");
  });

  // 7. 点击任务项展开详情（调 api.scheduledTask）
  it("点击任务项展开详情，调 api.scheduledTask(id)", async () => {
    mockData.current = EIGHT_TASKS;
    mockApi.scheduledTask.mockResolvedValue({
      id: 1,
      name: "基因得分",
      cron_expr: "30 15 * * 1-5",
      last_run_at: "2026-08-21T15:30:12",
      last_run_status: "success",
    });
    renderWithProviders(<TaskStatusCard stage="post_transition" isTradingDay={true} />);
    // 点击任务名区域（item-1）
    fireEvent.click(screen.getByTestId("task-item-1"));
    await waitFor(() => {
      expect(mockApi.scheduledTask).toHaveBeenCalledWith(1);
    });
    // 详情内容出现
    await waitFor(() => {
      expect(screen.getByText(/cron:/)).toBeInTheDocument();
    });
  });
});
