// 关注股票（自选股）—— 后端 API 持久化，localStorage 仅作 fallback。

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
  localStorage.setItem(KEY, JSON.stringify(codes));
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
        const resp = await fetch("/api/watchlist");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        // 后端可能直接返回数组，也可能包在 data 字段里
        const arr = Array.isArray(json) ? json : (Array.isArray(json?.data) ? json.data : []);
        return arr.filter((c: string) => typeof c === "string" && /^\d{6}$/.test(c));
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
        const resp = await fetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ codes }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        return {
          added: json.added ?? json.total ?? codes.length,
          total: json.total ?? codes.length,
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
        const resp = await fetch(`/api/watchlist/${code}`, { method: "DELETE" });
        return resp.ok;
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
