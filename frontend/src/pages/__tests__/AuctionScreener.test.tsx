// S025-E2 测试：AuctionScreener 页内 TabBar（竞价预案 TOP N / 盘中监控 9:25）。
// mock @/lib/api（auctionTop/auctionMonitor/auctionWatchlist），真实 react-query hooks + QueryClientProvider。
// 验证：默认 tab1 → 候选标的渲染；切 tab2 → Monitor925 渲染（9:25 盘中监控）；切回 tab1 → 候选标的复现。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { AuctionScreenerResult, AuctionSignal, AuctionCandidate } from "@/lib/api";

// vi.hoisted 保证 mock fn 引用在 factory 与测试间一致。
const apiMocks = vi.hoisted(() => ({
  auctionTop: vi.fn<(date?: string, n?: number) => Promise<AuctionScreenerResult>>(),
  auctionMonitor: vi.fn<() => Promise<AuctionSignal[]>>(),
  auctionWatchlist: vi.fn<() => Promise<string[]>>(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

import { AuctionScreener } from "@/pages/limitup/AuctionScreener";

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

const emptyResult: AuctionScreenerResult = {
  date: "2026-08-03",
  candidates: [],
  sti_score: 50,
  sti_phase: "中性",
  total_analyzed: 10,
  updated: "2026-08-03 09:15",
  disclaimer: "",
};

describe("AuctionScreener 页内 TabBar (E2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.auctionTop.mockResolvedValue(emptyResult);
    apiMocks.auctionMonitor.mockResolvedValue([]);
    apiMocks.auctionWatchlist.mockResolvedValue([]);
  });

  it("默认 tab1 → 渲染竞价预案（候选标的），盘中监控不出现", async () => {
    const qc = newClient();
    render(<AuctionScreener />, { wrapper: withClient(qc) });
    await waitFor(() => expect(screen.getByText("候选标的")).toBeInTheDocument());
    expect(screen.queryByText("9:25 盘中监控")).not.toBeInTheDocument();
  });

  it("切 tab2 → 显示盘中监控 9:25，候选标的隐藏", async () => {
    const qc = newClient();
    render(<AuctionScreener />, { wrapper: withClient(qc) });
    await waitFor(() => expect(screen.getByText("候选标的")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "盘中监控 9:25" }));
    await waitFor(() => expect(screen.getByText("9:25 盘中监控")).toBeInTheDocument());
    expect(screen.queryByText("候选标的")).not.toBeInTheDocument();
  });

  it("从盘中监控切回竞价预案 → 候选标的复现", async () => {
    const qc = newClient();
    render(<AuctionScreener />, { wrapper: withClient(qc) });
    await waitFor(() => expect(screen.getByText("候选标的")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "盘中监控 9:25" }));
    await waitFor(() => expect(screen.getByText("9:25 盘中监控")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "竞价预案 TOP N" }));
    await waitFor(() => expect(screen.getByText("候选标的")).toBeInTheDocument());
    expect(screen.queryByText("9:25 盘中监控")).not.toBeInTheDocument();
  });

  // S025 review fix 补测：防假绿——重构后行级 .map（c.code/c.name/c.score）从未验证
  it("tab1 候选非空 → 行级渲染 code/name/score", async () => {
    apiMocks.auctionTop.mockResolvedValue({
      ...emptyResult,
      candidates: [
        { code: "000001", name: "平安银行", score: 80, gene_score: 0.8 } as unknown as AuctionCandidate,
      ],
    });
    const qc = newClient();
    render(<AuctionScreener />, { wrapper: withClient(qc) });
    await waitFor(() => expect(screen.getByText("候选标的")).toBeInTheDocument());
    expect(screen.getByText("000001")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText("80")).toBeInTheDocument();
  });
});
