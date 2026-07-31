# 任务拆分 · S005 中长线价值选股漏斗

> 对应：`spec.md`（spec）+ `plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含：依赖、改动文件、验收方式、映射 AC。
> 规则：每条完成即跑对应单测/验收；财务端点必经 `astock.em_get`；不写方向/参考价位/主观评分（合规）；护城河只出客观代理、综合判断交 AI。

---

## 阶段 A · 模型与去劣计算（AC3/AC6/AC8）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | 建包骨架：`value_funnel/` + `__init__.py` + `tests/` | — | `value_funnel/__init__.py`、`tests/__init__.py` | `python -c "import value_funnel"` 不报错 |
| A2 | `QualityMetric`：index/name/value/threshold/passed/inapplicable/exempt/evidence/missing | A1 | `models.py` | 实例化字段齐 |
| A3 | `MoatSignals`：毛利率持续性/排名/ROE稳定性/可识别证据 + "综合判断交AI" note | A2 | `models.py` | 无主观评分字段 |
| A4 | `QualityAssessment`：metrics+moat+pass_count+双口径通过率+data_years+降级标注 | A2,A3 | `models.py` | 双口径字段齐 |
| A5 | `CompanyAnalysis`：商业模式/护城河/财务/估值位置/风险 + `counter_arguments`反面论据 | A2 | `models.py` | 反面论据字段在 |
| A6 | `MasterPerspective`+`DeepAnalysisSkeleton`：四大师框架+数据骨架+问题清单+ai_text待填+ai_pending | A2 | `models.py` | ai_pending 默认 True |
| A7 | `ValueFilterRecord`+`ValueFunnelLayer`+`ValueFunnelResult` | A6 | `models.py` | FunnelResult 含 layers/l2/l3/l4 |
| A8 | `quality._metric_1_roe`：10年平均ROE（<8%未通过）；5-10年降级标"不足10年"，<5年不适用 | A2 | `quality.py` | 年限降级生效 |
| A9 | `quality._metric_2_fcf`：5年累计自由现金流（经营CF−资本开支，为负未通过） | A2 | `quality.py` | 累计计算正确 |
| A10 | `quality._metric_3_interest`：利息覆盖（EBIT/利息<2未通过）；银行/保险标不适用 | A2 | `quality.py` | 银行标 inapplicable |
| A11 | `quality._metric_4_gross_margin`+`_metric_6_net_margin`：长期毛利率<15%/长期净利率<5% | A2 | `quality.py` | 两条独立计算 |
| A12 | `quality._metric_5_cash_quality`：经营CF/净利润5年均值<0.7 | A2 | `quality.py` | 5年均值口径 |
| A13 | `quality._metric_7_share_dilution`：5年股本膨胀>20%，并购所致标不计未通过 | A2 | `quality.py` | 并购豁免生效 |
| A14 | `quality._check_exemptions`：豁免A战略投入期/B周期底部/C护城河补偿（提示性标注） | A8-A13 | `quality.py` | 命中豁免标 exempt+rule |
| A15 | `quality.compute_quality(code)`：编排7条+豁免+双口径通过率+年限降级+missing透明 | A14 | `quality.py` | 返回 QualityAssessment |
| A16 | 单测：models + quality（年限降级/银行保险/双口径/数据缺失） | A15 | `tests/test_models.py`、`tests/test_quality.py` | `pytest -m "not live"` 过 |

---

## 阶段 B · L1 全市场扫描（AC1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `sources/l1_scan.scan_universe(direction)`：行业/主题扫描（复用 concept_blocks/hot_concepts/行业排名） | A7 | `sources/l1_scan.py` | 输入"AI算力"返回候选列表 |
| B2 | 指数成分扫描（沪深300/纳斯达克100 等） | B1 | `sources/l1_scan.py` | 指数输入返回成分股 |
| B3 | ST/*ST/退市 L1 即剔除；未上市候选标"未上市"直接放行进 L3（去劣不适用） | B1 | `sources/l1_scan.py` | ST 不入 L1 输出 |
| B4 | L1 单测（mock 概念/指数接口） | B3 | `tests/test_funnel.py` | pytest 过 |

---

## 阶段 C · L2 去劣 + 护城河（AC3/AC6/AC7）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | `moat.moat_signals(code)`：毛利率持续性/行业排名/ROE稳定性/可识别证据，不评分 | A3 | `moat.py` | 输出客观代理，无评分 |
| C2 | L2 层编排：对 L1 输出逐只 `compute_quality` + `moat_signals`；未通过者弃出，豁免命中者保留；护城河标注不剔除 | A15,C1 | `funnel.py` | L2 输出≤10，附被弃原因 |
| C3 | 财务取数经 `astock.em_get` + 熔断 + 路由缓存；超限标"未取得" | C2 | `sources/l2_financials.py` | em_get 调用，失败标 missing |
| C4 | L2 单测（含数据缺失/年限不足/银行保险/豁免命中） | C3 | `tests/test_funnel.py` | pytest 过 |

---

## 阶段 D · L3 精细分析骨架（AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | `sources/l3_analysis.build_analysis_skeleton(code)`：商业模式/护城河证据/财务摘要/估值位置/风险（复用 full_valuation/valuation_percentile/eastmoney_reports） | A5 | `sources/l3_analysis.py` | 返回 CompanyAnalysis |
| D2 | `counter_arguments` 反面论据占位（合规：呈现正反两面） | D1 | `sources/l3_analysis.py` | 字段非空占位 |
| D3 | L3 单测 | D2 | `tests/test_funnel.py` | pytest 过 |

---

## 阶段 E · L4 四大师骨架 + AI 出口（AC5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | `sources/l4_deep_skeleton.build_deep_skeleton(code)`：四大师框架+数据要点+引导问题清单，`ai_text` 留空、`ai_pending=True` | A6,D1 | `sources/l4_deep_skeleton.py` | 返回 DeepAnalysisSkeleton，ai_text=None |
| E2 | `deep-ai` 端点：调 `chat.run_chat_stream` 填四大师文字（**依赖 S001 修复**） | E1,S001 | `routers/value_funnel.py` | 调通返回 ai_text（S001 修后） |
| E3 | `ai_pending` 按钮：S001 未修前禁用 + 提示"AI 未就绪" | E2 | 前端 DeepSkeleton.tsx | 禁用态可见 |
| E4 | L4 单测（骨架生成；AI 文字 mock） | E1 | `tests/test_funnel.py` | pytest 过 |

---

## 阶段 F · API 路由（AC1-AC10）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | `routers/value_funnel.py` 框架 + `app.py` include_router | A7 | `routers/value_funnel.py`、`app.py` | /docs 出现新路由 |
| F2 | `POST /api/value-funnel/scan`（direction→L1 候选） | F1,B3 | 同上 | curl 返回候选列表 |
| F3 | `POST /api/value-funnel/run`（direction/stage→ValueFunnelResult） | F1,C2,D2,E1 | 同上 | curl 返回 FunnelResult |
| F4 | `GET /api/value-funnel/result`（run_id→ValueFunnelResult） | F3 | 同上 | curl 返回结果 |
| F5 | `GET /api/value-funnel/layers`（run_id→各层检视） | F3 | 同上 | curl 返回 layers |
| F6 | `GET /api/value-funnel/{code}/quality`（→QualityAssessment） | F1,C2 | 同上 | curl 返回去劣+护城河 |
| F7 | `POST /api/value-funnel/{code}/deep-ai`（调 chat 填 L4，依赖 S001） | F1,E2 | 同上 | S001 修后返回 ai_text |
| F8 | `GET /api/value-funnel/{code}/analysis`（→CompanyAnalysis） | F1,D2 | 同上 | curl 返回 L3 骨架 |
| F9 | 路由级缓存（`cache_response(ttl)` ~5min）+ VR_API_KEY 鉴权 | F1 | 同上 | 二次 GET 命中缓存 |
| F10 | API 单测 | F2-F9 | `tests/test_value_funnel_api.py` | pytest 过 |

---

## 阶段 G · 前端（US1-US9）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| G1 | `lib/value_funnel.ts`：API 客户端（复用 lib/api.ts，带 authHeaders） | F2-F8 | `lib/value_funnel.ts` | 可调 7 端点 |
| G2 | `components/value_funnel/FunnelLayers.tsx`：四层检视（输入/输出/被弃+原因） | G1 | 同路径 | 渲染 layers |
| G3 | `components/value_funnel/QualityCard.tsx`：7条通过/未通过/不适用 + 双口径通过率 + 豁免 + 护城河代理 | G1 | 同路径 | 双口径同屏 |
| G4 | `components/value_funnel/AnalysisSkeleton.tsx`：L3 精细分析骨架（含反面论据） | G1 | 同路径 | 渲染骨架+反方 |
| G5 | `components/value_funnel/DeepSkeleton.tsx`：四大师骨架 + "交AI"按钮（依赖 S001，未修禁用） | G1,E3 | 同路径 | 按钮禁用态可见 |
| G6 | `pages/ValueFunnel.tsx`：主页（输入方向→四层收敛→终选3家） | G2-G5 | `pages/ValueFunnel.tsx` | 页面可加载 |
| G7 | `router.tsx` 注册 `/value-funnel` 路由 | G6 | `router.tsx` | /value-funnel 可访问 |
| G8 | 前端冒烟（npm run dev 打开 /value-funnel 各交互） | G7 | — | 人工过各交互 |

---

## 阶段 H · 验收（全 AC）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| H1 | 逐条核对 AC1-AC10 | F10,G8 | — | AC checklist 全绿 |
| H2 | `financial_rigor.py` 复算去劣指标（ROE/FCF/利息覆盖等，AC8 可复现） | A15 | — | 复算结果与系统一致 |
| H3 | 合规自查（spec §2/§5）：无方向/参考价位/主观评分/一流非一流结论词；护城河不评分 | 全部 | — | 自查表全绿 |
| H4 | `pytest -m "not live"` 全过 | A16,B4,C4,D3,E4,F10 | — | 全绿 |
| H5 | 写验收报告，更新 spec 状态"已实现(日期)" | H1-H4 | `S005-*.md` | 报告归档 |

---

## 依赖图（关键路径）

```
A1→A2→A7→F1→F3→G6→G7→H1
        ↓
