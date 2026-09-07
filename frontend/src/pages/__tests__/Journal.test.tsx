// S166: Journal 页 smoke 单测——渲染 + tab 切换 + 后端未就绪诚实横幅。
// 仿 VerifierRecords.test.tsx 范式：vi.mock("@/lib/api") + QueryClientProvider wrapper。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// 全空 / available:False mock——sections 应诚实呈现"暂无/未就绪"不崩。
const apiMocks = vi.hoisted(() => ({
  journalList: vi.fn(async () => ({ trades: [], total: 0 })),
  journalStats: vi.fn(async () => ({ available: false, reason: "还没有交易记录" })),
  journalFees: vi.fn(async () => ({
    commission_rate: 0.00025, commission_min: 5, stamp_tax_rate: 0.0005,
    transfer_fee_rate: 0.00001, is_default: true,
  })),
  journalAdd: vi.fn(async () => ({ ok: true })),
  journalUpdate: vi.fn(async () => ({ ok: true })),
  journalDelete: vi.fn(async () => ({ ok: true })),
  journalSaveFees: vi.fn(async () => ({ ok: true })),
  riskReport: vi.fn(async () => ({ available: false, reason: "加载" })),
  riskAtRisk: vi.fn(async () => ({ available: false, reason: "没有持仓" })),
  riskExcursion: vi.fn(async () => ({ available: false, reason: "没有交易" })),
  riskAttribution: vi.fn(async () => ({ available: false, reason: "无命中数据" })),
  riskInbox: vi.fn(async () => ({ available: false, reason: "没有记录" })),
  riskRules: vi.fn(async () => ({
    max_loss_per_trade_pct: 5, max_loss_per_day_pct: 8, max_positions: 3,
    max_trades_per_day: 5, pause_after_losses: 3, max_unplanned_ratio: 0.2, is_default: true,
  })),
  riskSaveRules: vi.fn(async () => ({ ok: true })),
  riskEquityBase: vi.fn(async () => ({ equity_base: null })),
  riskSaveEquityBase: vi.fn(async () => ({ ok: true })),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks, ApiError: class extends Error { constructor(m: string, readonly s: number) { super(m); } } }));

import { Journal } from "@/pages/Journal";

function newClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}
function wrap(ui: ReactNode) {
  return <QueryClientProvider client={newClient()}>{ui}</QueryClientProvider>;
}

describe("Journal page (S166)", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((m) => (m as ReturnType<typeof vi.fn>).mockClear());
  });

  it("renders title + 4 tabs, default 交易日志", () => {
    render(wrap(<Journal />));
    expect(screen.getByText("交易日志 + 风险账本")).toBeInTheDocument();
    expect(screen.getByText("交易日志")).toBeInTheDocument();
    expect(screen.getByText("风险账本")).toBeInTheDocument();
    expect(screen.getByText("诊断")).toBeInTheDocument();
    expect(screen.getByText("设置")).toBeInTheDocument();
    expect(screen.getByText("记一笔交易")).toBeInTheDocument(); // 默认 tab 的录入表单
  });

  it("switches to 风险账本 tab showing honest R3 label", async () => {
    render(wrap(<Journal />));
    fireEvent.click(screen.getByText("风险账本"));
    await waitFor(() => {
      // R3 诚实标签 centerpiece：stop 对隔夜 gap-down 是仪式非保护
      expect(screen.getByText(/stop 对隔夜 gap-down 是仪式非保护/)).toBeInTheDocument();
    });
  });

  it("switches to 诊断 tab showing attribution honest unavailable", async () => {
    render(wrap(<Journal />));
    fireEvent.click(screen.getByText("诊断"));
    await waitFor(() => {
      expect(screen.getByText(/判断\/执行归因/)).toBeInTheDocument();
    });
  });

  it("设置 tab renders rules/fees/equity editors", async () => {
    render(wrap(<Journal />));
    fireEvent.click(screen.getByText("设置"));
    await waitFor(() => {
      expect(screen.getByText("风险宪法")).toBeInTheDocument();
      expect(screen.getByText("交易费率")).toBeInTheDocument();
      expect(screen.getByText("账户规模")).toBeInTheDocument();
    });
  });
});
