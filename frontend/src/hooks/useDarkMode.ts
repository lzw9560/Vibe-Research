import { useEffect, useState } from "react";

type Theme = "dark" | "light" | "warm-orange";

const THEME_KEY = "vr-theme";

function loadTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "warm-orange" || saved === "dark") return saved;
  return "dark"; // 默认暗色
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(loadTheme);

  useEffect(() => {
    document.documentElement.classList.remove("light", "dark", "warm-orange");
    document.documentElement.classList.add(theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  return { theme, setTheme };
}

// 兼容旧代码：导出一个 dark 派生值。注意：不要在同一个组件里同时使用 useTheme 和 useDarkMode，
// 否则会有两套状态管理冲突。新代码统一用 useTheme。
export function useDarkMode() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = () => {
    const next: Theme = dark ? "light" : "dark";
    setTheme(next);
  };
  return { dark, toggle };
}

export type { Theme };
