// S025-A 测试：api.winRateRecords POST 封装。
// 验证 wrapper 正确接线 path/method/body（request 低层 mock）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { WinRateRecordInput, WinRateRecordsResponse } from "./api/types";

// Mock 低层 client，断言 wrapper 以 (path, "POST", body) 调 request。
// 补全 loadAccessKey/saveAccessKey，避免 api.ts 的 re-export 取到 undefined。
vi.mock("./api/client", () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
  authHeaders: () => ({}),
  loadAccessKey: () => "",
  saveAccessKey: () => {
    /* noop */
  },
  request: vi.fn(),
  get: vi.fn(),
}));

import { api } from "./api";
import { request } from "./api/client";

const mockRequest = vi.mocked(request);

const fullRecord: WinRateRecordInput = {
  stock_code: "000001",
  stock_name: "平安银行",
  strategy_used: "打板",
  entry_date: "2026-08-01",
  entry_price: 10.5,
  exit_date: "2026-08-02",
  exit_price: 11.0,
  return_pct: 4.76,
  is_win: true,
  gene_score: 80,
  sti_label: "高潮",
  sector: "银行",
};

const okResponse: WinRateRecordsResponse = {
  added: ["000001"],
  added_count: 1,
  errors: [],
  error_count: 0,
};

describe("api.winRateRecords (S025-A2)", () => {
  beforeEach(() => mockRequest.mockReset());

  it("以 records 数组为 body POST /winrate/records", async () => {
    mockRequest.mockResolvedValue(okResponse);

    const res = await api.winRateRecords([fullRecord]);

    expect(mockRequest).toHaveBeenCalledTimes(1);
    expect(mockRequest).toHaveBeenCalledWith("/winrate/records", "POST", [fullRecord]);
    expect(res).toEqual(okResponse);
  });

  it("多元素数组原样透传 body", async () => {
    mockRequest.mockResolvedValue({ added: [], added_count: 0, errors: [], error_count: 0 });
    const records: WinRateRecordInput[] = [
      { stock_code: "000001", entry_date: "2026-08-01", exit_date: "2026-08-02" },
      { stock_code: "600000", entry_date: "2026-08-01", exit_date: "2026-08-02" },
    ];
    await api.winRateRecords(records);
    expect(mockRequest).toHaveBeenCalledWith("/winrate/records", "POST", records);
  });

  it("仅必填字段的 record 透传", async () => {
    mockRequest.mockResolvedValue(okResponse);
    const minimal: WinRateRecordInput = {
      stock_code: "000001",
      entry_date: "2026-08-01",
      exit_date: "2026-08-02",
    };
    await api.winRateRecords([minimal]);
    expect(mockRequest).toHaveBeenCalledWith("/winrate/records", "POST", [minimal]);
  });
});
