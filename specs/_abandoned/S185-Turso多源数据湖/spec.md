# Spec: S185 — Turso 多源全量交易数据湖（盘中沉淀 + 提前积累）

> 状态：草案 v2（grill 6 视角 rethink + 用户"分开设计"——数据湖只读 vs 生产本地 SQLite 分开）

## grill rethink（2026-09-11，6 视角 verdict=revise）

### 3 CRITICAL
1. **§5.1 臆造 API**——`libsql_client.connect(file:...?libsql://...?replicaMode=embedded)` 不存在。真实 API 是 `import libsql; libsql.connect(local, sync_url=url, auth_token=token, sync_interval=5, offline=False)`（模块名 libsql 非 libsql_client，kwarg 非 URL query，replicaMode 不存在）。
2. **无降级设计**——Turso 未注册/挂了/GFW 断时全量数据收集（R3-R7）一起挂。项目已有 DependencyMissing + circuit_breaker + data_status 范式可复用。
3. **baostock 单 socket 不可并发**——单 TCP socket singleton + recv(8192) 无 timeout，asyncio.to_thread 并发 = 响应交错损坏。serial-only。

### 7 表 5 重复（复用现有非重建）
- `ofi_snapshots`——复用现有 `intraday_ofi_snapshots(date,ts,code,ofi,ofi_abs,bid_ask_pressure,buy_vols_json,sell_vols_json,seal_amount,regime,snapshot_at)`，spec 的 bid1-5/ask1-5/seal_sincerity 是**错列名**
- `kline_5min`——复用 `baostock_5min_freeze(date,code,bars_json,bar_count)` JSON blob 模式
- `zt_pool`——PK 改回 `(date,code)` + source 非键（匹配 zt_history_store 现有 DELETE+INSERT 单源去重）
- `hithink_snapshots`——改结构化列（endpoint,code,datetime,price,pe_ttm,pb_mrq,...）非 raw JSON（绕过 S163 质量门）

### 9GB 全量撞墙（砍 scope 5-10×）
- OFI 全市场 4GB/DAY（9GB 2.5 天撞墙）→ 限涨停池 ~20-50 股（非 5226）
- kline_5min 5226×48×250=6.27GB/yr → 限涨停池 ~50-100 股 + 历史 1-2 年
- 日K 0.5GB/5yr → 可全量

### 推荐方案（KISS 路径 A 首选）
**路径 A**：零 libsql 依赖——stdlib sqlite3 本地写入零改动 + cron `turso_sync` 用 HTTP REST 推 Turso（天然降级，Turso 挂本地照跑）
**路径 B**（备选）：libsql-experimental（Rust binding，真支持 embedded replica）+ get_conn() 适配器（try libsql except sqlite3）+ extras_require={'turso':[...]}（可选依赖，非 base requirements）

### 分开设计（用户要求）
- **生产 DB**（.vibe-research/ 本地 SQLite）：trade_journal/market_data/gene_scores/winrate 等，实时写入，私有不入云
- **数据湖**（Turso 多源只读）：baostock kline/5min + tencent 五档 + hithink 快照 + 涨停池 + 三表，全量拉取只读沉淀，供后期测试（回测/§44）+ 开发（调试盘中策略）
- 物理分离——数据湖不混生产 DB，独立只读数据源

### 降级三态
1. 纯本地（VR_TURSO_URL 未设）→ sqlite3.connect(local) 当前模式
2. embedded replica connected → 本地读写 + 后台 sync Turso
3. 云同步失败降本地 → circuit_breaker('turso') 包 sync，OPEN 跳过不阻塞写入 + stale 标注（last_synced_at + data_status=ok/stale/degraded）

### 异步设计（轻量 asyncio 非 arq）
- 跨源并发 asyncio.gather(to_thread(baostock_serial), to_thread(tencent_batched), to_thread(hithink_throttled))
- baostock serial-only（单 socket）+ tencent 分批 50-500/batch（不封 IP 10-20 并发）+ hithink 如需限流从零 Semaphore（spec 臆造 Semaphore=2 代码库零命中）
- tenacity network_retry 只用于无内置 retry 的源（baostock/tencent），hithink/em_get 跳过（已有内置 retry，3×3=9 叠加爆炸）
- 断点续传 per-batch checkpoint（每 100 股 commit + done set，crash 跳过）
- dual-write 过渡期（DUAL_WRITE=true 同时写旧+Turso，2 周对比后切单）
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
