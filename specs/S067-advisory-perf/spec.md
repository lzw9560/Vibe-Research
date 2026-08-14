# S067 - advisory 端点性能优化

> 级别:**large**(涉及交易信号/财务验算,AGENTS.md 分级表自动 large)
> 状态:spec 草案(待 grill + 实施)
> 创建:2026-08-14
> 前置:advisory 死锁 bug 已在本会话修复(anyio.to_thread offload + winrate 5min 缓存 + kline 1h 缓存),advisory 不再拖垮 health。本 spec 处理**剩余的端点本身架构性慢**(>40s 首次 / 15s 二次)。

## 1. 问题陈述

`/api/advisory/summary` 端点响应过慢:
- 首冷请求 **>40s**(curl 40s 超时不返回)
- 二次请求 **~15s**(部分缓存命中但仍慢)
- 端点实际不可用(>40s 超时)

死锁已消除(并发 health 不受影响,to_thread offload 生效),但 advisory 端点本身的累计耗时使其不可用。

## 2. 根因链(基于 explorer 深度 recon)

### 调用链
```
advisory_summary_endpoint(routers/advisory.py:16)
└── advisory_summary(position_advisor_v2.py:495)  # 三场景串行
    ├── to_thread(advise_recommendations, limit)
    │   └── _latest_gene_map()           # DB 读今日 gene_scores
    │   └── _win_rate_map()              # 缓存 miss → run_strategy_backtest(90)
    │   └── for g in genes[:limit]: _lookup_strategy → match_strategies
    ├── to_thread(advise_watchlist)
    │   └── _latest_gene_map() / _win_rate_map()(5min 缓存大概率命中)
    │   └── for code in codes: _lookup_strategy
    └── advise_holdings()
        ├── await pf.get_portfolio()      # tencent_quote 批量网络(无缓存)
        └── to_thread(_advise_holdings_body, pf_data)
            ├── _kline_cache.clear()       # ⚠️ 自毁解析缓存
            ├── _latest_gene_map() / _win_rate_map()
            └── for h in holdings:
                ├── _lookup_holding_strategy  # layer2 逐持仓 N+1 DB
                └── _atr_trailing_stop → astock.kline  # mootdx 网络(_KLINE_CACHE 1h,独立)
```

### 慢点全量标注

| # | 函数 | 类型 | 耗时 | 缓存现状 | 可优化 |
|---|------|------|------|----------|--------|
| A | `run_strategy_backtest(90)` | 回测+网络 | ~6s 首冷/0s 热 | 12h 全局缓存 | 预热 |
| B | `astock.kline` (mootdx) | 网络 | 1-3s/次 | 1h TTL(独立 _KLINE_CACHE) | 并发 gather |
| C | `astock.tencent_quote` (urllib) | 网络 | ~0.33s/次 | **无缓存** | 日内缓存 |
| D | `_lookup_holding_strategy` layer2 | DB N+1 | 小但累加 | 无 | 批量 IN |
| E | 三场景串行执行 | 架构 | 累加 | — | asyncio.gather |
| F | `_kline_cache.clear()` | 自毁 | 强制重解析 | — | 移除/条件清 |

### 累计路径(>40s)
1. `_win_rate_map` miss → `run_strategy_backtest(90)` 冷启动 ~6s(回测内逐日逐股拉 kline,虽有 kline_cache 复用,首冷仍 10-30s)
2. `advise_holdings` 内 `_kline_cache.clear()` → 强制重新解析(虽 _KLINE_CACHE 命中免网络,但解析 + _atr_trailing_stop 循环仍累加)
3. `get_portfolio()` tencent_quote 无缓存,每次走网络
4. 三场景串行:recommendations + watchlist + holdings 顺序执行

## 3. 优化方案(优先级排序)

### P0(low risk,立即做)
**P0-1 回测预热**
- FastAPI startup event 预跑 `run_strategy_backtest(90)`,结果写 12h 全局缓存
- 风险:低(后台预热,失败不影响服务)
- 预期:首冷 6s → 0s
- 合规:不涉及交易信号变更,只优化缓存

