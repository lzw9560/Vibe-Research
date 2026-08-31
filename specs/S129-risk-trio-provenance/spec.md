# Spec: S129 — risk 三子维度 provenance 诚实化（critic 漏扫 #1 头条）

> 状态：待实现
> 作者：lzw9560  日期：2026-09-01
> 关联：S118 scan completeness critic #1 漏扫（`registry.md` S118 节 :304-305）——risk 三子维度（volatility/max_drawdown/liquidity_risk）失败返裸 0.0+warning 但无 data_status，`_merge_data_status` 不含三者 → composite risk 可在 3/8 维度静默归零时仍标 ok+LOW + factors 呈现"风险因素较少"。S128 or-zero 契约未覆盖（trio 是 `except: return 0.0` 无 provenance，非 `or 0` 强制归零，不同轴）。本 spec 闭合。

## 1. 问题 / 目标

critic #1 头条漏扫，已抽验实锤当前代码（2026-09-01）：

- `_calculate_volatility`(:412-431)/`_calculate_max_drawdown`(:434-455)/`_calculate_liquidity_risk`(:458-475) 三函数 except 块 `return 0.0` + warning，**无 data_status**；`len(closes)<2`/`not amounts`（bar 不足）也 `return 0.0`
- 调用处(:196-198) 只接 float，不接 status
- `_merge_data_status`(:216-218) 合 `base/cf/dt/seat/conc` 五态，**不含 trio** → trio 全失败时 data_status 仍 ok
- `_build_risk_factors`(:548-587) 对 status 全盲，只接 float → trio=0.0 时 `volatility>5`/`max_drawdown>10`/`liquidity_risk>0` 恒假 → 三 factor 静默不报 → `not factors`(:576) → 呈现 **"当前风险因素较少"**，而真相是"波动率/回撤/流动性三维度没算出来"

**严重度修正**（诚实标注，区分事实/推测）：
- **事实**：trio **不进 risk_score**（`dynamic_score = base_score + flow_adjustment` :166，S111 已诚实）也**不影响 risk_level**（:175-179 由 dynamic_score 阈值定）。
- **事实**：故非"risk_score 腐败"，而是 **data_status 撒谎 + factors 文本压制**。
- **事实**：承重链是 factors+data_status 喂 LLM/打板风险研判——`routers/limitup/analysis.py:21` 用 `update_one_day_risk_realtime` 做打板 risk 评估，`routers/risk.py:35,185`、`routers/stock_data.py:293` 同款消费。
- 触 §1.2 不臆造工程底线（呈现未算出的 0.0 当真"低风险/较少"=臆造）。

**目标**：trio 加 _meta sibling 返 (float, data_status)，`_merge_data_status` 含 trio，`_build_risk_factors` 消费 trio status → 失败维度显"数据缺失"非"较少"。全量 pytest 0 回归，registry 账本 critic #1 漏扫闭合。

## 2. 背景

- 仓内既有 `_meta` sibling 范式（对齐之）：`_calculate_concentration_risk_meta`(:488)/`_get_dragon_tiger_risk`(:265)/`calculate_base_risk`(:101) 均 `tuple[float, str]`。status 约定：fetch 失败/异常→"missing"、陈旧缓存→"degraded"、合法空→"ok"、成功→"ok"。
- `_merge_data_status`(:598-602) 取最差（missing>degraded>ok）。
- trio 调用方仅 `update_one_day_risk_realtime`(:158-258) 内 :196-198，**无外部调用方**（grep 实锤）→ 向后兼容仅护既有测试（`test_s008_t13b_kline:77-97` / `test_s008_bugs:37-68` / `test_regression_bugs:22-25` 调 `_calculate_volatility` 等拿 float）。
- OneDayRisk 字段 :45-47 `max_drawdown/volatility/liquidity_risk` 仍存 float（API 加性兼容，前端不破）。
- `_build_risk_factors` 调用方仅 :202-212（grep 实锤）。

## 3. 需求清单

