# Spec: S107 — 龙虎榜 hithink 集成（维度对齐设计）

> 状态：**已废弃**（2026-09-01，§2 调研完成→结论 (c) 不做，详见 §3）
> 原占位草案（S106 §11 承诺另立，待启动时补全），2026-09-01 调研后归档
> 作者：lzw9560  日期：2026-08-30  归档：2026-09-01
> 级别：N/A（已废弃）
> 关联：S106（§11 范围外处置，龙虎榜维度不同另立）/ S104（hithink_src 已建）/ S131（东财 dragon_tiger_board 承重链 raise_on_failure=True 诚实化）

## 1. 问题 / 目标

S106 评估龙虎榜 hithink 集成时发现**维度不同**，不能简单当 fallback：
- **hithink `special dragon-tiger`**：返 `{stock_items:[{thscode, name, concept_list, ...}]}`——**个股 + 概念维度**（51 股 / 57 席位实测）
- **东财 `dragon_tiger_board`**：返 `{records:[], seats:{buy,sell}, institution:{net_amt}}`——**席位买卖明细 + 机构净额维度**

两源字段**完全不重叠**——不是"同一数据两套口径"，是**两个不同维度的数据**。直接当 fallback 不成立。

> **前提更正（2026-09-01 §2 调研）**：原 §3 (a) 说"hithink 补东财没有的个股+概念维度"，但**东财 `concept_blocks()` 已提供个股概念**（`backend/data/sources/eastmoney.py`），hithink `concept_list` 非独有维度。hithink 真正独有的是 `hot_money_net_value`（股级游资净额）/ `range_days`（连榜天数）/ `hot_money_items`（命名游资→其买入股）——这些是 board-wide 视角，适合独立游资看板，非 first_board_filter 的 per-stock 评分输入。

## 2. 调研结果（2026-09-01 完成，hithink-finance CLI v0.1.7 实测 2026-08-28 数据 51 股/57 席位）

### 2.1 hithink 端点能力

- 端点：`hithink-finance special dragon-tiger`（CLI 已装，API Key 在 `.env` `HITHINK_FINANCE_API_KEY`）
- 参数：仅 `--board-type {all,org,hot_money}` + `--date YYYY-MM-DD`——**无 stock code 参数**，按日取整张榜，非 per-stock 查询。
- 三个 board-type 返回不同结构：
  - **`all`** → `stock_items[]`（per-stock 聚合）+ `hot_money_items:[]`（空）。字段：`thscode/ticker/name`、`concept_list[{name}]`、`change`、`net_value`（总净额·**元**）、`net_rate`、`hot_rank`、`buy_value`/`sell_value`（总买/卖·**元**）、`range_days`（连榜天数）、`hot_money_net_value`（游资净额·元，有则出现）、`org_net_value`（机构净额·元，有则出现）、`limit_reason`（上榜原因，有则出现）。
  - **`hot_money`** → `hot_money_items[]` 填充，每项是**命名游资席位**：`{name:"宁波桑田路", buying:元, rows:[该席位买的 stock_items...]}`。给游资**昵称**，非东财的营业部全名。
  - **`org`** → `stock_items[]` 过滤到有机构活动的股 + `org_net_value`/`org_net_rate`/`org_buy_num`（机构买入席位数）/`org_sell_num`（机构卖出席位数）——**给席位计数不给席位名**。

### 2.2 东财 dragon_tiger_board + first_board_filter 消费者精确需求

- 东财（`backend/data/sources/eastmoney.py:679`，per-stock + look_back=30 天）返 `records:[{date,reason,net_buy(万元),turnover}]`（多日上榜）+ `seats:{buy:[{name(营业部全名),buy_amt,sell_amt,net(万元)}],sell:[...]}`（TOP5 命名席位明细）+ `institution:{buy_amt,sell_amt,net_amt(万元)}`（机构专用席位净额，latest 上榜日）。
- **first_board_filter 消费者**：
  - `score_dim2_hot_money`（`first_board_filter.py:718`）：只用 `records`（→`billboard_count=len(records)`，近 30 天上榜次数）+ `institution.net_amt`（→`inst_net`）。**不碰 seats**。
  - `score_dim7_institution`（`first_board_filter.py:1010`）：`dt.institution_net`。只用 records 存在性 + institution_net。**不直接用 seats**。
  - 但 `dragon_tiger_from_dict`（`data/mappers.py:628`）透传 `seats.buy/sell` 到 DragonTiger 模型，下游 `hot_money_seats.py:429` 的 seat 画像链靠席位 NAME（`OPERATEDEPT_NAME`）匹配（`profile_map.get(seat_name)`）——**这条链必须命名席位明细**。