A8..A14→A15→C2→F3
              ↓
             D1→E1→E2(依赖S001)→F7
B1→B3→C2        ↑
C1→C2           S001（前置）
```

- A 阶段是地基；B/C/D 可与 A 部分并行（B/C/D 依赖 A）。
- E 依赖 A-D + **S001**（L4 AI 文字）。
- F 依赖 A-E；G 依赖 F；H 依赖 F-G。
- 关键路径：A → A15 → C2 → F3 → G6 → H1。
- **阻塞前置**：E2/F7 的 AI 文字依赖 S001 修复；S001 未修前 E2/F7 跳过（标 ai_pending），不阻塞前三层与漏斗主体。

---

## 执行规则

1. **一次一任务**：按 ID 顺序，完成一条跑其验收方式再开下一条。
2. **合规前置**：每条实现前对照 spec §2/§5 合规自查栏确认不触红线（无方向/参考价位/主观评分）。
3. **数据走 em_get**：C3 等财务端点必经 `astock.em_get`，不裸调。
4. **可复现**：A8-A15 各去劣指标均须可被 `financial_rigor.py` 复算（evidence 字段填取数时点+口径）。
5. **护城河不评分**：C1 只出客观代理信号，综合判断交 AI，禁主观★★★。
6. **双口径**：A4/C2/F6 通过率同屏展示绝对 N/7 + 调整 N/(7−不适用)。
7. **S001 依赖**：E2/F7/G5 的 AI 文字功能在 S001 修复前禁用+提示，不阻塞漏斗前三层。
8. **commit 引用**：commit message 带 S005 + 任务 ID（如 `S005-A15 compute_quality`）。