### R1 trio _meta sibling（risk_models.py:412-475）
- [ ] R1.1 加 `_calculate_volatility_meta(code: str, window: int = 20) -> tuple[float, str]`：`except`(KeyError/ValueError/TypeError/AttributeError) → `(0.0, "missing")` + warning（对齐 `_calculate_concentration_risk_meta:518`）；`len(closes)<2` → `(0.0, "degraded")`（bar 不足非 fetch 失败，partial）；成功 → `(round(variance**0.5*100, 2), "ok")`。`_calculate_volatility` 改调 `_meta` 返 float（向后兼容，签名不变）。
- [ ] R1.2 加 `_calculate_max_drawdown_meta(code: str, window: int = 60) -> tuple[float, str]`：同 R1.1 约定（except→missing，`len<2`→degraded，成功含 max_dd=0.0 合法零→ok）。`_calculate_max_drawdown` 改调 `_meta` 返 float。
- [ ] R1.3 加 `_calculate_liquidity_risk_meta(code: str) -> tuple[float, str]`：except→missing，`not amounts`→degraded，`avg_amount>=50000000`（高流动性合法零）→`(0.0, "ok")`，`<50000000`→`(round(100-avg_amount/50000000*100, 2), "ok")`。`_calculate_liquidity_risk` 改调 `_meta` 返 float。
- [ ] R1.4 测试钉死（新 `test_s129_risk_trio_provenance.py`）：①三 `_meta` 成功→`(value, "ok")`；②except→`(0.0, "missing")`；③bar 不足（`len<2`/`not amounts`）→`(0.0, "degraded")`；④liquidity 合法零（`avg_amount>=50M`）→`(0.0, "ok")`；⑤`_calculate_volatility` 等仍返 float（向后兼容）。

### R2 调用处接 status + `_merge_data_status` 含 trio（risk_models.py:196-218）
- [ ] R2.1 :196-198 改 `volatility, vol_status = await _calculate_volatility_meta(code)` 等（三组，解构）。
- [ ] R2.2 :216-218 `_merge_data_status(base_status, cf_status, dt_status, seat_status, conc_status, vol_status, dd_status, liq_status)` —— 含 trio 三态。
- [ ] R2.3 测试钉死：trio 全 missing → `data_status="missing"`；trio 一 degraded 余 ok → `"degraded"`；trio 全 ok → `"ok"`（mock `astock.kline` 抛异常/返少 bar/返全 bar 三态）。

### R3 `_build_risk_factors` 消费 trio status（risk_models.py:548-587）
- [ ] R3.1 `_build_risk_factors` 签名加 `vol_status: str = "ok", dd_status: str = "ok", liq_status: str = "ok"`（默认 ok 向后兼容）。
- [ ] R3.2 三 factor 条件改 status 感知：`vol_status in ("degraded","missing")` → `factors.append("波动率数据缺失")`（非 `volatility>5` 分支）；`elif volatility>5` → 原文本 `f"波动率偏高({volatility}%)"`。max_drawdown/liquidity 同款（"回撤数据缺失"/"流动性数据缺失"）。
- [ ] R3.3 `not factors` 兜底(:576)保留（全 ok 且无风险因素时"较少"仍合法）。
- [ ] R3.4 调用处 :202-212 传 `vol_status=vol_status, dd_status=dd_status, liq_status=liq_status`。
- [ ] R3.5 测试钉死：①trio 全 missing → factors 含三"数据缺失"（非"较少"）；②trio degraded → 对应"数据缺失"；③trio ok+`volatility>5` → "波动率偏高"（原行为不破）。

