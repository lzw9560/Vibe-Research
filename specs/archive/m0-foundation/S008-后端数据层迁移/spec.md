# Spec: S008 — 后端数据层迁移（astock/gstock/market → 模型）

> 状态：已实现 2026-07-31（T13 全批次 + T16 + T17 :8900 live 冒烟通过，765 passed；见 `验收报告.md`）
> 作者：Claude  日期：2026-07-29；续推 2026-07-30~07-31
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 2 步）、`../S007-契约层/spec.md`（前置，依赖冻结模型）、`../S009`（codegen，本 spec 完成路由挂 response_model 后才跑）、`../../ARCHITECTURE.md`

---

## 1. 问题 / 目标

`astock.py`(862) 被 32 文件 import，返裸 dict + 魔法字符串；同概念 4 套形状（`change_pct`/`pct`、`mcap_yi`亿/`mcap`元）。多个静默 bug 被 try/except 掩盖：`risk_models` 调 `astock.get_kline`（实际 `kline`）→ 波动率/回撤/流动性恒 0.0；`limitup_screener/data.py` 缺 `datetime` import；`chat.SYSTEM_PROMPT_NO_TOOLS` 重复定义两遍；`limitup_screener/models.py` 模型层反向 `import astock`；`seat_engine/models.py` 可变默认值（`set` 类变量共享）。

**目标**：astock/gstock/market 迁移到返回 S007 冻结的 Pydantic 模型；路由挂 `response_model`；修上述全部 bug；删 `data_provider/` 空壳与旧 `enums.py`；迁移层按消费者分组、有退出条件。

## 2. 背景

