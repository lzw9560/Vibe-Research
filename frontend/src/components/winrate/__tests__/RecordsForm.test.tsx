// S025-C 测试：RecordsForm 录入——受控表单 + useWinRateRecords。
// C1：空提交 → 必填校验拦截（stock_code/entry_date/exit_date）。
// C2：成功 → 清空 + invalidate + toast.success；失败(reject) → 保留输入 + toast.error；
//     部分失败(error_count>0) → 保留输入 + toast.error 展示 added_count/errors。
// 策略：mock @/lib/api.winRateRecords + real useWinRateRecords（onSuccess invalidate 真跑），
//       spy queryClient.invalidateQueries；mock sonner 的 toast。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { WinRateRecordInput, WinRateRecordsResponse } from "@/lib/api";

// vi.hoisted 保证 mock fn 引用在 vi.mock 工厂与测试间一致（vi.mock 提升不捕获顶层变量）。
const apiMocks = vi.hoisted(() => ({
  winRateRecords: vi.fn<(r: WinRateRecordInput[]) => Promise<WinRateRecordsResponse>>(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));

const toasts = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: toasts.success, error: toasts.error } }));

import { RecordsForm } from "../RecordsForm";

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

const okRes: WinRateRecordsResponse = {
  added: ["000001"],
  added_count: 1,
  errors: [],
  error_count: 0,
};

function fillRequired() {
  fireEvent.change(screen.getByLabelText("股票代码"), { target: { value: "000001" } });
  fireEvent.change(screen.getByLabelText("买入日期"), { target: { value: "2026-08-01" } });
  fireEvent.change(screen.getByLabelText("卖出日期"), { target: { value: "2026-08-02" } });
}

describe("RecordsForm (C1/C2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("C1 空提交 → 必填校验拦截，不调 winRateRecords", () => {
    const qc = newClient();
    render(<RecordsForm />, { wrapper: withClient(qc) });

    fireEvent.click(screen.getByRole("button", { name: /提交/ }));

    expect(screen.getByText("股票代码必填")).toBeInTheDocument();
    expect(screen.getByText("买入日期必填")).toBeInTheDocument();
    expect(screen.getByText("卖出日期必填")).toBeInTheDocument();
    expect(apiMocks.winRateRecords).not.toHaveBeenCalled();
  });

  it("C2 成功 → 清空表单 + invalidate winrate 前缀 + toast.success", async () => {
    apiMocks.winRateRecords.mockResolvedValue(okRes);
    const qc = newClient();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    render(<RecordsForm />, { wrapper: withClient(qc) });

    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: /提交/ }));

    await waitFor(() =>
      expect(apiMocks.winRateRecords).toHaveBeenCalledWith([
        expect.objectContaining({
          stock_code: "000001",
          entry_date: "2026-08-01",
          exit_date: "2026-08-02",
        }),
      ]),
    );
    await waitFor(() => expect(toasts.success).toHaveBeenCalled());
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["limitup", "winrate"] }),
    );
    // 表单清空
    await waitFor(() => expect(screen.getByLabelText("股票代码")).toHaveValue(""));
  });

  it("C2 失败(reject) → 保留输入 + toast.error 展示错误信息", async () => {
    apiMocks.winRateRecords.mockRejectedValue(new Error("网络错误"));
    const qc = newClient();
    render(<RecordsForm />, { wrapper: withClient(qc) });

    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: /提交/ }));

    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("网络错误"));
    expect(screen.getByLabelText("股票代码")).toHaveValue("000001");
    expect(screen.getByLabelText("买入日期")).toHaveValue("2026-08-01");
    expect(screen.getByLabelText("卖出日期")).toHaveValue("2026-08-02");
  });

  it("C2 部分失败(error_count>0) → 保留输入 + toast.error 展示 added_count/errors", async () => {
    const partial: WinRateRecordsResponse = {
      added: [],
      added_count: 0,
      errors: [{ index: 0, error: "exit_date 早于 entry_date" }],
      error_count: 1,
    };
    apiMocks.winRateRecords.mockResolvedValue(partial);
    const qc = newClient();
    render(<RecordsForm />, { wrapper: withClient(qc) });

    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: /提交/ }));

    await waitFor(() => expect(toasts.error).toHaveBeenCalled());
    expect(toasts.error).toHaveBeenCalledWith(
      expect.stringContaining("1 条失败"),
      expect.objectContaining({
        description: expect.stringContaining("exit_date"),
      }),
    );
    // 保留输入不滚
    expect(screen.getByLabelText("股票代码")).toHaveValue("000001");
  });
});
