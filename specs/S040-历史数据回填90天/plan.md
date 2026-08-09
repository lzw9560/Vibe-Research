# 技术方案 · S040 历史数据回填 90 天

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 原则：最小改动、照搬现有 pattern、勤 commit。东财走 em_get 限流层。

## 1. 文件结构与职责

### 新增
| 文件 | 职责 |
|---|---|
| `backend/backfill_history.py` | 回填脚本：逐日调 get_screener_result 写 DB，支持 --days/--start/--end/--batch-size/--dry-run |

### 改动
| 文件 | 改动 |
|---|---|
| `backend/backtest_lite.py` | `_calc_next_day_return` 加 kline_cache 参数；`run_backtest_async` + `generate_scatter_data` 内创建 kline_cache 并传入 |
| `backend/limitup_screener/data.py` | 确认/补充 date+code UNIQUE 约束 + INSERT OR REPLACE |

## 2. 回填脚本设计

> 实测修订（2026-08-09）：幂等已由 `PRIMARY KEY (date, code)` + `INSERT OR REPLACE` 保证（§2.3 确认无需改 DB 层）。另需防护：非交易日（周末/节假日/错误日期）`get_screener_result` 返回空 `gene_scores`——脚本必须识别空池日并跳过，否则会在 DB 写入 0 行记录、污染覆盖范围统计。

### 2.1 参数
```bash
python backfill_history.py --days 90 --batch-size 10 --dry-run
python backfill_history.py --start 2026-05-10 --end 2026-08-08 --batch-size 10
python backfill_history.py --days 90  # 分批交互确认后全跑
```

### 2.2 核心流程
```
1. 算日期列表（从 today 前推 N 个交易日，或 --start/--end 区间）
2. 按 --batch-size 分批
3. 每批：
   a. 逐日调 limitup_screener.get_screener_result(date)  # 内部走 em_zt_topic_pool -> transport.py 限流
   b. --dry-run 模式：只打印请求结果（成功/失败/条数），不写 DB
   c. 正式模式：get_screener_result 内部已 save_gene_scores 写 DB（幂等）
   d. 批结束打印：成功率、耗时、熔断器状态
4. 非 --dry-run 且非 --no-confirm：批间暂停等用户输入 y 继续
```

### 2.3 幂等
检查 `limitup_screener/data.py` 的 `save_gene_scores` 实现：
- 若已 INSERT OR REPLACE -> 天然幂等，无需改
- 若为 INSERT -> 加 `CREATE UNIQUE INDEX IF NOT EXISTS idx_gene_date_code ON gene_scores(date, code)` + 改 INSERT OR REPLACE

### 2.4 熔断器感知
脚本捕获 `RuntimeError("CircuitBreaker:eastmoney")` 异常，打印"熔断器 OPEN，等待 60s 恢复"，sleep 65s 后重试当前日。连续 3 次熔断则中止脚本。

## 3. backtest_lite K 线缓存设计

### 3.1 改动
```python
# 原
def _calc_next_day_return(code: str, date_str: str) -> float:
    raw = astock.kline(code, category=4, offset=5)
    bars = kline_from_mootdx(code, raw).bars
    ...

# 改
def _calc_next_day_return(code: str, date_str: str, kline_cache: dict[str, list] | None = None) -> float:
    if kline_cache is not None and code in kline_cache:
        bars = kline_cache[code]
    else:
        offset = kline_cache.pop("_offset", 20) if kline_cache else 5  # 从 cache dict 读 offset
        raw = astock.kline(code, category=4, offset=offset)
        bars = kline_from_mootdx(code, raw).bars
        if kline_cache is not None:
            kline_cache[code] = bars
    ...
```

### 3.2 调用方改动
`run_backtest_async` 和 `generate_scatter_data` 内：
```python
kline_cache: dict[str, list] = {"_offset": window_days + 15}
# ...
next_day_return = _calc_next_day_return(g.code, current, kline_cache)
```

window_days = (end_date - start_date) 转交易日天数，或直接传 90+15。

## 4. 交易日推算

复用 `backtest_lite._next_trading_day` 的日历逻辑，反推 N 个交易日。`trading_calendar.json` 已有节假日。