### R4 registry + 回归
- [ ] R4.1 `registry.md` 加 S129 节标注 critic #1 漏扫闭合。
- [ ] R4.2 全量 `pytest -m "not live" --deselect` 既有 flaky（newsradar/s032/spec_consistency/test_s040/test_market_degrades_without_akshare）0 回归。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/risk_models.py` | R1 三 `_meta` sibling + R2 调处接 status + merge 含 trio + R3 `_build_risk_factors` 消费 status |
| `backend/tests/test_s129_risk_trio_provenance.py` | R1.4+R2.3+R3.5 新建测试 |
| `specs/S111-真实裂缝登记册/registry.md` | R4.1 S129 节 |

> 仅 3 文件，trio 无外部调用方，blast radius 极小。R1/R2/R3 均触 `risk_models.py` 同文件，**不可并行 impl**（单 agent 顺序改）。

## 5. 设计方案

**统一 _meta sibling 范式**（对齐 `_calculate_concentration_risk_meta` :488 / S123 R2/R4）：三函数加 _meta 返 (float, status)，原函数改调 _meta 返 float（向后兼容签名不变，既有 `test_s008_t13b`/`test_s008_bugs`/`test_regression` 拿 float 全绿）。

**status 约定**（对齐仓内既有）：
- `except`（fetch/parse 异常）→ "missing"（对齐 `_calculate_concentration_risk_meta:518`）
- `len(closes)<2`/`not amounts`（bar 不足）→ "degraded"（partial data，非 fetch 失败）
- 成功（含合法零：高流动性 0.0/无回撤 0.0）→ "ok"

> **边界诚实标注**：`len(closes)<2` 可能是新股历史不足（合法）或 kline 返 0 bar（fetch 失败但未抛异常）——无 `fetch_ok` 标志无法区分。"degraded"（未算出，非 ok）比"ok"（撒谎）诚实，比"missing"（overstate fetch 失败）克制。对齐 trio 走 `astock.kline`（mootdx 本地直连，非 `get_with_fallback_meta` 缓存层，无 `fetch_ok`）。若 0 bar 需精确区分，后续给 trio 接 `get_with_fallback_meta`——YAGNI，当前 degraded 已闭合"未算出 vs ok"撒谎。

**`_build_risk_factors` status 感知**：trio 失败维度显"数据缺失"factor（非"较少"）。conc/dt factors-text 同款盲态为 **residual follow-up**（不在本 spec，scope 守 trio）：`conc_status`/`dt_status` 已进 `_merge_data_status`（data_status 反映），仅 factors 文本未感知；留下一轮扫。

**OneDayRisk 字段不动**：`max_drawdown/volatility/liquidity_risk` 仍 float（API 加性兼容，前端不破，对齐 S123 R4 hit_rate 不加 schema 字段范式）。

## 6. 验收标准

- [ ] A1 R1：三 `_meta` 返 (float,status)，except→missing、bar 不足→degraded、成功→ok（含合法零）；原函数向后兼容返 float
- [ ] A2 R2：`_merge_data_status` 含 trio；trio missing→data_status=missing
- [ ] A3 R3：trio 失败→factors 显"数据缺失"非"较少"；ok+超阈→原文本不破
- [ ] A4 全量 `pytest -m "not live" --deselect` 既有 flaky 0 回归
- [ ] A5 registry critic #1 漏扫闭合

## 7. 合规与工程底线自查（逐条确认）

- [x] 不臆造：trio 失败由 0.0+无 status → (0.0, missing/degraded)+factors"数据缺失"，不伪装"低风险/较少"
- [x] 判断可复现：纯代码逻辑 + 测试 mock 钉死（不依赖 live）
- [x] 私有数据：不涉
- [x] em_get 防封：trio 走 `astock.kline`（mootdx 本地，非 em_get），不涉防封
- [x] §44：trio 不进 risk_score（base+cf 定），非胜率数字承重链；仅 data_status+factors 诚实化，§44 已降为参考性建议不阻塞

## 8. 测试计划

`pytest -m "not live"` + 新 `test_s129_risk_trio_provenance.py`（~11 测：R1.4 五测 / R2.3 三测 / R3.5 三测）。`--deselect` 既有 flaky（同 S123 集：`test_market_degrades_without_akshare` / newsradar `test_fetch_global_intel_wm_import_fails` / s032 refresh_loop / spec_consistency / `test_s040_backfill::test_run_backtest_async_passes_kline_cache`）。

## 9. 风险与回滚

- **风险**：`data_status` 语义变（trio missing 抬 data_status）→ 前端 risk-dashboard 若按 data_status 显降级徽章，trio 失败会多显 degraded/missing（**诚实化预期效果**，非回归）；须 PR 说明"trio 失败现显数据缺失/degraded"。
- **回滚**：三 `_meta` 独立可 revert（原函数返 float 不依赖 _meta 签名）；`_merge_data_status` 三 status 可单独撤；`_build_risk_factors` status 默认 ok 不破既有。
