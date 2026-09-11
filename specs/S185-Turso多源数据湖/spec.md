# Spec: S185 — Turso 多源全量交易数据湖（盘中沉淀 + 提前积累）

> 状态：草案
> 作者：Claude  日期：2026-09-11
> 关联：S184 kline_refresh 方案 0 / S176 OFI 收集器 / S163 数据质量门 / wc98ebhlh 云资源调研（Turso 9GB）/ w3pvh9q8f 数据基建 grill / memory prefer-historical-data-over-wait / memory data-source-capabilities

## 1. 问题 / 目标

用户要：Turso 做**多源全量交易数据湖**——全量拉取不同数据源交易数据（尤其盘中数据）入 Turso，供后期调试盘中策略做数据沉淀 + 其他交易数据提前积累。

一句话：用 Turso（9GB 免费 libSQL 云 SQLite）做多源（baostock/tencent/hithink/ths/em/sina）全量交易数据湖，盘中数据（五档/5min/实时快照）优先沉淀，供后期盘中策略调试 + 历史回测。

## 2. 背景

- wc98ebhlh 调研：Turso 9GB 免费 + libSQL SQLite 分支 SQL 100% 兼容 + 500 DB + HTTP 协议（GFW 友好）
- w3pvh9q8f grill：baostock kline JSON 164MB 反模式 + 157MB×2 内存 + 无云备份
- memory data-source-capabilities：baostock（kline/5min/profit/行业 不封 IP）+ tencent（五档不封 IP）+ hithink（5 endpoint 实时 key）+ ths/em（涨停池 em_get 限流）+ sina（三表）
- S176 OFI 收集器：tencent 五档 + 封单诚意已建（intraday_ofi.py 纯函数 + ofi_collect cron */3 9-14）
- memory tencent-gtimg-5level-latent：qt.gtimg 五档 latent（_parse_gtimg 加 ~20 行可解 OFI 3s→1s 瓶颈）
- 用户"优先拉历史数据不等未来"（memory prefer-historical-data-over-wait）

## 3. 需求清单

- [ ] R1：Turso 接入基建——libsql-client + embedded replica（本地 SQLite 读写 + 后台同步 Turso）+ VR_TURSO_URL/TOKEN env
- [ ] R2：schema 设计——kline（日 K）+ kline_5min（盘中 5min）+ ofi_snapshots（五档 OFI）+ hithink_snapshots（实时快照）+ zt_pool（涨停池）+ financial（三表）+ profit（epsTTM）表
- [ ] R3：baostock 日 K 全量拉取入 Turso（替代 JSON 164MB）——refresh_kline_cache.py 改 INSERT OR REPLACE 写 Turso
- [ ] R4：baostock 5min bars 盘中数据沉淀——fetch_5min_bars 全量拉 + 入 kline_5min 表（盘中策略调试原料）
- [ ] R5：tencent 五档（qt.gtimg）盘中全量拉取——S176 OFI 收集器扩展，_parse_gtimg 加五档解析 + 入 ofi_snapshots（不封 IP 无限流）
- [ ] R6：hithink 实时快照沉淀——5 endpoint（行情/估值/指数/板块/特色）定时快照入 hithink_snapshots（盘中策略调试 + 回测）
- [ ] R7：ths/em 涨停池 + sina 三表 + baostock profit 全量入 Turso（其他交易数据提前积累）
- [ ] R8：数据质量门 + 血缘扩展（S163 扩展到 Turso）+ 私有数据隔离（key/持仓不入云只市场数据）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/data/turso_client.py | 新建：libsql 接入 + embedded replica + 连接管理 |
| backend/data/turso_schema.sql | 新建：kline/kline_5min/ofi_snapshots/hithink_snapshots/zt_pool/financial/profit 表 CREATE |
| backend/tools/refresh_kline_cache.py | 改：INSERT OR REPLACE 写 Turso（替代 JSON） |
| backend/data/sources/baostock_src.py | 扩展：fetch_5min_bars 全量拉 + 入 Turso |
| backend/engine/intraday_ofi.py | 扩展：_parse_gtimg 五档 + 入 ofi_snapshots |
| backend/scheduler/executors/intraday.py | 扩展：ofi_collect 全量拉 + 写 Turso |
| backend/data/zt_history_store.py | 扩展：zt_pool 入 Turso（P0-2 fallback 后） |
| requirements.txt | 加 libsql-client |
| .env | VR_TURSO_URL / VR_TURSO_TOKEN |

