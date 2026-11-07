# datalake SCHEMA

> 权威数据存储在 `~/.vibe-research/`（由 `vr_paths.resolve_data_dir()` 解析）。
> 本文档定义核心库表结构，供 DuckDB MCP 和因子工程使用。

## 目录结构

```
.vibe-research/
├── baostock_kline_cache.db      # 1.3G — A 股全市场 K 线（5255 codes）
├── dragon_tiger_history.db       # 450M — 龙虎榜历史
├── intraday_accumulation/
│   └── intraday_microstructure.db # 344M — 盘中 5min/auction/OFI/quote 快照
├── seal_intraday_2026.db         # 147M — 封单快照（当年，按月分表）
├── seal_intraday.db              # 107M — 封单快照（历史年 + 炸板预警）
├── datalake/
│   ├── ticks_YYYYMM.db           # 按月分库 — mootdx 分笔数据
│   └── stoke_YYYYMM.db           # 按月分库 — 研报/新闻/强势股/PE-PB
├── market_data.db                # 11M — workflow_state/scheduled_tasks/notes
├── gene_scores.db                # 5M — 因子评分/forward_test/universe_returns
├── zt_history.db                 # 4M — 涨停历史
├── trade_journal.db              # 2M — 交易日志/arm_status
├── funnel_cache.db               # 10M — funnel_results
├── verifier_recorder/
│   └── recorder.db               # 14M — verifier_records
├── pit_store/
│   └── pit_store.db              # 7M — snapshots
├── seat_profiles.db              # 584K — 席位画像
├── sti_timeline.db               # 192K — STI 情绪时间线
├── winrate.db                    # 384K — prediction_ledger/winrate_records
├── verification_card.db          # 28K — 验证条件
├── circuit_breaker_state.db      # 12K — breaker_state
├── evaluation_lifts.db           # 12K — dimension_lift_overrides
└── vr.db                         # 12K — price_alerts
```

## baostock_kline_cache.db

| 表 | 说明 |
|---|---|
| `kline` | 主表，每 code 一行 bars_json（WITHOUT ROWID） |
| `regime_gate_combo_log` | regime gate combo 日志 |

### kline 表结构
| 列 | 类型 | 说明 |
|---|---|---|
| code | TEXT PK | 6 位裸 code（如 000001） |
| bars_json | TEXT | JSON 数组，每个元素含 date/open/high/low/close/volume |

覆盖范围：5255 codes，2018-01-02 至今。

## dragon_tiger_history.db

| 表 | 说明 |
|---|---|
| `dragon_tiger_rows` | 龙虎榜明细 |
| `fetch_log` | 抓取日志 |
| `sqlite_sequence` | SQLite 内部 |

## intraday_microstructure.db

| 表 | 说明 |
|---|---|
| `baostock_5min_freeze` | 5 分钟冻结快照 |
| `intraday_auction_snapshots` | 集合竞价快照 |
| `intraday_ofi_snapshots` | OFI（Order Flow Imbalance）快照 |
| `intraday_quote_snapshots` | 行情快照 |
| `intraday_ranking_snapshots` | 排名快照 |

## datalake/ticks_YYYYMM.db

### ticks 表
| 列 | 类型 | 说明 |
|---|---|---|
| date | TEXT NOT NULL | YYYY-MM-DD |
| code | TEXT NOT NULL | 6 位裸 code |
| time | TEXT | HH:MM:SS |
| price | REAL | 成交价 |
| vol | INTEGER | 成交量（手） |
| buyorsell | INTEGER | 1=主动买 2=主动卖 0=中性 |
| volume | INTEGER | 成交量（股） |

索引：idx_ticks_date_code(date, code)

## datalake/stoke_YYYYMM.db

| 表 | 说明 |
|---|---|
| `research_reports` | 研报（date/code/report_name/institution/rating/raw_json） |
| `news` | 新闻（date/code/title/content/time/source） |
| `strong_stocks` | 强势股（date/code/name/pct/reason/industry） |
| `pe_pb` | PE-PB（date/name/pe/pb） |

## 写入 API

- `datalake/store.py::save_stoke_data(date_str, items)` → stoke_YYYYMM.db
- `datalake/store.py::save_ticks(date_str, code, ticks)` → ticks_YYYYMM.db
- `engine/kline_cache_store.py` → baostock_kline_cache.db
- `data/zt_history_store.py` → zt_history.db
- `engine/trade_journal.py` → trade_journal.db
- `candidate_funnel/funnel_cache.py` → funnel_cache.db

## DuckDB 查询示例

```sql
-- 查 baostock K 线（通过 DuckDB ATTACH SQLite）
ATTACH '.vibe-research/baostock_kline_cache.db' AS bk (TYPE SQLITE);
SELECT code, json_array_length(bars_json) AS bar_count FROM bk.kline ORDER BY bar_count DESC LIMIT 10;

-- 查龙虎榜
ATTACH '.vibe-research/dragon_tiger_history.db' AS dt (TYPE SQLITE);
SELECT * FROM dt.dragon_tiger_rows LIMIT 10;

-- 直接查 CSV（无需导入）
SELECT * FROM read_csv_auto('path/to/file.csv') LIMIT 100;
```

## 数据访问规则

1. **所有代码走 `vr_paths.resolve_data_dir()`**（P2 收口后强制）
2. **DuckDB MCP 用 ATTACH 查 SQLite**（不迁移数据，直接查）
3. **按月分库的 DB 不跨月查询**（ticks_202609 只含 9 月数据）
4. **baostock K 线是 bars_json 格式**（不是行式，需 JSON 解析）
