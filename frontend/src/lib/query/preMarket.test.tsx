// S048 R8 测试：usePreMarketBriefing(date) queryKey/staleTime 语义 + usePreMarketDates 接线。
// staleTime 逻辑抽纯函数 preMarketBriefingStaleTime 直测（避开 fake timers + react-query 的脆弱组合）。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiMocks = vi.hoisted(() => ({
  getPreMarketBriefing: vi.fn(),
  getPreMarketDates: vi.fn(),
}));

// limitup.ts 还从 @/lib/api 拉一堆别的名字；此 mock 只提供本文件用到的，其余 queryFn 不触发即无碍
vi.mock("@/lib/api", () => ({
  getPreMarketBriefing: apiMocks.getPreMarketBriefing,
  getPreMarketDates: apiMocks.getPreMarketDates,
}));

import {
  usePreMarketBriefing,
  usePreMarketDates,
  preMarketBriefingStaleTime,
} from "@/lib/query/limitup";

function newClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false, staleTime: 0 } },
  });
}
function withClient(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("preMarketBriefingStaleTime (S048 R8)", () => {
  it("status done → Infinity（今日 done 也幂等不重拉）", () => {
    expect(preMarketBriefingStaleTime(undefined, "done", "2026-08-10")).toBe(Infinity);
    expect(preMarketBriefingStaleTime("2026-08-10", "done", "2026-08-10")).toBe(Infinity);
  });

  it("历史日期（date < today）→ Infinity（含 no_snapshot，重采只能走显式 invalidate）", () => {
    expect(preMarketBriefingStaleTime("2026-07-01", "no_snapshot", "2026-08-10")).toBe(Infinity);
    expect(preMarketBriefingStaleTime("2026-07-01", "done", "2026-08-10")).toBe(Infinity);
  });

  it("今日视角非 done（running/idle/error/no date）→ 30s", () => {
    expect(preMarketBriefingStaleTime(undefined, "running", "2026-08-10")).toBe(30_000);
    expect(preMarketBriefingStaleTime(undefined, "idle", "2026-08-10")).toBe(30_000);
    expect(preMarketBriefingStaleTime(undefined, undefined, "2026-08-10")).toBe(30_000);
  });
});

describe("usePreMarketBriefing(date) (S048 R8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("queryKey 含 date，queryFn 透传 date", async () => {
    apiMocks.getPreMarketBriefing.mockResolvedValue({ status: "done", factors: [] });
    const qc = newClient();
    const { result } = renderHook(() => usePreMarketBriefing("2026-07-01"), { wrapper: withClient(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.getPreMarketBriefing).toHaveBeenCalledWith("2026-07-01");
    expect(qc.getQueryData(["limitup", "preMarketBriefing", "2026-07-01"])).toMatchObject({ status: "done" });
  });

  it("不传 date → queryFn 收 undefined（今日实时，现状路径）", async () => {
    apiMocks.getPreMarketBriefing.mockResolvedValue({ status: "idle" });
    const qc = newClient();
    const { result } = renderHook(() => usePreMarketBriefing(), { wrapper: withClient(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMocks.getPreMarketBriefing).toHaveBeenCalledWith(undefined);
  });
});

describe("usePreMarketDates (S048 R6)", () => {
  it("queryFn 接 getPreMarketDates，数据透传", async () => {
    apiMocks.getPreMarketDates.mockResolvedValue({ dates: ["2026-08-03"] });
    const qc = newClient();
    const { result } = renderHook(() => usePreMarketDates(), { wrapper: withClient(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.dates).toEqual(["2026-08-03"]);
  });
});
