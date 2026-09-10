// S179 P0.2: 命令面板 toggle hook——管理 open/close state + Cmd+K 全局监听。
// macOS Cmd+K（避浏览器 Ctrl+K 冲突，用户已定）。非 macOS 平台需另定快捷键（TODO）。
import { useCallback, useEffect, useState } from "react";

export interface CommandPaletteState {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

export function useCommandPalette(): CommandPaletteState {
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => setIsOpen((p) => !p), []);

  // Cmd+K 全局 toggle（仅 metaKey，避 Ctrl+K 浏览器冲突）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey && e.key === "k") {
        e.preventDefault();
        setIsOpen((p) => !p);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return { isOpen, open, close, toggle };
}
