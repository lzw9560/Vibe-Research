# 知识图谱图算法分析报告

> 自动生成于 `graph_analysis.py`。数据源：`/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing`

## 1. 图谱统计

| 指标 | 值 |
|---|---|
| 节点数 | 2709 |
| 有向边数 | 6860 |
| 无向边数（去重） | 6530 |
| 密度 | 0.00178 |

## 2. Top 20 Hub 节点（入度中心性）

> 入边最多 = 被引用最多 = 知识图谱的中心实体。

| 排名 | 实体 | 入度 |
|---|---|---|
| 1 | `stocks/` | 865 |
| 2 | `data-sources/eastmoney-push2` | 740 |
| 3 | `data-sources/tencent` | 402 |
| 4 | `reports/` | 379 |
| 5 | `concepts/` | 375 |
| 6 | `data-sources/` | 351 |
| 7 | `industries/` | 173 |
| 8 | `strategies/` | 156 |
| 9 | `concepts/list_date:` | 79 |
| 10 | `events/` | 71 |
| 11 | `specs/` | 63 |
| 12 | `concepts/涨停池` | 55 |
| 13 | `indices/000300` | 49 |
| 14 | `indices/000905` | 30 |
| 15 | `concepts/人工智能` | 29 |
| 16 | `concepts/华为概念` | 27 |
| 17 | `concepts/新能源车` | 26 |
| 18 | `industries/半导体` | 25 |
| 19 | `valuations/` | 22 |
| 20 | `metrics/` | 20 |

## 3. 社区发现（标签传播 LPA）

共发现 **16** 个社区（含孤立）。Top 10 社区：

| 社区 ID | 成员数 | Top 5 成员 |
|---|---|---|
| 514 | 1542 | `data-sources/eastmoney-push2` `data-sources/tencent` `concepts/` `data-sources/` `industries/` |
| 1687 | 745 | `stocks/` `reports/` `actions/` `analysts/曾朵红-东吴证券` `analysts/刘孟峦-国信证券` |
| 2164 | 88 | `strategies/` `events/2026-09-04-竞价异动` `events/2026-09-05-涨停池` `events/2026-09-07-异动` `events/2026-09-07-涨停池` |
| 1153 | 72 | `specs/` `valuations/` `dragon-tiger/` `metrics/` `analysts/李林卉-太平洋` |
| 1548 | 70 | `industries/电力设备` `stocks/603118` `stocks/603626` `10_Reference/meta/` `logic/cross-domain-gate` |
| 729 | 12 | `logic/` `reviews/` `actions/approve-entity` `logic/实体改名` `new` |
| 734 | 10 | `stocks/*` `analysts/*` `concepts/*` `dragon-tiger/席位` `events/涨停` |
| 1216 | 8 | `analysts/夏昌盛-国金证券` `analysts/方丽-国金证券` `analysts/洪希柠-国金证券` `analysts/舒思勤-国金证券` `reports/000415-2026-04-29-财务费用大幅下降，26Q1归母净利润+3` |
| 14 | 6 | `agents/` `agents/fundamental_analyst` `agents/hot_money_tracker` `agents/policy_analyst` `agents/lockup_monitor` |
| 1248 | 6 | `analysts/任鹤-国信证券` `analysts/王粤雷-国信证券` `analysts/王静-国信证券` `reports/000560-2026-04-24-2025年业绩承压，既受行业趋势拖累也有` `reports/000560-2026-09-03-住房交易业务竞争优势凸显，资产管理业务发` |

## 4. 桥节点（跨社区连接者）

> 邻居分布在 >=3 个社区的节点——信息在不同子图间流动的枢纽。

| 实体 | 跨社区数 | 总度数 |
|---|---|---|
| `stocks/` | 11 | 862 |
| `MOC` | 9 | 35 |
| `reports/` | 8 | 379 |
| `specs/` | 8 | 50 |
| `data-sources/` | 6 | 338 |
| `actions/` | 5 | 15 |
| `strategies/` | 4 | 147 |
| `specs/DEC-003` | 4 | 11 |
| `specs/DEC-004` | 4 | 10 |
| `dragon-tiger/603118-2026-08-24` | 4 | 4 |
| `dragon-tiger/603626-2026-08-21` | 4 | 4 |
| `data-sources/eastmoney-push2` | 3 | 682 |
| `data-sources/tencent` | 3 | 409 |
| `events/` | 3 | 66 |
| `valuations/` | 3 | 21 |
| `data-sources/akshare` | 3 | 18 |
| `specs/archive/m0-foundation/S008-后端数据层迁移` | 3 | 14 |
| `logic/causal-chains` | 3 | 13 |
| `specs/archive/m0-foundation/S017-A股涨跌预测模型栈` | 3 | 12 |
| `data-sources/eastmoney-datacenter` | 3 | 12 |

## 5. 示例最短路径

- `stocks/600519` → `specs/S007`：无路径（不连通）
- `stocks/000001` → `industries/食品饮料`：`stocks/000001` → `data-sources/eastmoney-push2` → `industries/食品饮料`（2 跳）
- `events/2026-09-07-涨停池` → `strategies/dragon_head`：`events/2026-09-07-涨停池` → `strategies/` → `MOC` → `strategies/dragon_head`（3 跳）

---

## 方法说明

- **建图**：扫描 vault 内所有 `.md`（排除 templates/index），解析正文 `[[]]` 双链为有向边，剥去 frontmatter 避免误解析。
- **Hub（入度中心性）**：`in_degree` 最高的节点，被引用最多。
- **社区发现（LPA）**：标签传播算法，15 轮迭代或收敛即停。简化版，单机标准库。
- **桥节点**：邻居分布在 >=3 个社区的节点，度量跨子图连接能力。
- **最短路径**：BFS。
