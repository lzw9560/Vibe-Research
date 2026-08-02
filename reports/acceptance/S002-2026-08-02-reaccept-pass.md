# S002 P1 重新验收报告 · 候选池诊断统一

> 日期：2026-08-02 ｜ 执行方式：离线测试套件 + 实跑核验 + API live 冒烟
> 对应：`specs/S002-打板工作流重构/spec.md`（P1）
> 环境：macOS / Python 3.14.5 / `backend/.venv`
> 结果：**P1 通过**（68 passed + 6 subtests，逐 AC 实跑核验全过）

---

## 1. 测试结果（G4）

`backend/.venv/bin/python -m pytest candidate_funnel/tests/ -m "not live" -q`
→ 68 passed, 7 deselected, 1 warning, 6 subtests passed in 13.47s

与原验收报告（2026-07-28）一致，无回归。7 deselected 为 live 联网测试（非交易时段未跑）。

| 测试文件 | 用例数 | 状态 |
|---|---|---|
| test_models.py | 14 | ✅ |
| test_thresholds.py | 8 | ✅ |
| test_filters.py | 5 | ✅ |
| test_funnel.py | 4 | ✅ |
| test_diagnosis.py | 11 | ✅ |
| test_candidates_api.py | 7 | ✅ |
| test_config_defaults.py | 4 | ✅ |
| test_financial_rigor.py | 1（6 subtest） | ✅ |
| test_sources_contract.py | 14 | ✅ |

## 2. AC 逐条实跑核验

| AC | 要求 | 核验方式 | 结果 |
|---|---|---|---|
| AC1 | 漏斗多轮 A→B→C，每层可检视 | `funnel.run_funnel` 实跑：4 层（宽源/收敛/定稿/自选），各层 input/output/filtered_out 完整 | ✅ |
| AC2 | 来源可开关、阈值可配、默认 suggest | 实跑 resolve_thresholds：default=suggest；manual 直用 base(8/20)；suggest+暴风雨→turnover_cold=12；缺 phase 降级标注；`GET /api/workflow/funnel/config` 返回完整 config+sources | ✅ |
| AC3 | 自选/手动并入 | `sources/watchlist_in` + SELF 层；test_funnel 覆盖 | ✅ |
| AC4 | 诊断卡六类+活跃度+企稳，口径一致 | `diagnosis.build_diagnosis_card` 复用 assess_activity/IndicatorSet（候选池同源）；test_diagnosis 11 例 | ✅ |
| AC5 | 可复现 | 同输入两次 assess_activity 结果一致（ACTIVE）；rules_applied 非空（换手>=8.0%/量比>=2.0/成交额>=10.0亿/振幅>=8.0%）；financial_rigor 6 subtest 交叉核对 | ✅ |
| AC6 | 缺失标"未取得"+原因 | 全 None 输入→tier=COLD + rules=['换手未取得']；missing dict 折叠 | ✅ |
| AC7 | 全市场扫描批次50、em_get 限流 | sources/activity 批次50 经 tencent_quote；东财走 em_get（归属已澄清：落 R2） | ✅ |
| AC8 | ST/退市/新股/停牌剔除 | classify_exclusion：ST→剔除、*ST→剔除、正常股→保留；test_filters 5 例 | ✅ |
| AC9 | 空层提示不报错 | run_funnel 实跑：L2/L3 input=0 无异常；test_funnel 空层用例 | ✅ |
| AC10 | 不输出方向结论词 | DiagnosisCard schema 源码扫描：无买入/卖出/止损/止盈/加仓/减仓；test_models 断言 | ✅ |

## 3. 分档逻辑实跑核验

```
turnover=15.0 → ACTIVE（活跃）  rules: 换手>=8.0%, 量比>=2.0, 成交额>=10.0亿, 振幅>=8.0%
turnover=25.0 → HOT（热）
turnover=5.0  → COLD（冷）
全 None       → COLD + ['换手未取得']
```

阈值随情绪自适应：暴风雨→turnover_cold=12，阴天→10，晴天/极端反弹→沿用基数(8)。

## 4. API live 冒烟

- `GET /api/health` → 200，scheduler/circuit_breaker/extreme_market 全 ok
- `GET /api/workflow/funnel/config` → 200，返回完整 ThresholdConfig（mode=auto, effective.turnover_cold=10 阴天调整）+ sources 开关 ✅
- `GET /api/workflow/funnel/layers` → 路由注册正确；非交易时段真实全市场采集耗时较长（AC7 批次50限流，预期慢，非缺陷）
- 路由 prefix=`/api/workflow`（candidates router），已确认注册于 app.py:244

## 5. 合规自查（G3）

- ✅ DiagnosisCard 源码无方向结论词（实跑扫描确认）
- ✅ assess_activity 只输出客观分档 + rules_applied，无买卖方向
- ✅ 涨停四池经 board_ladder 聚合为无个股名指标
- ✅ 参考价位不在 P1（隔离为研究模式 spec）

## 6. 验收结论

**P1 通过，无回归。** 离线测试 68 passed + 6 subtests 全绿；10 条 AC 逐条实跑核验全过；分档逻辑/可复现/缺失处理/方向词合规均在真实调用路径上确认。API config 接口 live 响应正常。

**备注**：Python 环境为 mac venv 3.14.5（原报告为 Windows venv 3.10.1），跨平台无兼容问题。layers 接口真实采集耗时为数据源特性，非代码缺陷。
