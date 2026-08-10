# Spec: S049a — 资金流取数修复（push2his 断连 → push2delay 降级 + 降级态诚实 missing）

> 状态：已实现（2026-08-11）
> 作者：Claude  日期：2026-08-11
> 级别：**medium**（后端取数链路改动，跨 data/sources + candidate_funnel；不接新外部源、无财务验算）
> 关联：S048（个股详情卡诊断链路）、S008（data/sources 重构）、memory `eastmoney-push2-ut-token`（push2 缺 ut / 断连已知问题）
> 流程门（AGENTS.md 分级）：medium —— develop 直接提交；spec + 单轮 review；后端 pytest 离线 + 联网冒烟。
> 实施偏差（见 §10）：实测 push2delay 为延迟镜像，**无论 lmt 多少只回最新 1 行 klines**——故 `fund_flow.py` 增加降级态 `main_net_5d` 诚实 missing（草案 §5"不改 fund_flow.py"不成立）。

## 1. 问题 / 目标

个股详情卡"资金流"块（`main_net_inflow`/`main_net_5d`）恒显"未取得"。实测根因：`stock_fund_flow_120d` 走 `push2his.eastmoney.com` 端点，该端点本机网络层断连（ConnectionError Max retries），但**同源 `push2delay.eastmoney.com` 实测返 200 + 正常 klines**（主力净流入 664611600 元）。

**目标**：push2his 取数失败时自动降级 push2delay，让资金流块在有数据时如实呈现，而非"未取得"。断连降级不引入新端点（push2delay 是东财官方延迟端点，memory `eastmoney-push2-ut-token` 已记"push2 间歇限流用 push2delay 降级"范式）。

## 2. 背景

- `backend/data/sources/eastmoney.py:272 stock_fund_flow_120d(code)`：调 `em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get", ...)`，`except Exception: return []`——断连静默返空，上层 `fund_flow.py:23` 见 `flows` 空标 missing"资金流未取得"。
- 实测（2026-08-11）三端点对比：
  - `push2his.eastmoney.com` → **ConnectionError**（Max retries exceeded）
  - `push2delay.eastmoney.com` → **200**，klines 正常（`2026-08-10,664611600.0,...`）
  - `push2.eastmoney.com` → ConnectionError
- `push2delay` 与 `push2his` 同路径同参数（`/api/qt/stock/fflow/daykline/get`，同 `ut` token `fa5fd1943c7b386f172d6893dbbd1`），仅 host 不同。东财 push2delay 是 push2 的延迟镜像（数据晚约 10-15 分钟，盘后/次日完全一致）——资金流是日级 T+1 盘后数据，延迟无实质影响。
- `candidate_funnel/sources/fund_flow.py:23` 是唯一消费者；`diagnose()` 经它取数填 `IndicatorSet.main_net_inflow`。
- em_get 走 `circuit_breaker.get_breaker("eastmoney")`（5 次失败 OPEN / 60s 恢复），但 push2his 断连是网络层 DNS/TCP，熔断器对单次 em_get 抛 ConnectionError → 熔断器计数 → 但 `stock_fund_flow_120d` 的 except 已吞掉，熔断器 OPEN 后连 push2delay 也被拒（同 breaker）。**降级须在 em_get 层之下或绕开熔断器**——见 §5。

## 3. 需求清单

- [x] R1 `stock_fund_flow_120d(code)` 在 push2his 失败时降级 push2delay，成功返正常 klines（不再空数组 → missing）
- [x] R2 降级对调用方透明——返回 shape `{date, main_net, small_net, ...}` 不变
- [x] R3 降级路径走 `em_get`（限流/熔断底线不变），不裸调 requests
- [x] R4 push2his 与 push2delay 都失败 → 返空 list（现状行为不变，上层 missing"资金流未取得"）
- [x] R5 单测：push2his 成功 → 用 push2his（不降级）；push2his 抛 ConnectionError + push2delay 成功 → 用 push2delay；两者都抛 → 空列表
- [x] R6 联网冒烟：实测 600519 返 1 行（push2delay 降级生效，`main_net=664611600`）
- [x] R7（实施中新增）push2delay 仅回 1 行时 `main_net_5d` 不以短窗口冒充 5 日累计 → 置 None + missing（AC6 诚实）；≥2 行保留既有"按可用天数求和"契约

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/eastmoney.py` | `stock_fund_flow_120d` 加 push2delay 降级（host 列表遍历 + em_get） |
| `backend/tests/test_s008_sources_eastmoney.py` | 补 R5 三分支单测（mock em_get 首次抛错二次成功 / 都成功用首次 / 都抛空） |
| `backend/candidate_funnel/sources/fund_flow.py` | （实施中新增）`len(flows) < 2` 时 `main_net_5d=None` + missing"资金流仅 1 天（降级源），5 日累计暂不可得" |

## 5. 设计方案

**降级位置**：在 `stock_fund_flow_120d` 内部，host 列表 `["push2his", "push2delay"]` 顺序试。不绕开 em_get——em_get 的熔断器是"eastmoney" 共享 breaker，push2his 断连会触发熔断计数，但 **em_get 内部对 ConnectionError 的处理是抛出而非吞**（见 `transport.py`），breaker 仅在 OPEN 时拒绝后续请求 60s。降级策略：

```python
def stock_fund_flow_120d(code: str) -> list[dict]:
    market_code = 1 if code.startswith("6") else 0
    params = {...}  # 不变
    headers = {...}  # 不变
    for host in ("push2his.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            d = em_get(f"https://{host}/api/qt/stock/fflow/daykline/get",
                       params=params, headers=headers, timeout=15).json()
            rows = _parse_klines(d)  # 抽出原 line 289-300 的解析
            if rows:  # 首个有数据的 host 即用
                return rows
        except Exception:
            continue  # 下一 host
    return []  # 都失败 → 空列表（现状行为）
