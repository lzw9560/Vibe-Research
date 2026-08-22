# Spec: S007 — 契约层（数据模型 + 回归基线 + 契约测试骨架）

> 状态：已实现 2026-08-01
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（本 spec 是其 §5 顺序第 1 步，CRITICAL 前置）、`../../ARCHITECTURE.md`、`../../CLAUDE.md` §1
> 后置依赖：`../S008`（后端数据层迁移，依赖本 spec 冻结的模型）、`../S009`（openapi-codegen，依赖路由挂 response_model 后）
> 编号说明：S006 为纲领；子 spec 自 S007 起。本 spec = 纲领 §5 第 1 步"契约层"。

---

## 1. 问题 / 目标

数据层双轨制：原始层（`astock`/`gstock`/`market`）返裸 dict + 魔法字符串，引擎层（`limitup_screener`/`limitup_sti`/`seat_engine`/`risk_models`）用 Pydantic，两轨字段名/单位/形状互不一致（涨跌幅 `change_pct` vs `pct`；市值 `mcap_yi`亿 vs `mcap`元；行情扁平 vs 嵌套）。`astock` 被 32 文件 import，契约不稳则全线回归。

**目标**：在**不动现有 astock 实现**的前提下，先建 `backend/models/` Pydantic v2 单一契约 + 回归基线录制夹具 + 前后端契约测试骨架，为 S008 数据层迁移提供可验证的目标契约。本 spec **只建契约与夹具，不迁移、不改 astock 返回值**。

## 2. 背景

- 当前同概念 4 套形状（来自调研）：
  - 涨跌幅：`tencent_quote`→`change_pct`；`market_turnover_rank`→`pct`
  - 总市值：`tencent_quote`→`mcap_yi`（亿元）；`market_turnover_rank`→`mcap`（元）
  - 流通市值：`tencent_quote`→`float_mcap_yi`（亿）；`market_turnover_rank`/`_emotion`→`float_cap`（元）
  - 行情形状：`tencent_quote` 扁平 dict；`us_hk_stock` 嵌套 `{quote:{...}, metrics:{...}}`
  - 估值形状：`full_valuation` 扁平；`valuation_percentile` 嵌套 `{metrics:{pe_ttm:{...}}}`
- `astock.py`(862) 被 32 文件 import；`data_provider/` 是未落地空壳残留。
- 前端手写 60 个 TS 接口无 codegen，漂移风险高。
- 合规边界（2026-07-29 调整）：允许教育研究性判断，但模型只承载客观数据，方向性判断走 AI 出口。

## 3. 需求清单

