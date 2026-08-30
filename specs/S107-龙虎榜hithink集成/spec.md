# Spec: S107 — 龙虎榜 hithink 集成（维度对齐设计）

> 状态：占位草案（S106 §11 承诺另立，待启动时补全）
> 作者：lzw9560  日期：2026-08-30
> 级别：待定（需先做 schema 对齐调研）
> 关联：S106（§11 范围外处置，龙虎榜维度不同另立）/ S104（hithink_src 已建）

## 1. 问题 / 目标

S106 评估龙虎榜 hithink 集成时发现**维度不同**，不能简单当 fallback：
- **hithink `special dragon-tiger`**：返 `{stock_items:[{thscode, name, concept_list, ...}]}`——**个股 + 概念维度**（51 股 / 57 席位实测）
- **东财 `dragon_tiger_board`**：返 `{records:[], seats:{buy,sell}, institution:{net_amt}}`——**席位买卖明细 + 机构净额维度**

两源字段**完全不重叠**——不是"同一数据两套口径"，是**两个不同维度的数据**。直接当 fallback 不成立。

## 2. 待调研（启动前必做）

- [ ] hithink dragon-tiger 返回的 `stock_items` 完整字段结构（实测只看了首层 thscode/concept_list）
- [ ] hithink 是否有「席位买卖明细」对应端点（special dragon-tiger 的 board_type=org/hot_money 子项）
- [ ] 东财 dragon_tiger_board 断流时（审查 H4：push2his 断→records 空→维度 2 降级 50），hithink 能补什么
- [ ] seat_engine / first_board_filter 消费的是「席位明细」还是「个股上榜」——决定 hithink 能否补

## 3. 候选方向（待定）

- **(a) hithink 补「个股上榜」维度**：东财返席位明细，hithink 返个股+概念，两维度并存不替代。新增 hithink 个股上榜端点，不动东财席位链路。
- **(b) hithink 作东财席位断流时的备援**：需先调研 hithink 是否有席位级数据（board_type 子项），否则维度对不上不能备援。
- **(c) 不做**：东财席位链路是 seat_engine 命脉，hithink 维度不同强行接会污染。保持东财单源，断流诚实降级。

**倾向 (a)**——hithink 补的是东财没有的「个股+概念」维度，不是替代席位。但要等 §2 调研确认 hithink 端点能力。

## 4. 受影响文件

待调研后定。

## 5. 不在本 spec 范围

- PE/PB 仲裁（S106 已做）
- 龙虎榜口径对齐的 cross_validate 仲裁（两维度不重叠，无法数值仲裁）
