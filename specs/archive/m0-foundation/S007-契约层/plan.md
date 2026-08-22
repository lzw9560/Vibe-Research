# Plan: S007 — 契约层技术方案

> 对应 `spec.md`。本 plan 细化模型字段、基线录制、契约测试、前端骨架的实现路径。

## 1. 模型字段定义（7 模型，基于 astock 调研 + 合理推断，实现时逐字段对齐基线）

### 1.1 `models/quote.py` — `Quote`
```python
class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    market: Market
    name: str | None = None
    price: float | None
    change_pct: float | None = None        # 百分数 2.34 = +2.34%
    change_amount: float | None = None      # 元
    volume: int | None = None               # 手
    turnover: float | None = None          # 元
    market_cap: float | None = None         # 元
    float_market_cap: float | None = None   # 元
    pe_ttm: float | None = None
    pb: float | None = None
    turnover_rate: float | None = None      # 百分数
    amplitude: float | None = None         # 百分数
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    updated_at: str | None = None           # ISO+08:00

    @property
    def market_cap_yi(self) -> float | None:
        return None if self.market_cap is None else self.market_cap / 1e8
```

### 1.2 其余 6 模型（字段集，实现时对齐）
- `Valuation`: code, market, pe_ttm, pb, ps_ttm, dividend_yield, peg, pe_digestion_years, forward_pe, consensus_eps, percentile, updated_at
- `Report`: code, market, title, institution, rating, rating_target_price, publish_date, source
- `News`: code, market, title, source, published_at, url, summary
- `MarketSnapshot`: date, index_code, index_name, close, change_pct, volume, turnover; 嵌套 `Emotion`（连板梯队/封板率/炸板率/晋级率/涨停家数，**不含个股名**——设计选择，Emotion 作聚合指标；弱合规下非红线）+ `Sector[]`
- `FundFlow`: code, market, main_net, main_net_5d, north_net, super_large_net, large_net, medium_net, small_net, date
- `KLine`: code, market, bars: list[KLineBar]；`KLineBar`: date, open, close, high, low, volume, turnover, amplitude

### 1.3 `models/enums.py`
```python
class Market(str, Enum): A = "A"; US = "US"; HK = "HK"; KR = "KR"
class ReportType(str, Enum): ...  # 客观评级枚举
class STIPhase(str, Enum): HIGH = "高潮"; START = "启动"; DIVERGE = "分歧"; LOW = "冰点"; EBB = "退潮"
```

### 1.4 `models/normalize.py`
`normalize_stock_code(code) -> (code, Market)`：A 股 6 位、港股 5 位、美股 ticker、韩股 `.KS` 后缀剥离。收编 `data_provider/`。

## 2. 基线录制夹具

- 10 只 code：`600519`/`000858`/`300750`/`688981`/`000001`/`399001`/`600036`/`00700`/`AAPL`/`005930.KS`
- 录制脚本 `tests/contract/record_baseline.py`（标 `live`，手动跑）：调 `astock.tencent_quote`/`full_valuation`/`eastmoney_reports`/`stock_news`/`gstock.us_hk_stock`，存 `baseline/{code}_{endpoint}.json`
- **合规**：只录公开行情；无私有数据

## 3. 契约测试结构

`tests/contract/test_models.py`（`not live`）：
- round-trip：读 baseline JSON → `Model.model_validate(dict)` → `.model_dump()` → 比对关键字段
- 必填校验：`code`/`market`/`price` 缺则 `ValidationError`
- 缺失值：可选字段缺为 `None`，非 0/"" 
- frozen：`model_copy(update=...)` 抛错（不可变）

## 4. 前端 vitest 骨架

- `vitest.config.ts`：environment jsdom，`setup.ts` 导入 @testing-library/jest-dom
- `src/test/client.test.ts` 占位（真实契约在 S013）
- `package.json` devDep：vitest + @testing-library/react + jsdom

## 5. 实现步骤
1. 建 `models/{enums,normalize}.py`（收编旧）
2. 建 7 模型（按 §1 字段，对齐基线时补漏字段为 Optional）
3. 跑一次 `record_baseline.py` 录 10 code 快照（手动 live）
4. 建 `tests/contract/test_models.py` round-trip
5. 建前端 vitest 骨架
6. `pytest -m "not live"` + `npx vitest run` 全过

## 6. 风险点
- astock 实际字段多于调研 → 基线录制时逐字段比对，漏的补 Optional
- 市值单位"元"签字 → 派生 `_yi` 属性兼容展示，结构不变
- frozen 模型与 Pydantic v2 兼容 → 用 `model_config = ConfigDict(frozen=True)`（v2 支持）