### 2.3 维度对比

| 维度 | 东财 dragon_tiger_board | hithink special dragon-tiger | 能否替代 |
|---|---|---|---|
| per-stock 查询 | ✅ code 参数 | ❌ 仅 board-wide by date | ❌ |
| 多日 look-back records（上榜次数） | ✅ 30 天 records | ❌ 单日 + `range_days`（连榜天数≠上榜次数） | ❌ |
| 机构净额 | ✅ `institution.net_amt`（万元，latest 上榜日） | ⚠️ `org_net_value`（元，仅查询日，optional） | 语义近/口径+访问不同 |
| 命名席位明细（营业部全名 buy/sell） | ✅ `seats.buy/sell` | ❌ hot_money 给游资昵称非全名；org 给 count 不给名 | ❌ |
| 游资净额（stock 级） | ❌ 无 | ✅ `hot_money_net_value` | hithink 独有 |
| 连榜天数 | ❌ 无 | ✅ `range_days` | hithink 独有 |
| 概念 | ✅ `concept_blocks()` 另有 | ✅ `concept_list` | 东财已有 |
| 上榜原因 | ✅ `records.reason` | ✅ `limit_reason` | 两源都有 |

## 3. 最终决策：**(c) 不做**（2026-09-01，§2 调研后定）

- **(b) 硬排除**：hithink **无命名席位明细**。东财 seat 画像链（`hot_money_seats.py:428-445`）按营业部全名 `OPERATEDEPT_NAME` 匹配画像 key；hithink `hot_money_items` 给游资昵称（"宁波桑田路"），`board-type=org` 给席位计数不给名。两套命名对不上，无法喂 seat 画像。hithink 作东财席位断流备援**不成立**。
- **(c) 最可辩护（采纳）**：first_board_filter 消费者是 **per-stock + look-back-30** 口径（每候选股取近 30 天上榜次数 + 最近上榜日机构净）。hithink 是 **board-wide + single-date** 口径（按日取整张 51 股榜，无 code 过滤）。两字段需求：
  - `billboard_count`（上榜次数）：hithink 无对应，`range_days` 是连榜天数≠上榜次数；复刻需逐日扫整榜 ~30 次/股。
  - `inst_net`（机构净）：hithink `org_net_value` 语义最近，但 (i) 单位元≠万元（可 /10000 修），(ii) **仅查询日**——股不在查询日榜上就取不到，而东财取 latest 上榜日 ≤ trade_date（look-back 30）；复刻东财 look-back 行为需向后逐日扫整榜，最坏 ~30 次 board-wide 调用/候选股。候选股常 51+ 只 × 最坏 30 日 = **上千次整榜调用/评分轮，灾难性放大**。
  - 东财该链路已有 S131 `raise_on_failure=True` 诚实化（源断→标 missing 而非伪装"未上榜 ok"），单源充分。**强行接 hithink 是把 board-wide 源塞进 per-stock 管线 = 架构错配 + API 调用爆炸，YAGNI。**
- **(a) 仅作"未来独立 board-level 富集"可成立，但 NOT first_board_filter 输入**：hithink 真正独有的东财缺字段是 `hot_money_net_value`（stock 级游资净额）、`range_days`（连榜天数）、`hot_money_items`（命名游资→其买入股）。这些是 board-wide 游资/机构视角，适合做"整榜游资活跃度"看板，不是 per-stock 评分输入。且原 spec §1"概念维度东财缺"前提**已更正**（东财 `concept_blocks()` 已提供个股概念）。若未来要做 board-level 游资看板，**另开 spec**，不塞进 S107。

**结论**：对 first_board_filter 消费者，(c) 不做最可辩护（维度+访问口径双错配，东财单源 + S131 诚实化已足）；(b) 硬排除（无命名席位明细）；(a) 若做须重新定位为独立 board-level 游资追踪数据源，不接入 first_board_filter 的 per-stock 评分。

## 4. 受影响文件

无（不做）。相关代码定位见 §2.2（东财 dragon_tiger_board / first_board_filter / mappers / hot_money_seats / hithink_src 均不动）。

## 5. 不在本 spec 范围

- PE/PB 仲裁（S106 已做）
- 龙虎榜口径对齐的 cross_validate 仲裁（两维度不重叠，无法数值仲裁）
- 独立 board-level 游资追踪看板（若未来需要，另开 spec，用 hithink 独有的 hot_money_net_value/range_days/hot_money_items）
