// 关注股票（自选股）—— 后端 API 持久化，localStorage 仅作 fallback。
// S013 T5：内联 fetch 改走 lib/api/client 的 request<T>（鉴权/JSON/解包统一）。
// safe() fallback 层保留：request 抛 ApiError → safe 捕获 → localStorage fallback。

import { request } from "@/lib/api/client";

const KEY = "vr-watchlist";

// ---------------------------------------------------------------------------
// Deprecated: 仅作为 API 失败时的 fallback 保留。
// ---------------------------------------------------------------------------

/** @deprecated 改用 `apiWatchlist.fetch()` */
export function loadWatch(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((c) => /^\d{6}$/.test(c)) : [];
  } catch {
    return [];
  }
}

/** @deprecated 改用 `apiWatchlist.add()` / `apiWatchlist.remove()` */
export function saveWatch(codes: string[]) {
  // localStorage 在隐私模式 / 嵌入式浏览器 / 配额写满时会抛异常。
  // 存不下就算了——自选丢失总好过整页崩掉（读取侧同样是 try/catch 兜底）。
  try {
    localStorage.setItem(KEY, JSON.stringify(codes));
  } catch {
    /* 存储不可用：本次会话内仍可正常使用，只是关掉页面后不保留 */
  }
}

// ---------------------------------------------------------------------------
// 解析工具（不变）
// ---------------------------------------------------------------------------

/** 从任意文本里抽取 6 位 A 股代码 */
export function parseCodes(raw: string): string[] {
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return Array.from(new Set(tokens.filter((t) => /^\d{6}$/.test(t))));
}

/** 把用户输入的一串代码并入已有自选，返回去重后的新列表 + 实际新增数量。 */
export function addCodes(existing: string[], raw: string): { next: string[]; added: number } {
  const incoming = parseCodes(raw).filter((c) => !existing.includes(c));
  return { next: [...existing, ...incoming], added: incoming.length };
}

// ---------------------------------------------------------------------------
// API 层：后端持久化 + localStorage fallback
// ---------------------------------------------------------------------------

export interface ApiWatchlistResponse {
  added?: number;
  total: number;
}

async function safe<T>(fn: () => Promise<T>, fallback: () => T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback();
  }
}

export const apiWatchlist = {
  /**
   * GET /api/watchlist → code[]
   * 失败时 fallback 到 localStorage。
   */
  async fetch(): Promise<string[]> {
    return safe(
      async () => {
        const arr = await request<string[]>("/watchlist");
        return (Array.isArray(arr) ? arr : []).filter(
          (c) => typeof c === "string" && /^\d{6}$/.test(c),
        );
      },
      () => loadWatch(),
    );
  },

  /**
   * POST /api/watchlist body { codes: string[] } → { added, total }
   * 失败时 fallback 到 localStorage。
   */
  async add(codes: string[]): Promise<{ added: number; total: number }> {
    return safe(
      async () => {
        const r = await request<{ added?: number; total: number }>("/watchlist", "POST", { codes });
        return {
          added: r.added ?? r.total ?? codes.length,
          total: r.total ?? codes.length,
        };
      },
      () => {
        const existing = loadWatch();
        const incoming = codes.filter((c) => !existing.includes(c));
        const next = [...existing, ...incoming];
        saveWatch(next);
        return { added: incoming.length, total: next.length };
      },
    );
  },

  /**
   * DELETE /api/watchlist/{code} → boolean
   * 失败时 fallback 到 localStorage。
   */
  async remove(code: string): Promise<boolean> {
    return safe(
      async () => {
        await request<void>(`/watchlist/${code}`, "DELETE");
        return true;
      },
      () => {
        const existing = loadWatch().filter((c) => c !== code);
        saveWatch(existing);
        return true;
      },
    );
  },

  /** 纯 localStorage 写入（fallback 内部使用 / 调试用） */
  saveLocally(codes: string[]) {
    saveWatch(codes);
  },
};
