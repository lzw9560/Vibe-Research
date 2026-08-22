# 技术方案 · S042 统一持仓建议引擎

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 依赖：S040 回填 90 天数据（回测胜率 sample_size 足够）。

## 1. 文件结构与职责

### 新增
| 文件 | 职责 |
|---|---|
| `backend/strategies/position_advisor_v2.py` | 统一建议引擎，三场景入口 |
| `backend/routers/advisory.py` | API 端点 |
| `frontend/src/pages/Advisory.tsx` | 前端建议中心 |
| `frontend/src/lib/api.ts`（扩展） | 新增 advisorySummary 调用 |

### 不改
| 文件 | 说明 |
|---|---|
| `backend/strategies/position_advisor.py` | v1 保持不动，推荐链路不受影响 |

## 2. 建议引擎设计

### 2.1 类结构
```python
class PositionAdvisorV2:
    def __init__(self, lookback_days: int = 90):
        self._lookback = lookback_days
        self._strategy_results: list[StrategyBacktestResult] | None = None  # 惰性加载

    @property
    def strategy_results(self):
        if self._strategy_results is None:
            self._strategy_results = run_strategy_backtest(self._lookback)
        return self._strategy_results

    def advise_recommendations(self, limit=20) -> list[dict]:
        ...

    def advise_watchlist(self) -> list[dict]:
        ...

    def advise_holdings(self) -> list[dict]:
        ...

    def summary(self, limit=20) -> dict:
        return {
            "recommendations": self.advise_recommendations(limit),
            "watchlist": self.advise_watchlist(),
            "holdings": self.advise_holdings(),
        }
```

### 2.2 战法 win_rate 查询
```python
def _get_win_rate(self, strategy_code: str) -> tuple[float, str]:
    """返回 (win_rate, source)。有回测数据 -> (0.62, 'backtest_90d')；无 -> (合成值, 'synthetic')。"""
    for r in self.strategy_results:
        if r.strategy_code == strategy_code:
            return r.win_rate, "backtest_90d"
    return synthetic_win_rate, "synthetic"
```

### 2.3 推荐标的建议（R2）
```python
def advise_recommendations(self, limit=20):
    recs = await get_today_recommendations(limit)
    suggestions = []
    for rec in recs:
        gene = _get_gene_for_code(rec.code)
        strategy_code = _match_strategy(gene)
        win_rate, source = self._get_win_rate(strategy_code)
        # 复用 position_advisor v1 的仓位/止损/止盈逻辑
        suggestion = PositionAdvisor().advise(signal)  # v1 算仓位
        suggestion.win_rate = win_rate
        suggestion.win_rate_source = source
        suggestions.append(suggestion.to_dict())
    return suggestions
```

### 2.4 持仓建议规则（R4）
见 spec D2 表。核心逻辑：
```python
def advise_holdings(self):
    portfolio = await get_portfolio()
    suggestions = []
    for h in portfolio["holdings"]:
        gene = _get_gene_for_code(h["code"])
        if gene is None:
            suggestions.append({"code": h["code"], "status": "no_signal", ...})
            continue
        strategy_code = _match_strategy(gene)
        win_rate, source = self._get_win_rate(strategy_code)
        pnl_pct = h["pnl_pct"]
        action = self._decide_action(pnl_pct, win_rate, h["cost"])
        suggestions.append({
            "code": h["code"], "action": action,
            "win_rate": win_rate, "win_rate_source": source,
            "pnl_pct": pnl_pct, "reasons": [...],
        })
    return suggestions

def _decide_action(self, pnl_pct, win_rate, cost):
    stop_loss_price = cost * 0.97  # 默认 -3%
    if pnl_pct < -3:
        return "close"
    if pnl_pct > 5 and win_rate >= 0.6:
        return "hold"
    if pnl_pct > 5 and win_rate < 0.4:
        return "reduce"
    if pnl_pct < -3 and win_rate >= 0.5:
        return "hold"
    if win_rate < 0.4:
        return "reduce"
    return "hold"
```

### 2.5 自选股建议（R3）
```python
def advise_watchlist(self):
    codes = watchlist_get()["codes"]
    suggestions = []
    for code in codes:
        gene = _get_gene_for_code(code)
        if gene is None:
            suggestions.append({"code": code, "status": "no_signal"})
            continue
        strategy_code = _match_strategy(gene)
        win_rate, source = self._get_win_rate(strategy_code)
        suggestion = PositionAdvisor().advise(signal)
        suggestions.append(suggestion.to_dict() | {"win_rate": win_rate, "win_rate_source": source})
    return suggestions
```

## 3. API 端点

```python
# routers/advisory.py
@router.get("/api/advisory/summary")
async def advisory_summary(limit: int = Query(20, ge=1, le=50)):
    advisor = PositionAdvisorV2()
    return {"data": advisor.summary(limit)}
```

## 4. 前端

`Advisory.tsx` 三个分区：
1. 推荐标的建议（表格：code / name / win_rate / 仓位 / 止损 / 止盈 / win_rate_source / 理由）
2. 自选股建议（同上 + no_signal 行）
3. 持仓建议（表格：code / name / action / win_rate / pnl_pct / win_rate_source / 理由）

每条建议底部挂"历史统计特征，市场有风险，不构成投资建议"。
