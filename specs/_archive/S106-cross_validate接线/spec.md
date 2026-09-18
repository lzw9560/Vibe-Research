# Spec: S106 — cross_validate 接线 + Valuation 暴露 PS/PCF/discrepancy

> 状态：已实现(2026-08-30)
> 作者：lzw9560  日期：2026-08-30
> 级别：medium（接线孤儿模块 + 扩 model 字段，碰数据输出）
> 分支：`feature/S106-cross-validate`（off develop，squash-merge）
> 关联：S104/S105（hithink 已直连）/ grill「坚实数据底座」第 3 层孤儿接线

## 1. 问题 / 目标

**A. cross_validate 孤儿**：`data/validators.py::cross_validate`（S017 P1-c 纯函数库，Verdict 四档 + adopted_value）全后端零调用（审查确认）。多源口径仲裁层建好没人用 = 底座缺一块。

**B. PS/PCF 没传到下游**：S104 给 `full_valuation` 加了 `ps_ttm`/`pcf_ttm`（hithink 补），但 `Valuation` model + mapper 没这俩字段——PS/PCF 拿了没传到 `query_valuation` AI 工具，也没进 `/api/valuation` 端点。S104 遗留。

**目标**（严格 SDD）：
1. Valuation model + mapper 加 `ps_ttm`/`pcf_ttm`/`dividend_yield` 字段（补 S104 遗留）
2. `full_valuation` 暴露 hithink 备源 `pe_ttm_hithink`/`pb_hithink` + **数据层调 cross_validate 仲裁 PE/PB，dict 带 discrepancy**
3. 两出口透传 discrepancy：AI 工具 `query_valuation`（mapper→Valuation）+ HTTP 端点 `/api/valuation`（raw dict 已有）——**都做进 S106，不推前端**
4. MAJOR_DIFFERENCE 取主源不丢数据，discrepancy 给 AI/前端当研判护栏

## 2. 背景

- `cross_validate(field, {源名:值})`（`data/validators.py:79`）：≤1% CONSISTENT、1-5% DIFFERENCE、>5% MAJOR_DIFFERENCE（adopted=None）、单源 SINGLE_SOURCE、全 None UNKNOWN。插入序即优先级。
- 实测两源 PE/PB 一致到小数点后两位（茅台 19.92 vs 19.916204 <1% CONSISTENT）。
- **两出口**（实测确认）：`query_valuation`（`ai/tools/stock_tools.py:38`）走 mapper→Valuation model_dump；`/api/valuation`（`routers/stock_data.py:121`）直接返 `{"data": full_valuation(code)}` raw dict 不走 mapper。

## 3. 需求清单

- [x] R1 `Valuation` model 加 `pcf_ttm`/`discrepancy`
- [x] R2 `valuation_from_full_valuation` mapper 填 `ps_ttm`/`pcf_ttm`/`dividend_yield`/`discrepancy`
- [x] R3 `full_valuation` 暴露 `pe_ttm_hithink`/`pb_hithink` + 数据层调 cross_validate 仲裁 PE/PB 写 `discrepancy`（一处仲裁，两出口透传）
- [x] R4 `query_valuation` AI 工具：mapper 已透传 discrepancy，无需额外逻辑
- [x] R5 `/api/valuation` 端点：raw dict 已含 discrepancy，无需额外逻辑
- [x] R6 §44 边界：PE/PB 展示非"出结论"；discrepancy 护栏不阻断

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/astock.py` | `full_valuation` 暴露 `pe_ttm_hithink`/`pb_hithink` + 调 cross_validate 仲裁写 discrepancy（复用 valuation_snapshot，零额外请求） |
| `backend/models/valuation.py` | `Valuation` 加 `pcf_ttm`/`discrepancy` |
| `backend/data/mappers.py` | `valuation_from_full_valuation` 填 `ps_ttm`/`pcf_ttm`/`dividend_yield`/`discrepancy` |
| `backend/tests/test_s106_cross_validate.py` | 新增 11 用例 |

**注意**：`query_valuation`（stock_tools.py）和 `/api/valuation`（stock_data.py）**不动**——discrepancy 在数据层生成，两出口透传，无重复仲裁代码（方案 a）。

## 5. 设计方案

### 5.1 full_valuation 数据层仲裁（astock.py）

复用 S104 已有 valuation_snapshot 调用（5min 缓存，零额外请求），暴露备源 + 调 cross_validate：

```python
if code in hs:
    out["ps_ttm"] = hs[code].get("ps_ttm")
    out["pcf_ttm"] = hs[code].get("pcf_ttm")
    out["pe_ttm_hithink"] = hs[code].get("pe_ttm")   # 备源
    out["pb_hithink"] = hs[code].get("pb_mrq")       # 备源

