// S165 wire: DimensionValidationGrid 单测——mock fallback + LIVE/MOCK 徽标。
// 仿 limitup.test.tsx 范式：vi.mock("@/lib/api") + QueryClientProvider wrapper。
// DimensionValidationCard mock 为轻量 stub（12 张复杂卡在 jsdom 渲染慢，mock 后 DOM 小、waitFor 快）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { DimensionValidationRecord } from "@/lib/verifier-contract";

const apiMocks = vi.hoisted(() => ({
  evaluationDims: vi.fn<() => Promise<DimensionValidationRecord[]>>(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

// 轻量 stub：Grid 只测 fallback/badge 逻辑，卡内渲染由 DimensionValidationCard.test.tsx 覆盖。
vi.mock("@/components/DimensionValidationCard", () => ({
  DimensionValidationCard: ({ record }: { record: DimensionValidationRecord }) => (
    <div data-testid="dim-card">{record.dimension_id}</div>
  ),
}));

import { DimensionValidationGrid } from "@/components/DimensionValidationGrid";
import { dimensionValidationMocks } from "@/lib/__fixtures__/dimension-validation.mock";

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

describe("DimensionValidationGrid (S165 wire)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("后端 error → mock fixture fallback + MOCK 徽标", async () => {
    apiMocks.evaluationDims.mockRejectedValue(new Error("backend not ready"));
    const qc = newClient();
    render(<DimensionValidationGrid />, { wrapper: withClient(qc) });

    // 等待 query settle（error → fallback）
    await waitFor(() => expect(screen.getByText("MOCK")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText(/后端未就绪，显示 mock/)).toBeInTheDocument();
    // mock fixture 12 张卡渲染（stub）
    expect(screen.getAllByTestId("dim-card")).toHaveLength(12);
  });

  it("后端返空数组 → mock fixture fallback + MOCK 徽标", async () => {
    apiMocks.evaluationDims.mockResolvedValue([]);
    const qc = newClient();
    render(<DimensionValidationGrid />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("MOCK")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("后端返真实数据 → LIVE 徽标（无 MOCK）", async () => {
    // 单条真实 dim（与 mock 不同 dim_id 避免撞 key）
    const realDim: DimensionValidationRecord = {
      ...dimensionValidationMocks[0],
      dimension_id: "real_test_dim",
      label: "真实测试维度",
    };
    apiMocks.evaluationDims.mockResolvedValue([realDim]);
    const qc = newClient();
    render(<DimensionValidationGrid />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.queryByText("MOCK")).not.toBeInTheDocument();
    expect(screen.getByText("real_test_dim")).toBeInTheDocument();
  });

  it("调 api.evaluationDims() 端点", async () => {
    apiMocks.evaluationDims.mockResolvedValue([...dimensionValidationMocks]);
    const qc = newClient();
    render(<DimensionValidationGrid />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument(), { timeout: 5000 });
    expect(apiMocks.evaluationDims).toHaveBeenCalledWith();
  });
});
