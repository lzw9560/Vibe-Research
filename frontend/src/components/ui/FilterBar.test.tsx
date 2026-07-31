import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FilterBar } from "./FilterBar";

describe("FilterBar", () => {
  it("search onChange 派发", () => {
    const onChange = vi.fn();
    render(<FilterBar search={{ value: "", onChange, placeholder: "搜" }} />);
    fireEvent.change(screen.getByPlaceholderText("搜"), { target: { value: "foo" } });
    expect(onChange).toHaveBeenCalledWith("foo");
  });

  it("pill 点击触发 onClick 且 aria-pressed 反映 active", () => {
    const onClick = vi.fn();
    render(
      <FilterBar
        pills={[
          { key: "all", label: "全部", active: true, onClick },
          { key: "up", label: "仅涨", active: false, onClick },
        ]}
      />,
    );
    const all = screen.getByText("全部");
    fireEvent.click(all);
    expect(onClick).toHaveBeenCalled();
    expect(all).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("仅涨")).toHaveAttribute("aria-pressed", "false");
  });

  it("sort select 派发 onChange", () => {
    const onChange = vi.fn();
    render(
      <FilterBar
        sort={{
          value: "a",
          onChange,
          options: [
            { value: "a", label: "A" },
            { value: "b", label: "B" },
          ],
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText("排序"), { target: { value: "b" } });
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("right 槽渲染", () => {
    render(<FilterBar right={<button>刷新</button>} />);
    expect(screen.getByText("刷新")).toBeInTheDocument();
  });

  it("无配置时渲染空容器（不报错）", () => {
    const { container } = render(<FilterBar />);
    expect(container.firstChild).not.toBeNull();
  });
});