- S007 已建 `backend/models/` 7 模型 + 回归基线 + 契约测试；本 spec 用之。
- 32 依赖者：routers/stock_data、stock_financial、limitup/metrics、chat、gstock、market、risk_models、portfolio、daily_review、bidding_monitor、auction_screener、backtest_lite、limitup_strategy、limitup_screener/models、seat_engine/service、candidate_funnel/sources×6、value_funnel/*。
- `em_get` 限流/熔断/代理探测三合一耦合在单函数；4+ 套缓存并存。

## 3. 需求清单

- [ ] R1 astock 各数据函数返回 S007 模型（Quote/Valuation/Report/News/FundFlow/KLine）；保留 `to_dict()` 适配层供未迁移消费者过渡
- [ ] R2 gstock.us_hk_stock 返回统一 `Quote`（嵌套→扁平）；push2→push2delay 降级保留
- [ ] R3 market._emotion/_sentiment/_sectors 返回类型化模型；TTL 缓存迁 `infra/cache.py`
- [ ] R4 routers 挂 `response_model`（stock_data/stock_financial/limitup/market 等）
- [ ] R5 🩹修 `risk_models` 的 `get_kline`→`kline`（波动率/回撤/流动性不再恒 0.0），补单测锁住
- [ ] R6 🩹修 `limitup_screener/data.py` 缺 `datetime` import
- [ ] R7 🩹删 `chat.SYSTEM_PROMPT_NO_TOOLS` 重复定义（第一份死代码）
- [ ] R8 `limitup_screener/models.py` 移除 `import astock`（模型不依赖数据源），`_numf` 内联或迁 utils
- [ ] R9 🩹修 `seat_engine/models.py` 可变默认值（`Field(default_factory=set)`）
- [ ] R10 `em_get` 限流/熔断/代理探测拆到 `backend/data/transport.py`；astock 拆 `data/sources/{tencent,eastmoney,akshare,mootdx,sina}.py`
- [ ] R11 删 `backend/data_provider/` 与旧 `backend/enums.py`（功能已由 S007 models/normalize/enums 提供）
- [ ] R12 迁移层按消费者分组（A=routers/B=chat/C=engines），每组迁完即删该组适配 shape 转换，有退出条件
- [ ] R13 统一复权口径：`kline_resolver` 加 `adjust` 契约 + `_SOURCE_ADJUST` 源口径声明表；消费者传 `adjust="qfq"` 时只走原生前复权源（百度/akshare），不回退 raw 源（新浪/mootdx），无 qfq 源诚实返空（不臆造复权因子重算）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/astock.py` | 🔥拆为 `data/sources/*` + 返模型 |
| `backend/gstock.py`/`market.py` | 🔥返模型 |
| `backend/risk_models.py` | ✏️🩹修 get_kline |
| `backend/chat.py` | ✏️🩹删重复 SYSTEM_PROMPT_NO_TOOLS（TOOLS/_exec_tool 迁 S010） |
| `backend/limitup_screener/models.py` | ✏️移除 import astock |
| `backend/limitup_screener/data.py` | 🩹datetime import |
| `backend/seat_engine/models.py` | 🩹可变默认值 |
| ➕`backend/data/sources/*`、`backend/data/transport.py` | ➕拆分新增 |
| `backend/data_provider/`、`backend/enums.py`(旧) | 🗑️删 |
| `backend/routers/stock_data.py`/`stock_financial.py`/`limitup/*`/`market.py` | ✏️挂 response_model |
| 32 依赖者中其余 | ✏️改读模型字段 |

## 5. 设计方案

- **迁移策略**：按消费者分组分批，A 组（routers）先迁并挂 response_model → B 组（chat/mcp）→ C 组（engines）。每组的 dict 适配层（`to_dict()`）在该组全部消费者迁完后立即删除——有退出条件，不残留。
- **em_get 拆分**：限流/熔断/代理探测移到 `data/transport.py`，astock 各 source 只管取数+映射模型；保留限流语义不变（QPS≤2、直连优先失败降级代理、熔断器）。
- **bug 修复**：`get_kline`→`kline` 是静默失效（波动率恒 0.0），修后补单测锁住；其余 import/重复定义/可变默认值一并修。
- **取舍**：不重写 astock 的取数逻辑（五源分级、腾讯底座、东财走 em_get），只改返回类型与拆分文件。

## 6. 验收标准

- [ ] A1 astock/gstock/market 数据函数返回 S007 模型；`to_dict` 适配层仅对未迁移消费者保留
- [ ] A2 回归基线回放：10 只 code 的模型字段值与重写前 dict 字段语义一致（价格/涨跌幅/市值单位按 S007 §5.1 转换后一致）
- [ ] A3 `risk_models` 波动率/回撤/流动性对基线 code 返回非 0 真实值，单测锁住
- [ ] A4 routers 挂 response_model；FastAPI /docs 显示 schema
- [ ] A5 `chat.SYSTEM_PROMPT_NO_TOOLS` 仅一份；`limitup_screener/models` 不 import astock；seat_engine 可变默认值修复
- [ ] A6 `data_provider/` 与旧 `enums.py` 已删；`data/sources/*`+`data/transport.py` 就位
- [ ] A7 `pytest -m "not live"` 全过（含 S007 契约测试 + 新增 bug 回归测试）
- [ ] A10 `kline_resolver.fetch_kline(code, adjust="qfq")` 只返 qfq 源（百度/akshare），不回退 raw；`list_sources(adjust="qfq") == ["baidu","akshare"]`；`t16_panel_train.fetch_stock` 走 qfq 统一口径
- [ ] A8 :8900 现有端点行为兼容（返回 `{"data": ...}` 信封内模型 dict 形态）
- [ ] A9 涉市值/估值数据跑 `~/tools/financial_rigor.py` 验算通过

## 7. 合规自查（弱合规，按 CLAUDE.md §1 2026-07-30 调整）

> 2026-07-30 定位调整：合规降级为弱合规，仪式类改为风险提醒；仅核查工程底线。

- [x] 迁移只改返回类型与文件组织，不臆造数据（工程底线）
- [x] 东财端点仍走 `em_get`（已迁 `data/transport.py`），不裸调 requests（工程底线·防封）
- [x] 私有数据仍只存 VR_DATA_DIR（工程底线·隔离）
- [~] 涨停四池/连板股榜：`lianban_stocks` 不再强制剥离（弱合规后可如实呈现个股 code/name，公开榜单）。Emotion 模型仍省略该字段作**设计分层**（聚合 vs 客观榜单），但非红线。`emotion_from_dict` mapper 当前仍剥离——保留为设计选择，可后续按需放开。
- [~] SYSTEM_PROMPT 措辞放宽在 S010 落地（本 spec 不改 SYSTEM_PROMPT 措辞，仅 R7 删重复定义）

## 8. 测试计划

- 基线回放（S007 夹具）：10 只 code round-trip
- 新增 bug 回归：test_risk_models_kline / test_seat_engine_defaults / test_chat_prompt_no_dup
- `pytest -m "not live"` 全量
- live 冒烟：:8900 端点 + MCP 5 工具实测

## 9. 风险与回滚

- 🔴 32 依赖者迁移期：契约已冻结（S007）+ 分组迁移 + 适配层退出条件；每消费者迁完即测
- 🟡 迁移层残留风险：退出条件强制（组迁完即删 shape 转换），不残留
- 🟢 回滚：git revert；astock 取数逻辑未变，行为兼容
