import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { BombAlertsResult } from "@/lib/api";
import { WorkflowStage } from "../components/WorkflowStage";
import BombAlertPanel from "../BombAlertPanel";

// S036 工作流标灰——WorkflowStage notImplemented prop + BombAlertPanel 已实现态。
// IntradayMonitor 已由 S063 去桩重写（真实四层布局），不再属 S036 未实现态，
// 其测试在 IntradayMonitor.test.tsx；PostMarketReview 已由 S054 去桩重写，
// 其测试在 PostMarketReview.test.tsx。BombAlertPanel 已由 S216 P0 去桩重写
// （/risk/bomb-alerts 返真实信号），旧"未实现"标灰已废弃。

// BombAlertPanel 用 useQuery 调 api.bombAlerts，需 mock + QueryClientProvider。
const apiMocks = vi.hoisted(() => ({
  bombAlerts: vi.fn<() => Promise<BombAlertsResult>>(),
}));
vi.mock("@/lib/api", () => ({ api: apiMocks }));

function newClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false, staleTime: 0 },
    },
  });
}

function withClient(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("S036 工作流标灰", () => {
  it("WorkflowStage notImplemented=true 渲染未实现横幅，不渲染 children", () => {
    render(
      <WorkflowStage
        title="t"
        subtitle="s"
        notImplemented
        notImplementedMessage="未实现说明"
      >
        <div data-testid="child">不应出现</div>
      </WorkflowStage>,
    );
    expect(screen.getByText("未实现")).toBeInTheDocument();
    expect(screen.getByText("未实现说明")).toBeInTheDocument();
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });

  it("WorkflowStage 未传 notImplemented 时正常渲染 children（回归 PreMarketBriefing 用法）", () => {
    render(
      <WorkflowStage title="t" subtitle="s">
        <div data-testid="child">内容</div>
      </WorkflowStage>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.queryByText("未实现")).not.toBeInTheDocument();
  });

  it("BombAlertPanel 渲染已实现态（S216 P0 接线，空数据显示空状态而非旧标灰）", async () => {
    apiMocks.bombAlerts.mockResolvedValue({
      date: "2026-09-20",
      alerts: [],
      count: 0,
      note: "",
    });
    const qc = newClient();
    render(<BombAlertPanel />, { wrapper: withClient(qc) });
    // 查询完成后显示空状态（非旧"未实现"标灰）
    expect(await screen.findByText("当日无炸板预警信号")).toBeInTheDocument();
    expect(screen.getByText("炸板预警")).toBeInTheDocument();
    expect(screen.queryByText("未实现")).not.toBeInTheDocument();
  });
});
