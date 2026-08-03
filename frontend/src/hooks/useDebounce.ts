// 标准 debounce hook：延迟 delay ms 后同步 value；期间 value 再变则重置计时器，
// 仅末次变更在延迟后生效。用于搜索框等高频输入——输入框用原 value 保响应，
// 请求/查询用 debounced 值控频，避免每键改 queryKey 触发请求 + 闪 Skeleton。
//
// 空值（""）语义：搜索框清空时即时断查（不延迟），且切维度清空后重输不以旧
// debounced 起跳——渲染期直返空（防清空首帧 stale），effect 期立即同步 debounced
// 为空（防后续非空帧从旧值串味到新维度）。
import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    if (value === "") {
      setDebouncedValue(value);
      return;
    }
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);

  return value === "" ? value : debouncedValue;
}
