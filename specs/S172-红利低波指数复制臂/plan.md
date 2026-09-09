# Plan: S172 — 红利低波指数复制臂（A 臂 floor）

> spec: spec.md  状态：已定稿  日期：2026-09-09

## 1. 取舍与备选

### 1.1 数据源（spec §5.1 补充）

spec §5.1 列了 3 个 akshare 函数，但 R3 跟踪误差需要 4 个——ETF 历史净值收益未列。补全：

| 数据 | akshare 函数 | 用途 | 防封 |
|---|---|---|---|
| ETF 512890 实时行情 | `fund_etf_spot_em()` | R1 spot | push2delay（ut 内嵌，非 push2 裸调）|
| **ETF 512890 历史复权净值** | `fund_etf_hist_em(symbol='512890', adjust='qfq')` | **R3 跟踪误差 ETF 端** | push2delay |
| 930955 指数历史 | `index_zh_a_hist(symbol='930955')` | R3 跟踪误差 index 端 | push2delay |
| 930955 published 成分权重 | `index_stock_cons_weight_csindex('930955')` | R2 对比（非复制）| csindex.com.cn（非东财，无防封问题）|

spec §5.1 说 `fund_etf_spot_em` "走东财 datacenter"——实际 akshare 源码用 `push2delay.eastmoney.com`（push2 延时镜像），ut token 已内嵌在 akshare params 里。结论不变（不需 `em_get` 限流，push2delay 延时镜像封 IP 风险远低于 push2 实时），技术细节修正。

### 1.2 备选方案为何不选

- **hithink ETF 行情端点**：已集成但非必要——akshare `fund_etf_spot_em` / `fund_etf_hist_em` 够用且免费。hithink 降级备用（spec §9 风险表已列）。
- **csindex 直取指数历史**：`index_zh_a_hist` 走东财已含 930955，不需额外接 csindex 行情 API。`index_stock_cons_weight_csindex` 只取成分权重（csindex 专有），历史行情走东财更统一。
- **不复权 ETF 历史**：必须 `adjust='qfq'`（前复权）——ETF 分红除权不复权则收益序列有跳空，跟踪误差算错。spec §5.4 "ETF 净值收益（复权）"即此。

### 1.3 不接 accounting

ETF 管理费已含净值（你看到的净值是扣费后），市场收益即净收益。无 stop-loss / take-profit（长线底仓 hold，spec R6）。故不接 `accounting` 模块——与打板 / 短线臂的 accounting 接线完全解耦。

## 2. 模块拆分

### 2.1 `backend/tools/fetch_etf_tracking.py`（取数 + 跟踪误差）

```
fetch_etf_tracking.py
  ├─ _ak()                           # 惰性 import akshare（akshare_src 模式）
  ├─ fetch_etf_quote(code='512890')  # R1：fund_etf_spot_em 筛 512890 → dict
  ├─ fetch_etf_hist(code, start, end) # R3 ETF 端：fund_etf_hist_em(adjust='qfq') → [{date, close, ret}]
  ├─ fetch_index_hist(symbol, start, end) # R3 index 端：index_zh_a_hist → [{date, close, ret}]
  ├─ fetch_index_cons_weight(index='930955') # R2：成分权重 → [{code, name, weight}]
  └─ tracking_error_report(etf_code='512890', index_code='930955', windows=None) # R3 汇总
```

- akshare 惰性 import（`_ak()` 函数，akshare_src.py 模式）——akshare 缺失 raise DependencyMissing
- akshare 调用间 `time.sleep(2)` 惯例（spec §5.1 防封说明，低量一次性）
- 取数失败返空 dict / 空列表，诚实降级不臆造（akshare_src chip_distribution 模式）
- 跟踪误差口径：日收益序列做差 → std(diff) × sqrt(252) 年化（spec §5.4）
- 窗口默认：近 1 月（~21 交易日）/ 3 月（~63）/ 6 月（~126）/ 1 年（~252）

### 2.2 `backend/strategies/index_replication_floor.py`（建仓 + 持有 + 周报）

```
index_replication_floor.py
  ├─ _FLOOR_DIR                      # resolve_data_dir() / 'etf_floor'
  ├─ _atomic_write_json(path, data)  # atomic write（scan_long_value_cache 模式）
  ├─ build_position_batches(total=100000, n_batches=5, interval_days=7, one_shot=False) # R4
  ├─ record_batch(batch_idx, date, price, shares, amount) # 写 batches.json
  ├─ hold_status()                   # 读 batches.json → 持仓状态
  └─ weekly_report()                 # R5：持仓市值 + 成本基 + 浮动盈亏 + 跟踪误差
```

- 私有数据写 `resolve_data_dir() / 'etf_floor' / 'batches.json'`（vr_paths 模式，.gitignore）
- atomic write（`tmp + os.replace`，scan_long_value_cache.py:58 模式）
- `build_position_batches` 生成计划（日期 / 金额 / 批次），不自动下单——用户确认后 `record_batch` 记录实盘
- `weekly_report` 调 `fetch_etf_quote`（实时市值）+ `tracking_error_report`（跟踪误差）+ `hold_status`（成本基）汇总
- 无 stop/take 代码（grep 确认，A6 验收）

## 3. 依赖序

```
vr_paths.py（已存在，复用 resolve_data_dir）
  ↑
fetch_etf_tracking.py（新建，依赖 akshare + vr_paths）
  ↑
index_replication_floor.py（新建，依赖 fetch_etf_tracking + vr_paths）
  ↑
tests/test_fetch_etf_tracking.py + test_index_replication_floor.py（新建，mock akshare）
```

- 不改 `vr_paths.py`（复用 `resolve_data_dir()`）
- 不改 `accounting/*`（不接）
- 不改 `scheduled_tasks.py`（不接 cron，spec §4 可选后续）
- 不改其他 verdict / harness / claude 兜底

## 4. 数据流

```
建仓：
  build_position_batches(100000, 5, 7)
    → [{batch:1, date:2026-09-10, amount:20000, status:'planned'}, ...]
  → record_batch(0, date, price, shares, amount)
    → batches.json（.vibe-research/etf_floor/）

周报：
  weekly_report()
    ├─ hold_status()           ← batches.json（成本基 + 持仓份数）
    ├─ fetch_etf_quote('512890') ← fund_etf_spot_em（实时价格 → 市值）
    └─ tracking_error_report()   ← fund_etf_hist_em + index_zh_a_hist（跟踪误差）
    → {market_value, cost_basis, unrealized_pnl, tracking_error, ...}
```

## 5. 测试策略

- **离线单测**（mock akshare）：
  - `test_fetch_etf_tracking`：monkeypatch akshare 返回固定 DataFrame，验取数解析 + 跟踪误差计算口径（std(diff)×sqrt(252)）
  - `test_index_replication_floor`：monkeypatch fetch_etf_quote + tracking_error_report，验分批建仓计划 + 周报格式 + atomic write
  - VR_DATA_DIR 隔离（conftest.py 已设 tmp 目录）
- **联网验收**（A1-A5 手动跑，不进 pytest）：
  - `backend/.venv/bin/python -c "from tools.fetch_etf_tracking import fetch_etf_quote; print(fetch_etf_quote('512890'))"`
- **不破坏现有**：`pytest -m "not live"` 全绿（A7）
