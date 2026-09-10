// S178: OFI 盘中数据只读看板契约（contract-first，仿 journal-contract.ts）。
// 后端 GET /api/intraday/ofi?date=&code=&limit= 返 {snapshots,count,date,truncated}。
// honest label「conditioning 数据收集 · 非交易信号」——read-only，非信号生成器。

export interface OfiSnapshot {
  date: string;
  ts: string;
  code: string;
  ofi: number;                // ∈ [-1,1] 归一化 (Σbuy-Σsell)/(Σbuy+Σsell)
  ofi_abs: number;            // Σbuy-Σsell
  bid_ask_pressure: number;   // Σbuy/Σsell（涨停 sell=0 cap 999）
  buy_vols_json: string;      // 五档量 JSON（重算用）
  sell_vols_json: string;
  seal_amount: number | null; // 涨停封单额
  regime: string | null;      // strong_trend/weak/bear（conditioning 分层）
  snapshot_at: string;
}

export interface OfiResponse {
  snapshots: OfiSnapshot[];
  count: number;
  date: string;
  truncated: boolean;
}
