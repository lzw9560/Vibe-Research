# 龙头大跌反包（leader_drop_reversal）

## 适用天气
极端反弹（龙头大跌触发量化止损后筹码真空，情绪修复反包）

## 核心逻辑
龙头股 T-1 日大跌≥7%（触发量化止损割肉，筹码真空）后，T 日低开反包吞没前日阴线且爆量。本质是止损盘出清后的情绪修复反包，区别 reverse_package（炸板后反包 open_count≥2）与 pattern_reversal（长上影后反包）。

## 入场条件
- 龙头确认：high_gene=1 或 sector_rank≤3
- T-1 大跌：日内跌幅≥7%（close 相对 open，不依赖 pctChg）
- T 吞没：T 日 close≥T-1 open 且 T 日 open≤T-1 close（低开反包吞没阴线）
- 放量：T 日量比≥1.2x（T/T-1 volume）

## 退出参数
- 止损：跌破入场价 -3%
- 止盈：涨至 +6%（入场价基准）触发减仓锁利
- 最大持有：1 日（T+1 严格卖出）

## 风险点
- 反包失败即大面，严格 T+1 纪律
- 大跌从 close/open 复算（不依赖 pctChg，R14 注入前可用）
- bars 由 _build_limitup_msc 从 baostock cache 取尾部 2 根（T-1+T）
- edge_type=event（待验，§44v2 须 R11 event_drift 修正才 verdict 可靠）

## 历史统计特征，市场有风险，研究参考。
