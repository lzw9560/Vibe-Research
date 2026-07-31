import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DataTable, type Column } from "./DataTable";

interface Row {
  name: string;
  change: number;
}

const rows: Row[] = [
  { name: "a", change: 1 },
  { name: "b", change: -2 },
];

const columns: Column<Row>[] = [
  { key: "name", header: "名称" },
  { key: "change", header: "涨跌", sortable: true },
];

describe("DataTable", () => {
  it("渲染表头与数据行", () => {
    render(<DataTable data={rows} columns={columns} keyExtractor={(r) => r.name} />);
    expect(screen.getByText("名称")).toBeInTheDocument();
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
  });

  it("空数据显示 emptyState", () => {
    render(
      <DataTable
        data={[]}
        columns={columns}
        keyExtractor={(r) => r.name}
        emptyState={<span>无</span>}
      />,
    );
    expect(screen.getByText("无")).toBeInTheDocument();
  });

  it("loading 显示骨架（不渲染数据行）", () => {
    render(
      <DataTable
        data={[]}
        columns={columns}
        keyExtractor={(r) => r.name}
        loading
        skeletonRows={3}
      />,
    );
    // 数据行不渲染（骨架仅模拟表头形状）
    expect(screen.queryByText("a")).not.toBeInTheDocument();
    expect(screen.queryByText("b")).not.toBeInTheDocument();
  });

  it("点击可排序表头触发 onSort（传出 sortKey）", () => {
    const onSort = vi.fn();
    render(
      <DataTable
        data={rows}
        columns={columns}
        keyExtractor={(r) => r.name}
        onSort={onSort}
        sort={{ key: "change", direction: "asc" }}
      />,
    );
    fireEvent.click(screen.getByText("涨跌").closest("th")!);
    expect(onSort).toHaveBeenCalledWith("change");
  });

  it("active 升序列 aria-sort=ascending 且显示 ▲", () => {
    render(
      <DataTable
        data={rows}
        columns={columns}
        keyExtractor={(r) => r.name}
        onSort={vi.fn()}
        sort={{ key: "change", direction: "asc" }}
      />,
    );
    const th = screen.getByText("涨跌").closest("th")!;
    expect(th).toHaveAttribute("aria-sort", "ascending");
    expect(th.textContent).toContain("▲");
  });

  it("active 降序列 aria-sort=descending 且显示 ▼", () => {
    render(
      <DataTable
        data={rows}
        columns={columns}
        keyExtractor={(r) => r.name}
        onSort={vi.fn()}
        sort={{ key: "change", direction: "desc" }}
      />,
    );
    const th = screen.getByText("涨跌").closest("th")!;
    expect(th).toHaveAttribute("aria-sort", "descending");
    expect(th.textContent).toContain("▼");
  });

  it("不可排序列无指示、aria-sort=none", () => {
    render(<DataTable data={rows} columns={columns} keyExtractor={(r) => r.name} onSort={vi.fn()} />);
    const th = screen.getByText("名称").closest("th")!;
    expect(th).toHaveAttribute("aria-sort", "none");
    expect(th.textContent).not.toContain("↕");
  });

  it("sortable 但无 onSort 时不渲染指示（无交互）", () => {
    render(<DataTable data={rows} columns={columns} keyExtractor={(r) => r.name} />);
    // 有 sortable 标记但未提供 onSort → 不应出现 ↕ 指示
    const th = screen.getByText("涨跌").closest("th")!;
    expect(th.textContent).not.toContain("↕");
  });

  it("onRowClick 行点击派发", () => {
    const onRowClick = vi.fn();
    render(
      <DataTable
        data={rows}
        columns={columns}
        keyExtractor={(r) => r.name}
        onRowClick={onRowClick}
      />,
    );
    fireEvent.click(screen.getByText("a").closest("tr")!);
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });
});
