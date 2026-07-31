import { describe, it, expect } from "vitest";

// 烟雾测试：确保 vitest + jsdom + globals 配置正确可用。
describe("smoke", () => {
  it("basic arithmetic works", () => {
    expect(1 + 1).toBe(2);
  });
});
