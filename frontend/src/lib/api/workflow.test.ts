// S048 测试：workflow api 封装——getPreMarketBriefing(date?) 路径拼接 + getPreMarketDates。
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("./client", () => ({
  get: vi.fn(),
  request: vi.fn(),
}));

import { getPreMarketBriefing, getPreMarketDates } from "./workflow";
import { get } from "./client";

const mockGet = vi.mocked(get);

describe("getPreMarketBriefing (S048)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("不带 date → GET /workflow/pre-market（现状路径不变）", async () => {
    mockGet.mockResolvedValue({ status: "idle" });
    await getPreMarketBriefing();
    expect(mockGet).toHaveBeenCalledWith("/workflow/pre-market");
  });

  it("带 date → 路径拼 ?date=YYYY-MM-DD", async () => {
    mockGet.mockResolvedValue({ status: "no_snapshot", data_date: "2026-07-01" });
    const r = await getPreMarketBriefing("2026-07-01");
    expect(mockGet).toHaveBeenCalledWith("/workflow/pre-market?date=2026-07-01");
    expect(r?.status).toBe("no_snapshot");
  });

  it("请求失败 → 返 null 不抛（本文件既有约定）", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    expect(await getPreMarketBriefing("2026-07-01")).toBeNull();
  });
});

describe("getPreMarketDates (S048 R6)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("GET /workflow/pre-market/dates → {dates} 原样返", async () => {
    mockGet.mockResolvedValue({ dates: ["2026-08-03", "2026-07-01"] });
    const r = await getPreMarketDates();
    expect(mockGet).toHaveBeenCalledWith("/workflow/pre-market/dates");
    expect(r?.dates).toEqual(["2026-08-03", "2026-07-01"]);
  });

  it("请求失败 → 返 null", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    expect(await getPreMarketDates()).toBeNull();
  });
});
