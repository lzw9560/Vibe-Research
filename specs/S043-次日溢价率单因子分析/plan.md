# 技术方案 · S043 次日溢价率单因子分位分析

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 依赖：S040 回填 90 天数据。

## 1. 文件结构与职责

### 改动
| 文件 | 改动 |
|---|---|
| `backend/backtest_lite.py` | 泛化分位函数 + scatter 加因子字段 + BacktestResult 新增字段 |
| `backend/routers/backtest.py` | 新增 `GET /api/backtest/factor-analysis` 端点 |
| `frontend/src/pages/Backtest.tsx` | 新增"因子分位" Tab |

### 不新增文件
复用现有 backtest_lite + backtest router，最小改动。

## 2. 泛化分位函数

### 2.1 现有函数
```python
def _calc_percentile_analysis(scatter: list[dict]) -> dict[str, Any]:
    # 硬编码按 gene_score 三档分桶
```

### 2.2 泛化版
```python
def _calc_factor_percentile_analysis(
    scatter: list[dict],
    factor_key: str = "gene_score",
    buckets: list[tuple[str, float, float]] | None = None,
) -> dict[str, Any]:
    """按指定因子分桶分析。buckets = [(label, low, high), ...]，None 用默认。"""
    if buckets is None:
        buckets = [("0-60", 0, 60), ("60-75", 60, 75), ("75-100", 75, 100)]
    # ... 通用分桶逻辑
```

现有 `_calc_percentile_analysis` 改为：
```python
def _calc_percentile_analysis(scatter):
    return _calc_factor_percentile_analysis(scatter, "gene_score")
```

### 2.3 premium_rate 默认桶
```python
_PREMIUM_BUCKETS = [
    ("0-30", 0, 30),
    ("30-50", 30, 50),
    ("50-70", 50, 70),
    ("70-100", 70, 100),
]
```

## 3. scatter 加因子字段

`generate_scatter_data` 的 point 新增：
```python
points.append({
    ...,
    "factor_premium_rate": g.factors.get("次日溢价率", 0),
})
```

## 4. BacktestResult 扩展

```python
@dataclass
class BacktestResult:
    ...
    factor_percentile_analysis: dict[str, Any] | None = None  # 新增可选字段
```

`run_backtest_async` 内调 `_calc_factor_percentile_analysis(scatter, "factor_premium_rate", _PREMIUM_BUCKETS)` 填入。

## 5. API 端点

```python
@router.get("/api/backtest/factor-analysis")
async def factor_analysis(
    start: str = Query(...),
    end: str = Query(...),
    factor: str = Query("premium_rate"),
):
    scatter = await generate_scatter_data((start, end))
    factor_key = {"premium_rate": "factor_premium_rate"}.get(factor, "factor_premium_rate")
    result = _calc_factor_percentile_analysis(scatter, factor_key, _PREMIUM_BUCKETS)
    return {"data": result}
```

## 6. 前端

`Backtest.tsx` 新增 Tab "因子分位"：
- 一个下拉选因子（当前只有 premium_rate，预留扩展）
- 一个表格展示四档 count / avg_return / hit_rate
- 不需要折线图——表格够直观