## 5. 设计方案

### 5.1 Turso embedded replica（本地优先 + 云同步）

```python
# turso_client.py
import libsql_client
# embedded replica：本地 SQLite 文件读写 + 后台同步 Turso 云
def get_conn():
    return libsql_client.connect(
        f"file:.vibe-research/turso_local.db?libsql://{TURSO_DB}.turso.io?auth_token={TURSO_TOKEN}&replicaMode=embedded"
    )
```

### 5.2 schema（多源交易数据湖）

- `kline(code, date, open, high, low, close, volume, amount, turn, pctChg, isST, source, PRIMARY KEY(code, date))`——日 K
- `kline_5min(code, datetime, open, high, low, close, volume, PRIMARY KEY(code, datetime))`——盘中 5min
- `ofi_snapshots(code, datetime, bid1-5, ask1-5, ofi, bid_ask_pressure, seal_sincerity, PRIMARY KEY(code, datetime))`——五档 OFI
- `hithink_snapshots(endpoint, code, datetime, snapshot_json, PRIMARY KEY(endpoint, code, datetime))`——实时快照
- `zt_pool(date, code, name, lbc, reason, source, PRIMARY KEY(date, code, source))`——涨停池
- `financial(code, period, revenue, profit, roe, PRIMARY KEY(code, period))`——三表
- `profit(code, year, quarter, epsTTM, PRIMARY KEY(code, year, quarter))`——epsTTM

### 5.3 盘中数据优先沉淀（用户核心）

盘中策略调试需历史盘中数据。当前盘中数据缺（S176 OFI 只 60d live 累积中）。Turso 全量拉：
- tencent 五档（qt.gtimg 不封 IP）——ofi_collect cron */3 扩展全量 + 入 ofi_snapshots
- baostock 5min——fetch_5min_bars 全量历史 + 日更
- hithink 实时——5 endpoint 盘中定时快照

### 5.4 多源全量拉取（提前积累）

- baostock 日 K（5226 股）——替代 JSON，入 kline 表
- baostock 5min（历史 + 日更）——入 kline_5min
- tencent 五档（盘中全量）——入 ofi_snapshots
- hithink 5 endpoint（实时快照）——入 hithink_snapshots
- ths/em 涨停池——入 zt_pool（P0-2 fallback 后）
- sina 三表——入 financial
- baostock profit——入 profit

### 5.5 私有数据隔离

- API key / 持仓 / 研报 / .env **不入 Turso**（CLAUDE.md §1.2 私有数据隔离）
- 只市场数据缓存 + 盘中快照 + 涨停池 + 三表入 Turso

## 6. 验收标准

- [ ] A1：Turso 接入（libsql + embedded replica + VR_TURSO_URL/TOKEN）
- [ ] A2：7 表 schema 建好 + migration
- [ ] A3：baostock 日 K 全量入 Turso（替代 JSON 164MB）
- [ ] A4：baostock 5min 盘中数据沉淀
- [ ] A5：tencent 五档全量拉 + 入 ofi_snapshots（不封 IP）
- [ ] A6：hithink 实时快照沉淀
- [ ] A7：ths/em 涨停池 + sina 三表 + profit 入 Turso
- [ ] A8：数据质量门 + 血缘扩展 + 私有数据隔离
- [ ] A9：全量测试无回归 + tsc0

## 7. 合规与工程底线自查

- [x] 不臆造：多源全量拉取有数据源能力支撑（memory data-source-capabilities）
- [x] 私有数据隔离：key/持仓不入 Turso（§1.2）
- [x] 不涉 em_get：baostock/tencent 不封 IP；ths/em 涨停池走 em_get 限流（P0-2 fallback 后）
- [x] 工程底线：embedded replica 重算范式（本地优先 + 云同步）

## 8. 测试计划

- turso_client 单测（连接 + replica 同步）
- schema migration 单测
- baostock 日 K 入 Turso 集成测试
- tencent 五档拉取 + ofi_snapshots 写入
- 数据质量门扩展（completeness/timeliness/accuracy）

## 9. 后续可选

- DuckDB 读 Turso 做 §44 截面分析（列式快）
- Turso 查询 API（前端直连 Realtime）
- 多设备同步（Turso 云 + 本地 replica）
