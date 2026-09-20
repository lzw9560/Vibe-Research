// S221 gap1: DeliveryStatusCard 测试——推送状态灯渲染。
// today_status + notify_on_success 映射 ✓/✗/⚠。不臆造"已送达"（无 webhook receipt）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const hooks = vi.hoisted(() => ({
  useDeliveryFireStatus: vi.fn(),
}));

vi.mock("@/lib/query/signals", () => ({
  useDeliveryFireStatus: hooks.useDeliveryFireStatus,
}));

import { DeliveryStatusCard } from "../DeliveryStatusCard";
import type { ScheduledTaskStatus } from "@/lib/query/scheduledTasks";

function mockTask(over: Partial<ScheduledTaskStatus> = {}): ScheduledTaskStatus {
  return {
    id: 1,
    name: "daily_report",
    cron_expr: "50 14 * * 0-4",
    last_run_at: "2026-09-20T14:50:00",
    last_run_status: "success",
    today_status: "done",
    task_type: "daily_report",
    enabled: true,
    notify_on_success: true,
    ...over,
  };
}

function setupDailyReport(task: ScheduledTaskStatus | null) {
  hooks.useDeliveryFireStatus.mockReturnValue({
    data: task ? [task] : [],
    dailyReport: task,
    weeklyReview: null,
    isLoading: false,
    isError: false,
    error: null,
  });
}

function setupLoading() {
  hooks.useDeliveryFireStatus.mockReturnValue({
    data: undefined,
    dailyReport: null,
    weeklyReview: null,
    isLoading: true,
    isError: false,
    error: null,
  });
}

describe("DeliveryStatusCard (S221 gap1)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("done + notify_on_success=true → ✓ 今天已 fire + 飞书已配置", () => {
    setupDailyReport(mockTask({ today_status: "done", notify_on_success: true }));
    render(<DeliveryStatusCard />);
    expect(screen.getByText(/今天已 fire/)).toBeInTheDocument();
    expect(screen.getByText(/飞书已配置/)).toBeInTheDocument();
  });

  it("done + notify_on_success=false → ⚠ 今天 fire 但飞书未配置", () => {
    setupDailyReport(mockTask({ today_status: "done", notify_on_success: false }));
    render(<DeliveryStatusCard />);
    expect(screen.getByText(/今天已 fire/)).toBeInTheDocument();
    expect(screen.getByText(/飞书未配置/)).toBeInTheDocument();
  });

  it("pending → ✗ 今日未 fire", () => {
    setupDailyReport(mockTask({ today_status: "pending", last_run_at: null }));
    render(<DeliveryStatusCard />);
    expect(screen.getByText(/今日未 fire/)).toBeInTheDocument();
  });

  it("degraded → ⚠ fire 但降级", () => {
    setupDailyReport(mockTask({ today_status: "degraded", last_run_status: "degraded" }));
    render(<DeliveryStatusCard />);
    expect(screen.getByText(/降级/)).toBeInTheDocument();
  });

  it("error → ✗ fire 失败", () => {
    setupDailyReport(mockTask({ today_status: "error", last_run_status: "failed" }));
    render(<DeliveryStatusCard />);
    expect(screen.getByText(/fire 失败/)).toBeInTheDocument();
  });

  it("loading → skeleton（不假装有数据）", () => {
    setupLoading();
    const { container } = render(<DeliveryStatusCard />);
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("dailyReport=null → pending 态（无 daily_report task 注册）", () => {
    setupDailyReport(null);
    render(<DeliveryStatusCard />);
    expect(screen.getByText(/今日未 fire/)).toBeInTheDocument();
  });
});
