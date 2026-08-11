# S062 任务拆分（原子任务 + 依赖 + 验收）

> develop 直提；small-medium。依赖 S058 卡片层落地（cards/ 目录 + 模板约定）。

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| T1 | STRATEGY_REGISTRY `reverse_package` 参数精化：entry_condition = T-2/T-3 涨停 + T-1 断板调整 + T-1 成交额>15 亿 + 均线多头（M7/M14>1.0）+ 实体>-3%；max_hold_days=1（严格 T+1 纪律）；止损跌破前日最低价 | — | 注册表 diff 测试 |
| T2 | `cards/reverse_package.md` 撰写：完整逻辑 + 执行规则（次日竞价/开盘买入，T+1 分时+板块强度+大盘情绪综合卖出）+ 来源标注（quantjuzi/fanbao_strategy：回测 2026.04-06 胜率 50.9%/均笔 +1.07%，实盘 2025.10 起 357 笔 47.62%）+ 样本时效声明 | S058 R2.1 | 卡片存在 + 来源字段断言 |
| T3 | STRATEGY_REGISTRY 新增 `dragon_head` 战法条目（区别于现有 low_absorption 低吸龙头：此为强势识别/追踪型）：板块领涨地位 + 相对强度跑赢板块 2% + 换手>5% + 量比>1.5 + 板块级催化确认；weather_regimes=[晴天,阴天] | — | 注册表测试 |
| T4 | `cards/dragon_head.md` 撰写（内容源：DSA dragon_head.yaml 评估标准 + 上述口径，工具名映射 VR 工具） | S058 R2.1 / T3 | 同上 |
| T5 | 合规核查：两卡无行动指令措辞、尾挂风险提醒、来源+样本区间+「历史统计不保证未来」齐全；样本>1 年触发复核标记逻辑 | T2/T4 | checklist 过 + 测试 |
| T6 | S053 联动记录：反包卡参数与「60 日无信号查因」对照（新参数是否改变信号频率），结论记 commit message | T1 | 记录 |

## 执行序

T1 → T2；T3 → T4（两线并行）→ T5 → T6。前置：S058 R2.1 模板约定就绪。