**P0-2 tencent_quote 日内缓存**
- 模块级 `dict[codes_tuple, (result, ts)]`,TTL=3600s(参考 kline 缓存)
- 风险:低(行情日内变化小,只读)
- 预期:get_portfolio 网络耗时 → 0s
- 合规:只读行情,不涉及交易信号

### P1(medium risk,短期)
**P1-1 kline 并发 gather**
- _advise_holdings_body 内 `for h in holdings` 的 kline 串行改 `concurrent.futures.ThreadPoolExecutor`(max_workers=5 限流,避免 mootdx 并发压力)
- 风险:中(mootdx 并发承载需评估)
- 预期:串行 → 并发,-3~5s
- 合规:无

**P1-2 移除 `_kline_cache.clear()`**
- _advise_holdings_body 内移除,或改按时间戳条件清理(日内有效)
- 风险:低(kline 日内有效)
- 预期:消除 holdings 场景重复解析
- 合规:无

### P2(low risk,并行化)
**P2-1 三场景 asyncio.gather**
- advisory_summary 内 recommendations/watchlist/holdings 并行
- 风险:低(CPU-bound 已在 thread pool)
- 预期:串行累加 → 并行,-2s
- 合规:无

**P2-2 批量 sqlite3(layer2 IN 查询)**
- `_lookup_holding_strategy` layer2 改批量 IN 查询所有持仓 code
- 风险:低
- 预期:N+1 → 1 次查询
- 合规:无

### P3(兜底)
**P3 端点超时 + 降级**
- 端点加 timeout=15s,超时返回已计算部分 + `partial=true` + disclaimer
- 风险:中(需前端兼容 partial 字段)
- 合规:降级时不返回误导性交易信号,保留 disclaimer

## 4. 分级流程门(AGENTS.md large)

| 门 | 要求 |
|---|---|
| spec.md | ✅ 本文件 |
| plan/tasks | 必写(可并入 spec 一节) |
| feature 分支 | `feature/S067-advisory-perf`,off develop |
| code review / grill | 完整 grill(涉及交易信号/财务数据) |
| review 轮数 | 单轮,HIGH 阻断,MEDIUM 进 backlog |
| playwright 验收 | playwright-pro 完整 |
| 归档 | 批量归档,一 spec 一 commit(`feat(S067): ...`) |

## 5. 合规自查(CLAUDE.md §1 + AGENTS.md)

涉及交易信号/财务数据,过弱合规:
1. **建议口径**:保持「历史统计特征,不构成投资建议」disclaimer 不变
2. **win_rate_source**:缓存不改变来源标注(backtest_90d / synthetic / none)
3. **交易信号**:优化后 action(enter/add/reduce/close/hold)逻辑不变,仅加速
4. **数据准确性**:tencent_quote/kline 缓存为只读行情,不影响计算正确性
5. **不臆造数据**:缓存命中返回历史回测/行情真实结果,不伪造

## 6. 预期优化后耗时

| 场景 | 当前 | 优化后 |
|------|------|--------|
| 首冷 | >40s | ~8-12s(回测预热+缓存+tencent缓存) |
| 二次 | ~15s | ~3-5s(kline 复用+tencent 缓存+并行) |
| 理想热缓存 | — | ~1-2s(全缓存命中+并行) |

## 7. 实施建议

- **Phase 1**(P0,低风险,先做):tencent_quote 缓存 + 回测预热 → advisory 首冷大幅降
- **Phase 2**(P1+P2,中风险):kline 并发 + 移除 clear + 三场景 gather + 批量 DB → 二次降到 3-5s
- **Phase 3**(P3,兜底):端点超时+降级 → 保证可用性

每个 Phase 可独立合并,P0 优先(收益大风险低)。

## 8. 依赖

- 无前置 spec 依赖(死锁修复已在 develop)
- mootdx 并发承载需 P1-1 前评估(可能需限流参数调优)

## 9. 风险

- mootdx 并发压力(P1-1):可能触发限流/超时,需 max_workers 限流 + 回退串行
- 缓存时效:tencent_quote 行情日内缓存,盘后数据更新后需失效(可用短 TTL 或收盘清)
- 交易信号合规:所有优化不得改变 action 计算逻辑,仅加速
