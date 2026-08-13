// S055：炸板预警横幅 + sparkline 测试
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { BombAlertBanner, SealAmountSparkline } from "@/components/risk/BombAlertBanner";

const mockApi = vi.hoisted(() => ({
  bombAlerts: vi.fn(),
  sealSnapshots: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: mockApi }));

describe("BombAlertBanner (S055)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("无预警时不渲染横幅", async () => {
    mockApi.bombAlerts.mockResolvedValue({ alerts: [], count: 0 });
    const { container } = render(<BombAlertBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("红色预警渲染红框 + 规则编号 + 依据", async () => {
    mockApi.bombAlerts.mockResolvedValue({
      alerts: [
        {
          id: 1, rule_id: "C1", alert_level: "red", condition: "封单减 40%",
          code: "000001", name: "平安银行", ts: "2026-08-11T10:30:00", data_status: "ok",
        },
      ],
      count: 1, note: "",
    });
    render(<BombAlertBanner />);
    await waitFor(() => {
      expect(screen.getByText("炸板红色预警")).toBeInTheDocument();
      expect(screen.getByText(/封单减 40%/)).toBeInTheDocument();
    });
  });

  it("黄色预警渲染黄框", async () => {
    mockApi.bombAlerts.mockResolvedValue({
      alerts: [
        {
          id: 1, rule_id: "C6", alert_level: "yellow", condition: "封单/流通市值 0.1%",
          code: "000001", name: "平安银行", ts: "2026-08-11T10:30:00", data_status: "ok",
        },
      ],
      count: 1, note: "",
    });
    render(<BombAlertBanner />);
    await waitFor(() => {
      expect(screen.getByText("炸板黄色预警")).toBeInTheDocument();
    });
  });

  it("点击 X 可关闭横幅", async () => {
    mockApi.bombAlerts.mockResolvedValue({
      alerts: [
        {
          id: 1, rule_id: "C1", alert_level: "red", condition: "test",
          code: "000001", name: "测试", ts: "2026-08-11T10:30:00", data_status: "ok",
        },
      ],
      count: 1, note: "",
    });
    const { container } = render(<BombAlertBanner />);
    await waitFor(() => expect(screen.getByText("炸板红色预警")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button"));
    expect(container.firstChild).toBeNull();
  });
});

describe("SealAmountSparkline (S055)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("快照不足 2 条显示「封单时序不足」", async () => {
    mockApi.sealSnapshots.mockResolvedValue({
      snapshots: [{ seal_amount: 1e8 }], count: 1, data_status: "ok",
    });
    render(<SealAmountSparkline code="000001" />);
    await waitFor(() => {
      expect(screen.getByText("封单时序不足")).toBeInTheDocument();
    });
  });

  it("快照充足渲染 SVG path", async () => {
    mockApi.sealSnapshots.mockResolvedValue({
      snapshots: [
        { seal_amount: 1e8 }, { seal_amount: 0.8e8 }, { seal_amount: 0.6e8 },
      ],
      count: 3, data_status: "ok",
    });
    const { container } = render(<SealAmountSparkline code="000001" />);
    await waitFor(() => {
      const path = container.querySelector("path");
      expect(path).toBeTruthy();
      expect(path?.getAttribute("d")).toContain("M");
    });
  });

  it("加载中显示加载文案", () => {
    mockApi.sealSnapshots.mockReturnValue(new Promise(() => {}));
    render(<SealAmountSparkline code="000001" />);
    expect(screen.getByText("加载封单时序…")).toBeInTheDocument();
  });
});