# S106：PE/PB 交叉验证（东财 vs hithink）——数据层一处仲裁，两出口透传
from data.validators import Verdict, cross_validate
discrepancies = []
for field, em_val, hs_val in [
    ("pe_ttm", out.get("pe_ttm"), out.get("pe_ttm_hithink")),
    ("pb", out.get("pb"), out.get("pb_hithink")),
]:
    if em_val is not None and hs_val is not None:
        vr = cross_validate(field, {"东财": em_val, "hithink": hs_val})
        if vr.verdict in (Verdict.DIFFERENCE, Verdict.MAJOR_DIFFERENCE):
            discrepancies.append({"field": field, "verdict": vr.verdict.value,
                                  "deviation_pct": vr.max_deviation_pct})
if discrepancies:
    out["discrepancy"] = discrepancies
```

### 5.2 §44 边界（grill 锁定）

PE/PB 展示非"出结论"（§44 管 winrate/r/verdict）。MAJOR_DIFFERENCE **取主源（东财）不丢数据** + discrepancy 透传当护栏，不阻断。

## 6. 验收标准

- [x] A1 `query_valuation("600519")` 返 ps_ttm=9.361984/pcf_ttm=13.618296（S104 遗留修复）
- [x] A2 `/api/valuation?code=600519` raw dict 含 pe_ttm_hithink=19.916204/pb_hithink=6.455055
- [x] A3 PE/PB 一致时（CONSISTENT）无 discrepancy 键（茅台实测 None）
- [x] A4 PE/PB 差>5%（mock hithink PE=30）discrepancy 透传 `[{field,verdict:"major_difference",deviation_pct}]` + 取主源东财 PE=19.92
- [x] A5 hithink 断流（SINGLE_SOURCE）PE/PB 走东财，无 discrepancy
- [x] A6 `cross_validate` 不再孤儿（full_valuation 调用，spy 测试验证）
- [x] A7 两出口一致：AI model_dump discrepancy == raw dict discrepancy

## 7. 合规与工程底线自查

- [x] 不臆造：MAJOR_DIFFERENCE 取主源不丢数据，discrepancy 诚实标差异
- [x] §44 口径：PE/PB 展示非结论层；discrepancy 护栏不阻断
- [x] 私有数据隔离：无新增落盘
- [x] em_get 防封：不动

## 8. 测试计划

- **单测** 11 用例全 PASS：暴露 3 + MAJOR_DIFFERENCE 2 + SINGLE_SOURCE 1 + 孤儿激活 1 + mapper 1 + cross_validate 纯函数 3
- **真实冒烟**：query_valuation("600519") PS/PCF 非空 + 无 discrepancy；/api/valuation raw dict 含备源
- **全量 gate**：跑中（待回）

## 9. 风险与回滚

- **风险**：MAJOR_DIFFERENCE 取主源非 adopted=None，绕过 §44 ">5% 不采用"。**grill 锁定**：PE 展示非结论层，护栏式标记足够。
- **风险**：仲裁放数据层 full_valuation，让它承担仲裁职责。**接受**：一处仲裁两出口透传，比两处重复仲裁简洁（KISS）。
- **回滚**：删 full_valuation 仲裁块 + mapper/model 字段即退回。

## 10. 冲突审查表

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S017 P1-c `cross_validate 孤儿` | 纯函数库无人调 | full_valuation 调用 | **激活** | 数据层仲裁 PE/PB，孤儿上线 |
| S104 `full_valuation 补 PS/PCF` | dict 有 ps/pcf，mapper/model 没字段 | mapper/model 加字段 + 暴露 | **修复遗留** | Valuation 加 pcf_ttm/discrepancy，mapper 填 ps/pcf/dividend_yield |
| S104 `query_valuation` | 无 PS/PCF/discrepancy | 透传（mapper 已填） | 共存 | 不破坏现有字段 |
| S104 `/api/valuation` | raw dict 无 discrepancy | raw dict 带 discrepancy（数据层生成） | 共存 | 端点返 raw dict 已含，无需改端点代码 |

## 11. 范围外明确处置（SDD 严格，不含糊）

| 项 | 处置 | 理由 |
|---|---|---|
| PS/PCF 仲裁 | **不做** | hithink 唯一源（东财结构性零供给），无第二源。cross_validate 对单源返 SINGLE_SOURCE 直接取，不触发仲裁。 |
| 龙虎榜 hithink 集成 | **另立 spec S107** | 维度不同（hithink 个股+概念 vs 东财席位明细），互补不替代，需独立 schema 对齐。本 spec 不碰，S107 占位。 |
| 端点 discrepancy 前端展示 | **做进 S106** | 端点 raw dict 带 discrepancy 是后端职责（R3 已含）；前端渲染属前端 spec，但后端数据出口本 spec 完成。 |

## 12. 不在本 spec 范围

- 龙虎榜 hithink 集成 → spec S107（已立占位，维度不同需 schema 对齐）
- discrepancy 前端 UI 渲染（前端 spec，后端出口已完）
- 缓存治理全铺（datacenter/tencent，第 1 层后续切片）