```

**关键决策**：
- `if rows:` 而非 `if d.get("data"):`——push2his 偶发返 200 但 klines 空（断连恢复期），此时也应降级 push2delay（push2delay 数据更稳）。空 klines 视同失败继续下一 host。
- host 顺序 push2his 优先（实时性略好），失败才 push2delay——盘后/次日两者一致，盘中 push2delay 晚 10-15min，资金流是日级盘后数据无影响。
- 抽 `_parse_klines(d)` 内部函数避免重复解析逻辑（DRY）。
- 不改 `fund_flow.py`：返回 shape 不变，上层无感。

**不选的方案**：
- 改 em_get / 熔断器：影响面太大（所有东财端点共享 breaker），非本 spec 范围。
- 直连 push2delay 不试 push2his：push2his 通时实时性更好，且 push2delay 盘中延迟——保持优先 push2his 失败降级。
- datacenter 端点（`RPT_STOCK_CAPITALFLOW_DAY`）：实测返 0 rows（该 report 名不存在或需不同 filter），不可用。

## 6. 验收标准

- [x] A1 `pytest backend/tests/test_s008_sources_eastmoney.py -m "not live"` 全过（含新增三分支，7 passed）
- [x] A2 联网冒烟：实测 `stock_fund_flow_120d('600519')` 返 1 行（push2delay 降级生效，date=2026-08-10）
- [ ] A3 `diagnose("600519")` 的 `indicators.main_net_inflow` 非 None（端到端——并入 S049c 个股诊断验收一起跑）
- [x] A4 `pytest candidate_funnel/tests tests/test_s008_sources_eastmoney.py -m "not live"` 158 passed 无回归（全量回归在 C12 收口跑）

## 7. 合规与工程底线自查（逐条确认）

- [ ] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1）：本 spec 纯取数修复，无新增研判输出
- [ ] 判断可复现：资金流值来自东财 push2delay 端点原文，无臆造；push2his 失败降级路径可追溯（log 记降级事件）
- [ ] 涨停四池/连板股榜个股：不涉及
- [ ] 用户私有数据：不涉及
- [ ] 新增东财端点走 `em_get()` 限流：push2delay 复用既有 em_get（限流/熔断/代理底线不变），**非新端点**（同 path 同 ut，仅 host 换）

## 8. 测试计划（TDD 红→绿）

**后端红**（先写先跑红）：
1. `test_s008_sources_eastmoney.py` 补三用例（mock `em_get`）：
   - push2his 成功 → 用首 host（em_get 调 1 次，push2delay 不调）
   - push2his 抛 ConnectionError + push2delay 成功 → 用 push2delay（em_get 调 2 次，返 push2delay 数据）
   - 两者都抛 → 空列表（em_get 调 2 次都抛）

**后端绿**：实现 host 遍历降级。跑单测全绿。

**联网冒烟**（手动，A2/A3）：起后端，`curl /api/workflow/candidates/600519/diagnosis` 看 `indicators.main_net_inflow` 非 null。

## 9. 风险与回滚

- **push2delay 也被限流**：两 host 都断时返空（现状行为，无回归）；熔断器 OPEN 60s 后恢复重试——可接受（资金流非实时关键数据）。
- **push2delay 数据延迟**：盘中 10-15min，盘后/次日一致——资金流是日级盘后数据，无实质影响。
- **klines 解析抽函数**：`_parse_klines` 逻辑与原 inline 一致，无行为变化，仅 DRY。
- **回滚**：单 commit `git revert`，恢复单 host push2his——回到现状（断连时 missing）。

## 10. 实施记录（2026-08-11）

- **新发现**：`push2delay.eastmoney.com` 是延迟镜像，**无论 lmt 参数设多少只回最新 1 行 klines**（push2his 本机 ConnectionError）。故降级态只能治好 `main_net_inflow`（当日值），`main_net_5d` 拿不到 5 天窗口。
- **应对**：`fund_flow.py` 在 `len(flows) < 2`（即单行降级态）时置 `main_net_5d=None` + missing 文案"资金流仅 1 天（降级源），5 日累计暂不可得"；≥2 行保留既有契约（flows[-5:] 按可用天数求和，`test_main_net_5d_is_sum_of_last_five_in_wan` 4 行 fixture → 5500 万 通过）。阈值取 `<2` 而非 `<5`：既有契约允许短窗口求和，只有单行冒充"5 日"才是误导。
- **测试**：`test_s008_sources_eastmoney.py` 补三分支降级测试（7 passed）；`candidate_funnel` 全量 + eastmoney 158 passed。
- **联网冒烟**：`stock_fund_flow_120d('600519')` → 1 行，`{'date': '2026-08-10', 'main_net': 664611600.0, ...}`，降级生效。
- **遗留**：A3 端到端 diagnose 冒烟并入 S049c（个股诊断 as_of）一起验收；push2his 恢复后 main_net_5d 自动回归完整窗口，无需再改。