- [ ] R1 建 `backend/models/` 7 个 Pydantic v2 模型：`Quote`/`Valuation`/`Report`/`News`/`MarketSnapshot`/`FundFlow`/`KLine`
- [ ] R2 冻结字段名与单位约定（见 §5.1），文档化；新增字段须走 spec 变更
- [ ] R3 建 `backend/models/enums.py`：`Market`(A/US/HK/KR)、`ReportType`、`STIPhase` 等，收编 `enums.py`(13行)
- [ ] R4 建 `backend/models/normalize.py`：`normalize_stock_code`（收编 `data_provider/` 空壳）
- [ ] R5 建回归基线录制夹具 `backend/tests/contract/baseline/`：录 10 只代表 code（A股 6 + 港股 2 + 韩股 2）真实响应快照
- [ ] R6 建契约测试骨架 `backend/tests/contract/test_models.py`：模型 round-trip（dict→model→dict）+ 字段必填校验 + 基线回放比对
- [ ] R7 建前端 vitest 骨架（`frontend/src/test/` + `vitest.config.ts`），含 `client.ts` 契约测试占位
- [ ] R8 **不修改 `astock`/`gstock`/`market` 现有返回值**（迁移在 S008）；本 spec 只新增 models/ 与 tests/contract/

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/models/quote.py` | ➕新 `Quote` 模型 |
| ➕`backend/models/valuation.py` | ➕新 `Valuation` 模型 |
| ➕`backend/models/report.py` | ➕新 `Report` 模型 |
| ➕`backend/models/news.py` | ➕新 `News` 模型 |
| ➕`backend/models/market_snapshot.py` | ➕新 `MarketSnapshot`/`Emotion`/`Sector` 模型 |
| ➕`backend/models/fund_flow.py` | ➕新 `FundFlow` 模型 |
| ➕`backend/models/kline.py` | ➕新 `KLine`/`KLineBar` 模型 |
| ➕`backend/models/enums.py` | ➕新共享枚举（收编旧 `enums.py`，旧文件保留待 S008 删） |
| ➕`backend/models/normalize.py` | ➕新 `normalize_stock_code`（收编 `data_provider/`，旧目录保留待 S008 删） |
| ➕`backend/models/__init__.py` | ➕新，re-export 全部模型 |
| ➕`backend/tests/contract/__init__.py` | ➕新 |
| ➕`backend/tests/contract/baseline/*.json` | ➕新 10 只 code 响应快照 |
| ➕`backend/tests/contract/test_models.py` | ➕新契约测试 |
| `backend/conftest.py` | ✏️加 `market_data.db` 隔离 + 基线夹具 fixture |
| ➕`frontend/vitest.config.ts` | ➕新 |
| ➕`frontend/src/test/setup.ts` | ➕新 |
| ➕`frontend/src/test/client.test.ts` | ➕新占位 |
| `frontend/package.json` | ✏️加 vitest/@testing-library devDep |

## 5. 设计方案

### 5.1 字段与单位约定（冻结，待签字）

| 维度 | 约定 | 说明 |
|---|---|---|
| 价格 | `float`，单位**元** | 如 `price: 1680.50` |
| 涨跌幅 | `float`，单位**百分数** | 如 `change_pct: 2.34` 表示 +2.34%；统一字段名 `change_pct` |
| 总市值 | `float`，单位**元** | `market_cap`；派生只读属性 `market_cap_yi`（÷1e8）兼容展示 |
| 流通市值 | `float`，单位**元** | `float_market_cap`；派生 `float_market_cap_yi` |
| 日期/时间 | `str` ISO 8601 + 北京时区 | 如 `2026-07-29T15:05:00+08:00`；统一 `BEIJING_TZ` |
| 代码 | `str` | A 股 6 位；港股 5 位；美股 ticker；韩股 `XXXXXX.KS` |
| 缺失值 | `None` | 禁止用 `0`/`""` 占位，缺失即 `None`（对齐 S002 US6 数据缺失透明） |

**取舍**：市值统一"元"而非"亿"——绝对值无歧义，前端展示层做 `÷1e8` 派生。涨跌幅统一百分数（12.34）而非小数（0.1234），与前端展示口径一致、减少转换层。

### 5.2 模型骨架（草案，实现时按 astock 实际字段对齐）

```python
# models/quote.py
class Quote(BaseModel):
    code: str
    name: str | None = None
    market: Market
    price: float | None
    change_pct: float | None = None
    volume: int | None = None          # 手
    turnover: float | None = None      # 元
    market_cap: float | None = None    # 元
    float_market_cap: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    turnover_rate: float | None = None # 百分数
    limit_up_price: float | None = None
    limit_down_price: float | None = None
    updated_at: str | None = None      # ISO+08:00
    model_config = ConfigDict(frozen=True)
    @property
    def market_cap_yi(self) -> float | None: ...
```

其余 6 模型同理（字段集见 plan.md 细化）。**关键**：所有模型 `frozen=True`（不可变，对齐编码风格 §immutability）。

### 5.3 回归基线录制夹具

- 选 10 只代表 code：A股 `600519`(沪主)/`000858`(深主)/`300750`(创)/`688981`(科)/`000001`(指)/`399001`(指)；港股 `00700`；美股 `AAPL`；韩股 `005930.KS`
- 录制：跑一次真实取数（`tencent_quote`/`full_valuation`/`eastmoney_reports`/`stock_news`/`us_hk_stock`），把原始 dict 响应存为 `baseline/{code}_{endpoint}.json`
- 回放：契约测试 mock 网络层返回这些 JSON，比对"原始 dict → `Quote.model_validate(dict)` → `.model_dump()`"round-trip 字段值一致
- **合规**：基线快照只含客观数据，不含持仓/研报等私有数据；baseline 是公开行情，可进仓

### 5.4 不动现有实现

本 spec 严格只新增 `models/` + `tests/contract/`。`astock`/`gstock`/`market` 继续返 dict。迁移（astock 返模型、路由挂 response_model）在 S008。这样契约层可独立签字、独立验证、独立合并，不阻塞现有 :8900 服务。

## 6. 验收标准

- [ ] A1 `backend/models/` 7 模型 + enums + normalize 定义，`frozen=True`，字段按 §5.1 单位约定
- [ ] A2 `tests/contract/test_models.py` round-trip 测试过：基线 JSON → model → dump 字段值一致
- [ ] A3 模型缺失值用 `None`，必填字段（code/market/price）缺则校验失败
- [ ] A4 基线录 10 只代表 code 的 `tencent_quote`/`full_valuation`/`reports`/`news`/`us_hk_stock` 快照
- [ ] A5 `pytest -m "not live"` 全过（含新契约测试，用基线回放不联网）
- [ ] A6 前端 `npx vitest run` 骨架过（client 占位测试）
- [ ] A7 `astock`/`gstock`/`market` 返回值未变（现有 :8900 端点行为不变，回归零影响）
- [ ] A8 `data_provider/` 与旧 `enums.py` 未删（留给 S008 收编删除），但 `models/normalize`+`models/enums` 已提供等价能力

## 7. 合规自查（投研边界，逐条确认 — 按新 CLAUDE.md §1）

- [ ] 模型只承载客观数据（价格/估值/研报元数据/新闻），不含方向性判断字段
- [ ] 基线快照只含公开行情，无私有数据（持仓/研报/key 不入 baseline）
- [ ] 涨停四池聚合指标（如纳入 `MarketSnapshot.Emotion`）不含个股名字段（设计选择：Emotion 作聚合指标；弱合规下非红线，`lianban_stocks` 榜单另可如实呈现个股名）
- [ ] 模型字段命名客观，不出现"推荐/买入/卖出"等方向性词（方向判断走 AI 出口）
- [ ] 私有数据仍只存 `~/.vibe-research/`，baseline 不含
- [ ] 不涉及东财端点新增（本 spec 不改 em_get 调用）

## 8. 测试计划

- 单测：`tests/contract/test_models.py`——round-trip + 必填校验 + 缺失值 + frozen 不可变
- 基线回放：mock 网络返 baseline JSON，验证模型 parse 一致（不联网，标 `not live`）
- 录制（一次性，手动）：跑真实取数生成 baseline，人工核对字段映射正确
- 前端：`vitest` 骨架 + client 占位
- 回归：`:8900` 现有端点行为不变（A7）

## 9. 风险与回滚

- 🟡 字段映射不全：astock 实际字段多于调研所见，实现时可能漏字段——缓解：基线录制时逐字段比对，漏的补到 model（可选字段 `None` 默认）
- 🟡 单位约定签字风险：市值"元"vs"亿"若签字时被否决，模型派生属性调整即可，不影响契约结构
- 🟢 回滚：本 spec 只新增不改动，回滚 = 删 `models/` + `tests/contract/`，对现有系统零影响
- 🟢 不阻塞：astock 返 dict 不变，:8900 服务持续可运行
