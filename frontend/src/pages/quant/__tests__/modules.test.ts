// Track D M3 test: 量化模块定义——诚实标注 live/planning（守工程底线：不臆造）。
import { describe, it, expect } from "vitest";
import { QUANT_MODULES } from "../modules";

describe("QuantModules data (M3)", () => {
  it("共 7 个模块（M1-M7）", () => {
    expect(QUANT_MODULES).toHaveLength(7);
    expect(QUANT_MODULES.map((m) => m.key)).toEqual([
      "M1", "M2", "M3", "M4", "M5", "M6", "M7",
    ]);
  });

  it("恰好 3 live（M1 OFI / M2 预期差 / M4 em_get防封）+ 4 planning", () => {
    const live = QUANT_MODULES.filter((m) => m.status === "live");
    const planning = QUANT_MODULES.filter((m) => m.status === "planning");
    expect(live).toHaveLength(3);
    expect(planning).toHaveLength(4);
    expect(live.map((m) => m.key).sort()).toEqual(["M1", "M2", "M4"]);
    expect(planning.map((m) => m.key).sort()).toEqual(["M3", "M5", "M6", "M7"]);
  });

  it("planning 模块不含 live 数据源（不臆造 live 数据入口；null/undefined 均可）", () => {
    for (const m of QUANT_MODULES.filter((x) => x.status === "planning")) {
      expect(m.liveSource).toBeFalsy(); // null 或 undefined 均表示无 live 数据源
      expect(m.note).toBeTruthy(); // 必须有诚实说明
    }
  });

  it("M1 OFI 有 liveSource + link（已实现 endpoint）", () => {
    const m1 = QUANT_MODULES.find((m) => m.key === "M1");
    expect(m1?.status).toBe("live");
    expect(m1?.liveSource).toBe("ofi");
    expect(m1?.link).toBe("/workflow/intraday/ofi");
  });

  it("M2/M4 live 且有 liveSource（S216 P2 接线 endpoint：预期差 / emHealth）", () => {
    const m2 = QUANT_MODULES.find((m) => m.key === "M2");
    const m4 = QUANT_MODULES.find((m) => m.key === "M4");
    expect(m2?.status).toBe("live");
    expect(m2?.liveSource).toBe("expectationGap");
    expect(m4?.status).toBe("live");
    expect(m4?.liveSource).toBe("emHealth");
  });
});
