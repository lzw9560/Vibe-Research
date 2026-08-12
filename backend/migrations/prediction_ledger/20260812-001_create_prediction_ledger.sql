-- S061 R1.1: 预测账本表
-- 记录系统判断（含未执行的），与 winrate_records（交易）语义分离
CREATE TABLE IF NOT EXISTS prediction_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stated_at TEXT NOT NULL,           -- 预测发出日（YYYY-MM-DD）
    source TEXT NOT NULL,              -- funnel_candidate | strategy_hit | manual
    signal_ref TEXT,                   -- funnel:final / 战法 code / 空
    code TEXT NOT NULL,                -- 股票代码
    name TEXT,                         -- 股票名称
    prediction_type TEXT NOT NULL,     -- next_day_premium | strategy_outcome
    baseline_price REAL,               -- 基准价（入场价/信号日收盘价）
    expected TEXT,                     -- 预期方向（如 >0 / 止盈 / 止损）
    horizon INTEGER NOT NULL,          -- 验证周期（天数；1=次日）
    due_date TEXT NOT NULL,            -- 到期日（stated_at + horizon 个交易日）
    actual_return REAL,                -- 实际收益（到期填）
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | hit | miss | expired | voided
    attribution TEXT,                  -- 归因备注（K 线缺失等）
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_at TEXT,
    UNIQUE(stated_at, source, code)    -- 幂等：同日同源同股一条
);

CREATE INDEX IF NOT EXISTS idx_prediction_status ON prediction_ledger(status);
CREATE INDEX IF NOT EXISTS idx_prediction_due_date ON prediction_ledger(due_date);
CREATE INDEX IF NOT EXISTS idx_prediction_source ON prediction_ledger(source);
CREATE INDEX IF NOT EXISTS idx_prediction_stated_at ON prediction_ledger(stated_at);
