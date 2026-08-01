# 任务拆分 · S002 P1 候选池诊断统一

> 对应：`spec.md`（spec）+ `plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含：依赖、改动文件、验收方式、映射 AC。
> 规则：每条完成即跑对应单测/验收；东财端点必经 `astock.em_get`；不写方向/参考价位（合规）。

---

## 阶段 A · 模型与口径（AC3/AC5）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | 建包骨架：`candidate_funnel/` + `__init__.py` + `tests/` | — | `candidate_funnel/__init__.py`、`tests/__init__.py` | `python -c "import candidate_funnel"` 不报错 |
| A2 | `BaseThreshold`：基数 8/20/2/10/8 | A1 | `models.py` | 实例化字段默认值=spec §5.2 |
| A3 | `ThresholdConfig`：mode(auto/suggest/manual)/base/adjustment/sentiment_phase/effective | A2 | `models.py` | 默认 mode=suggest |
| A4 | `IndicatorSet`：六类字段全量 + `missing: dict[str,str]` | A2 | `models.py` | None 字段不报错；missing 可填 |
| A5 | `Announcement`+`StabilizationSignals`+`ActivityTier`+`ActivityAssessment`(含 rules_applied) | A2 | `models.py` | ActivityTier 三枚举齐 |
| A6 | `DiagnosisCard`：indicators+activity+stabilization+risk_flags+as_of，**无位置结论词** | A4,A5 | `models.py` | 字段不含方向词 |
| A7 | `FilterRecord`+`FunnelLayer`+`FunnelResult` | A6 | `models.py` | FunnelResult 含 layers/final_candidates |
| A8 | `thresholds.resolve_thresholds(cfg, sti_phase)`：基数+情绪调整→effective；调整写入 adjustment | A3 | `thresholds.py` | manual 直用 base；缺 phase 降级 |
| A9 | 单测：模型口径一致性 + thresholds 解析（auto/suggest/manual/缺 phase） | A8 | `tests/test_models.py`、`tests/test_thresholds.py` | `pytest -m "not live"` 过 |

---

## 阶段 B · 漏斗引擎（AC1/AC7/AC9）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `sources/gene.py`：R1 涨停基因得分采集（复用 limitup_screener） | A4 | `sources/gene.py` | mock 返回 IndicatorSet 片段 |
| B2 | `sources/board_ladder.py`：R1 连板梯队（聚合涨停四池→无个股名指标） | A4 | `sources/board_ladder.py` | 输出含连板数/封板率，无个股名透传 |
| B3 | `sources/activity.py`：R2 全市场活跃度（换手/量比/成交额），批次 50，经 em_get | A4 | `sources/activity.py` | 批次计数=50；东财走 em_get。**AC7 批次50+限流约束落此（R1 宽源为聚合非 quote 扫描，见 spec AC7 澄清）** |
| B4 | `sources/fund_flow.py`：R2 资金流（主力净流/龙虎榜机构/北向） | A4 | `sources/fund_flow.py` | 北向不可得→missing |
| B5 | `sources/auction.py`：R3 集合竞价异动（复用 auction_screener） | A4 | `sources/auction.py` | 返回 auction_open_pct |
| B6 | `sources/catalyst.py`：R3 公告+板块联动 | A4 | `sources/catalyst.py` | announcements/concepts 填充 |
| B7 | `sources/watchlist_in.py`：自选/手动并行通道 | A4 | `sources/watchlist_in.py` | 接 routers/watchlist |
| B8 | ST/*ST/退市/新股/停牌 入口过滤工具（剔除或注入 risk_flags） | B1 | `sources/_filters.py` | ST 标的不入下层 |
| B9 | `funnel.run_funnel(stage,date,cfg)`：R1→R2→R3 + 自选并行，每层输出为下轮输入，空层提示 | A7,B1-B8 | `funnel.py` | 离线 mock 端到端跑通；空层返回提示 |
| B10 | 漏斗单测（mock 各 source，端到端 + 空层） | B9 | `tests/test_funnel.py` | pytest 过 |

---

## 阶段 C · 诊断卡聚合（AC3/AC4/AC6）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | `diagnosis.assess_activity(ind,eff)`：规则可复现分档（换手/量比/成交额/振幅），填 rules_applied | A8 | `diagnosis.py` | 同输入两次结果一致；rules_applied 非空 |
| C2 | `diagnosis.detect_stabilization(ind,market_ctx)`：企稳四信号+evidence | A4 | `diagnosis.py` | 每信号 bool 或 None+依据 |
| C3 | `diagnosis.build_diagnosis_card(code,cfg)`：聚合六类指标→IndicatorSet→DiagnosisCard | A6,C1,C2 | `diagnosis.py` | 返回 DiagnosisCard |
| C4 | missing 透明：任一取数失败记 `indicators.missing[field]=原因`，不补全 | C3 | `diagnosis.py` | 失败字段在 missing 且值仍 None |
| C5 | 诊断卡单测（含 missing 场景） | C4 | `tests/test_diagnosis.py` | pytest 过 |

---

## 阶段 D · 自适应阈值（AC2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | 对接 `limitup_sti`/`sentiment_weather` 取当日情绪 phase | A8 | `thresholds.py` | phase 取不到→None |
| D2 | auto 模式：按 phase 自动调档位边界（如暴风雨换手下限→12） | D1 | `thresholds.py` | 调整项入 adjustment |
| D3 | suggest 模式：给建议阈值+依据，用户可一键接受/手调 | D2 | `thresholds.py` | 返回 effective+依据 |
| D4 | manual 模式 + 情绪缺失降级（用 base 并标"情绪档未取得"） | D2 | `thresholds.py` | 缺 phase 不报错 |
| D5 | 自适应单测（三模式 + 缺 phase 降级） | D4 | `tests/test_thresholds.py` | pytest 过 |

---

## 阶段 E · API 路由（AC1-AC10）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | `routers/candidates.py` 框架 + `app.py` include_router | A7 | `routers/candidates.py`、`app.py` | /docs 出现新路由 |
| E2 | `POST /api/workflow/candidates/funnel`（stage/date→FunnelResult） | E1,B9 | 同上 | curl 返回 FunnelResult |
| E3 | `GET /api/workflow/candidates`（date→list[DiagnosisCard]） | E1,C3 | 同上 | curl 返回候选 |
| E4 | `GET /api/workflow/candidates/{code}/diagnosis` | E1,C3 | 同上 | curl 返回诊断卡 |
| E5 | `GET /api/workflow/funnel/layers`（run_id→各层检视） | E1,B9 | 同上 | curl 返回 layers |
| E6 | `GET/PUT /api/workflow/funnel/config`（ThresholdConfig+来源开关） | E1,A3 | 同上 | PUT 后 GET 一致 |
| E7 | 路由级缓存（`cache_response(ttl)` ~60s）+ VR_API_KEY 鉴权 | E1 | 同上 | 二次 GET 命中缓存 |
| E8 | API 单测 | E2-E7 | `tests/test_candidates_api.py` | pytest 过 |

---

## 阶段 F · 前端（US1-US7）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | `lib/candidates.ts`：API 客户端（复用 lib/api.ts，带 authHeaders） | E2-E6 | `lib/candidates.ts` | 可调 6 端点 |
| F2 | `components/candidate/FunnelLayers.tsx`：各层输入/输出/过滤原因 | F1 | 同路径 | 渲染 layers |
| F3 | `components/candidate/DiagnosisCard.tsx`：六类指标+活跃度档+企稳信号，无方向词 | F1 | 同路径 | 渲染诊断卡 |
| F4 | `components/candidate/ThresholdPanel.tsx`：auto/suggest/manual 切换+调参 | F1 | 同路径 | 三模式可切 |
| F5 | `pages/Candidates.tsx`：候选池主页（漏斗+最终候选+诊断卡抽屉） | F2-F4 | `pages/Candidates.tsx` | 页面可加载 |
| F6 | `router.tsx` 注册 `/candidates` 路由 | F5 | `router.tsx` | /candidates 可访问 |
| F7 | "交 AI 判断"按钮占位（依赖 S001，未修前禁用+提示） | F3 | DiagnosisCard.tsx | 按钮禁用态可见 |
| F8 | 前端冒烟（npm run dev 打开 /candidates 各交互） | F6 | — | 人工过各交互 |

---

## 阶段 G · 验收（全 AC）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| G1 | 逐条核对 AC1-AC10 | E8,F8 | — | AC checklist 全绿 |
| G2 | `financial_rigor.py` 复算候选排序/活跃度分档（AC5 可复现） | C1 | — | 复算结果与系统一致 |
| G3 | 合规自查（spec §2/§5）：无方向/参考价位/排名/收益 | 全部 | — | 自查表全绿 |
| G4 | `pytest -m "not live"` 全过 | A9,B10,C5,D5,E8 | — | 全绿 |
| G5 | 写验收报告，更新 spec 状态"已实现(日期)" | G1-G4 | `S002-*.md` | 报告归档 |

---

## 依赖图（关键路径）

```
A1→A2→A3→A8→D1→D2→D5
        ↓
A4→B1..B8→B9→B10
        ↓
   C1→C3→C5
        ↓
       E1→E2..E8 → F1..F8 → G1..G5
```

- A 阶段是地基，C/D 可与 B 部分并行（均依赖 A）。
- E 依赖 B+C+D；F 依赖 E；G 依赖 E+F。
- 关键路径：A → B9 → C3 → E2 → F5 → G1。

---

## 执行规则

1. **一次一任务**：按 ID 顺序，完成一条跑其验收方式再开下一条。
2. **合规前置**：每条任务实现前对照 spec §2/§5 合规自查栏确认符合 CLAUDE.md §1.1 弱合规口径（2026-07-30）——可出研判/推荐/买卖时机但仅挂轻量风险提醒「历史统计特征，市场有风险」，保留可复现等工程底线。
3. **数据走 em_get**：B3/B4 等东财端点必经 `astock.em_get`，不裸调。
4. **可复现**：C1 分档、A8 阈值均须可被 `financial_rigor.py` 复算。
5. **不引入参考价位/方向词**：F3 诊断卡、各模型字段均不含。
6. **commit 引用**：commit message 带 S002 + 任务 ID（如 `S002-A2 BaseThreshold`）。
