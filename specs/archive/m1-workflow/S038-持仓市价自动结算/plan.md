# 技术方案 · S038 持仓市价自动结算

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 级别：large，feature/S038-auto-settlement 分支。依赖 S037 先合并。

## 1. 文件结构与职责

### 新增
| 文件 | 职责 |
|---|---|
| `backend/market_price.py` | `fetch_current_price(code) -> float | None` |

### 改动
| 文件 | 改动 |
|---|---|
| `backend/routers/workflow.py` | `_settle_on_transition` 加拉价逻辑 + `exit_price_source` |
| `frontend/src/components/workflow/WorkflowStateCard.tsx` | 市价结算选项 + 预填 exit_price |

## 2. fetch_current_price 设计

```python
# backend/market_price.py
import astock
from data.mappers import quote_from_tencent

def fetch_current_price(code: str) -> float | None:
    """调 tencent_quote 拉当前价。失败返 None。"""
    try:
        raw = astock.tencent_quote([code]) or {}
        model = quote_from_tencent(code, raw.get(code, {}))
        return model.price or None
    except Exception:
        return None
```

## 3. _settle_on_transition 改动

```python
# routers/workflow.py _settle_on_transition 内
if state == "settled":
    # 用户手填优先
    if exit_price is not None:
        source = "manual"
    else:
        # 尝试自动拉价
        market_price = fetch_current_price(code)
        if market_price is not None:
            exit_price = market_price
            source = "market"
        else:
            # fallback: S034 既有缺价跳过
            return {"recorded": False, "reason": "行情获取失败，请手动填写卖出价", "exit_price_source": None}
    # 走 S034 正常结算链路
    result = record_settlement(code, date, entry_price, exit_price, ...)
    result["exit_price_source"] = source
    return result
```

## 4. 前端 WorkflowStateCard

settled 流转前，如果 exit_price 为空：
- 显示 toggle "按市价自动结算"
- toggle on -> 传 `auto_fill_exit_price: true` 到 transition 请求体
- 后端拉到价 -> 响应含 exit_price + exit_price_source -> 前端预填输入框（用户可改）

## 5. transition 请求体扩展

```json
{
  "code": "600519",
  "date": "2026-08-08",
  "state": "settled",
  "entry_price": 100.0,
  "exit_price": null,              // null = 请求自动拉价
  "auto_fill_exit_price": true     // flag: 后端拉价
}
```

`auto_fill_exit_price` 为 false 或不传 -> 保持 S034 原行为（exit_price 必填，缺则跳过）。
