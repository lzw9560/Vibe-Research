# 回测脚本

## 文件说明

### backtest_vol_ratio.py
量比/成交额过滤回测。从 gene_scores.db 取 qualify=1 的候选样本，用新浪财经 API 拉日K线，
计算 vol_ratio / amount_yi / 次日收益，分组对比胜率。

结论：不加过滤胜率最优（73%），量比 >= 1.5 和成交额 >= 10亿过滤均降低胜率。

### backtest_dragon_tiger.py
游资接力净流出过滤回测。在量比回测基础上，额外用东财 datacenter API 拉龙虎榜买卖席位明细，
计算游资净额，分组对比胜率。K线数据缓存到 /tmp/backtest_kline_cache.json 避免重复拉取。

结论：游资净流出组胜率最高（83.3%），不能作为负向过滤条件。

## 运行方式

```bash
cd backend
../.venv/bin/python3 ../scripts/backtest/backtest_vol_ratio.py
../.venv/bin/python3 ../scripts/backtest/backtest_dragon_tiger.py
```

需要网络访问（新浪财经 + 东财 datacenter），沙箱内需提权运行。

## 数据源

详见 docs/data-source-availability.md

## 扩展指南

新增回测脚本时：
1. 从 gene_scores.db 或 winrate.db 取样本
2. 用 astock 或直接 HTTP API 拉历史数据
3. 计算候选过滤指标 + 次日收益
4. 分组对比胜率/期望/盈亏比
5. 结论写入脚本头部注释 +本 README
