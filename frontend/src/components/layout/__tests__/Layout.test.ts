// Nav IA Phase 2 isPathActive 防回归测试（第二轮验证 agent 维度 7 建议）
// 防 /stock/ 带尾/ 致详情页匹配失效回归（9ba750e 曾引入此 CRITICAL）
import { describe, it, expect } from "vitest";
import { isPathActive } from "../Layout";

describe("isPathActive", () => {
  // 盘面线 matchPrefix（navigation.ts 实际值，/stock /sectors 不带尾/）
  const panMian = [
    "/workspace", "/market", "/intraday", "/screener", "/candidates",
    "/value-funnel", "/watchlist", "/bidding", "/limitup", "/recommendation",
    "/intel", "/stock-data", "/stock", "/sectors",
  ];

  it("matches detail page /stock/:code via startsWith(p+'/')", () => {
    expect(isPathActive("/stock/600519", panMian)).toBe(true);
  });

  it("matches detail page /sectors/:key via startsWith(p+'/')", () => {
    expect(isPathActive("/sectors/banking", panMian)).toBe(true);
  });

  it("precise match /stock-data (not false-matched by /stock prefix)", () => {
    expect(isPathActive("/stock-data", panMian)).toBe(true);
  });

  it("does not false-match /database for /data prefix (original M-A fix)", () => {
    expect(isPathActive("/database", ["/data"])).toBe(false);
  });

  it("does not false-match /stockabc for /stock prefix", () => {
    expect(isPathActive("/stockabc", ["/stock"])).toBe(false);
  });

  it("precise match hub route", () => {
    expect(isPathActive("/workspace", panMian)).toBe(true);
  });

  it("matches query param variant p+'?'", () => {
    expect(isPathActive("/workspace?phase=intraday", panMian)).toBe(true);
  });

  it("does not match unrelated path", () => {
    expect(isPathActive("/settings", panMian)).toBe(false);
  });
});
