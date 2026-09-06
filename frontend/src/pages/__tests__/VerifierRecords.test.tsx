// S165 wire: VerifierRecords 页单测——mock fallback + LIVE/MOCK 徽标。
// 仿 limitup.test.tsx 范式：vi.mock("@/lib/api") + QueryClientProvider wrapper。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { RecorderRecord } from "@/lib/verifier-contract";

const apiMocks = vi.hoisted(() => ({
  verifierRecords: vi.fn<() => Promise<RecorderRecord[]>>(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

import { VerifierRecords } from "@/pages/VerifierRecords";
import { recorderRecordMocks } from "@/lib/__fixtures__/dimension-validation.mock";

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

describe("VerifierRecords (S165 wire)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("后端 error → mock fixture fallback + MOCK 徽标", async () => {
    apiMocks.verifierRecords.mockRejectedValue(new Error("backend not ready"));
    const qc = newClient();
    render(<VerifierRecords />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("MOCK")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText(/后端未就绪，显示 mock/)).toBeInTheDocument();
    // mock fixture 第一条 recorder_id 渲染
    expect(screen.getByText(recorderRecordMocks[0].recorder_id)).toBeInTheDocument();
  });

  it("后端返空数组 → mock fixture fallback + MOCK 徽标", async () => {
    apiMocks.verifierRecords.mockResolvedValue([]);
    const qc = newClient();
    render(<VerifierRecords />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("MOCK")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("后端返真实数据 → LIVE 徽标（无 MOCK）", async () => {
    const realRecord: RecorderRecord = {
      ...recorderRecordMocks[0],
      recorder_id: "rec_real_test_001",
    };
    apiMocks.verifierRecords.mockResolvedValue([realRecord]);
    const qc = newClient();
    render(<VerifierRecords />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.queryByText("MOCK")).not.toBeInTheDocument();
    expect(screen.getByText("rec_real_test_001")).toBeInTheDocument();
  });

  it("调 api.verifierRecords() 端点", async () => {
    apiMocks.verifierRecords.mockResolvedValue([...recorderRecordMocks]);
    const qc = newClient();
    render(<VerifierRecords />, { wrapper: withClient(qc) });

    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument(), { timeout: 5000 });
    expect(apiMocks.verifierRecords).toHaveBeenCalledWith();
  });
});
