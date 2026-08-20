# 技术方案 · S088 盘前暴风雨预测模型

> 对应 spec.md（grill 锁定 11 需求 + 第一档因子）

## 0. 复用清单

| 需求 | 复用现有能力 |
|---|---|
| R2 外围隔夜 | `market.get_global_indices`（美股三大/A50/港股/大宗） |
| R3 内部先行 | `limitup_screener.data.load_gene_scores`（T-1 gene）+ `limitup_sti.data.get_db`（sti_timeline max_boards/break_rate） |
| R5 新闻密度 | `newsradar.get_radar`（12 赛道 RSS + 利空关键词） |
| R4 估值水位 | 数据源待定——先跳过（权重临时分给外围+内部+新闻），不臆造 |

## 1. 分阶段

- **A 模型** `storm_predictor.py`：因子采集（外围/内部/新闻）+ 加权 + 概率分 + 仓位映射
- **B 端点** `GET /api/sentiment/storm-predict?date=` 返概率分+因子明细+仓位
- **C 前端** ContextTab 接入暴风雨概率分+仓位+因子明细
- **D 测试** 单测（mock 因子）+ 0819 回测验证 + 既有 STI 0 回归

## 2. 因子加权（spec §5.1）

概率分 = 外围隔夜×0.40 + 内部先行×0.40 + 新闻密度×0.20（估值 R4 先跳过，权重重分配）
