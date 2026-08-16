# Spec: S070 — intraday 数据采集管道（盘中 ephemeral → 盘后离线 §44）

> 状态：草案
> 作者：lzw  日期：2026-08-16
> 关联：S069（每日 forward_test 管道）、S055（盘中封单时序采集）、S066 §44（验证 bar）

## 1. 问题 / 目标

§44 grill reframe 结论：public EOD 因子（8 涨停史 1.6x、板块热度 1.2x）对"次日涨停/溢价"全 <2x（死）。
涨停是**催化/资金驱动**，edge 若存在只在 **intraday ephemeral 数据**（封单动量、实时资金流、tick）里——
但当前 intraday 数据近期-only（封单 2 日 / 资金流 1 日）→ §44 验证日历阻塞。

**目标**：建 intraday 采集管道（盘中捕获→持久化→日积）→ 盘后离线 §44 验证 intraday 因子能否破 2x →
若破 → 盘前用 intraday edge 选股 → 盘中执行。即便 edge 不成，intraday 采集对"盘后复盘/风控"仍有值
（foundation，非纯 alpha 押注）——对齐用户"盘前盘后承担更多、给盘中做依赖"哲学。

## 2. 背景

- S055 `seal_intraday_collect`（盘中封单时序，cron 交易时段 60s）→ `seal_intraday_snapshots`（ts/date/code/seal_amount...）。
  封单**trajectory**（日内 delta）可从 snapshots 导出（无需新 fetch），但仅 2 日积累。
- 资金流：`astock.stock_fund_flow_120d`（fflow/daykline，**日级**非 intraday；实测近期-only 1 日）。
  intraday 资金流需 fflow/kline 实时端点（TBD，走 em_get 限流）。
- §44 bar：lift>=2x + CI 不重叠 + n>=30。
- 诚实先验：§44 模式（public EOD 全 <2x）暗示 intraday 也可能 <2x——但 intraday **dynamics**（封单 trajectory、
  实时资金流）是未测的不同类（非 EOD snapshot），有破 2x 的可能（untested）。

## 3. 需求清单

- [ ] R1（封单 trajectory）：从 seal_intraday_snapshots 算日内封单 trajectory（delta/max/min/slope）→ 持久化（intraday_features 表或扩 snapshots）。
- [ ] R2（资金流 intraday 采集）：探 em_get fflow/kline 实时端点，盘中采集个股实时资金净流入 → 持久化。
- [ ] R3（持久化 + 日积）：intraday_features 表（date/code/feature...）；scheduled 采集日积。
- [ ] R4（盘后 §44）：日积满 ~30 日后，§44 验证 intraday 因子（封单 trajectory / 资金流）→ 次日涨停/溢价 lift。
- [ ] R5（诚实标注）：未满 30 日标探索性；不破 2x 标噪声；破 2x 才接入选股。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | 扩 seal_intraday_collect 或新增 intraday_fund_flow_collect executor |
| `backend/strategies/intraday_features.py`（新） | 封单 trajectory 计算 + 资金流 intraday fetch |
| `backend/data/sources/eastmoney.py` | fflow/kline intraday 端点（若 R2 可行） |
| `backend/tools/intraday_edge_validation.py`（新） | §44 验证 intraday 因子 → 次日涨停/溢价 |
| `backend/tests/` | trajectory 计算 + 采集 executor 测试 |

## 5. 设计方案

**两段（采集→验证），验证日历阻塞**：
- **采集（盘中 scheduled）**：R1 封单 trajectory（从 snapshots 导出，零新 fetch，最廉先做）+ R2 资金流 intraday
  （em_get fflow/kline，探端点可行性）。持久化 intraday_features，日积。
- **验证（盘后，~30 日后）**：R4 §44 验证 intraday 因子 → 次日涨停/溢价。复用 sector_heat_validation 口径
 （热/冷分位 + Wilson CI + lift）。

**先验诚实**：§44 public EOD 全死的模式暗示 intraday 也可能 <2x。R1（trajectory）零成本（导出现有 snapshots）
先做——即便最终无 edge，trajectory 对盘后复盘（封单衰减形态）仍有值。R2（资金流 intraday）需探端点，
若端点不可行/限流重则 defer。

## 6. 验收标准

- [ ] A1 R1：封单 trajectory 从 snapshots 算出 + 持久化（intraday_features 日积）。
- [ ] A2 R2（若可行）：资金流 intraday 采集 + 持久化。
- [ ] A3 ~30 日后 §44：intraday 因子 → 次日涨停 lift 报告（破 2x → 接选股；<2x → 标噪声 + 考虑 pivot (b)）。
- [ ] A4 诚实：未满 30 探索性；不臆造（缺数据标 None）。

## 7. 合规自查（弱合规，§1.2 工程底线）

- [x] 不臆造：intraday 数据来自 em_get/采集真实；缺标 None。
- [x] 私有数据隔离：intraday_features 存 VR_DATA_DIR（不入 git）。
- [x] 防封：em_get 限流熔断（fflow 端点走 em_get，不裸调）。
- [x] §13.0：foundation 数据管道（找 edge 的数据采集），非新 alpha 战法层；edge 是 bonus（不成也有复盘值）。
