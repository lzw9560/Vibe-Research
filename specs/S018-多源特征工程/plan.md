# Plan: S018 — 多源特征工程

> 状态：已实现（macro 第二批待 Fred API，见 验收报告.md）  日期：2026-07-29
> 关联：`spec.md`、`../S017-A股涨跌预测模型栈/plan.md`、`../S002`/`../S005`（数据源）
> 本 plan 仅定义技术实现，行为/验收以 `spec.md` 为准。

---

## 1. 架构总览

```
backend/predict/features/
├── registry.py        # 特征注册表（声明式）
├── external.py        # 外盘（SPX/VIX/A50/恒生科技/美债10Y/DXY）
├── fund_flow.py       # 热钱/资金流向组（高权重）
├── behavior.py        # 行为微观组 + 游资画像/一日游风险（高权重）
├── sentiment.py       # 情绪（涨停四池聚合/板块分歧度）
├── text.py            # 文本（newsradar LLM 情绪/事件，固定版本+提示词）
├── calendar.py        # 日历（节假日/交割/会议哑变量）
├── macro.py           # 宏观（DXY 第一批；汇率/大宗/利差 第二批）
└── selection.py       # SHAP + Boruta 特征选择
backend/predict/feature_interface.py   # 对接 S017 的统一抽取接口（S008 迁移只换实现）
```

## 2. 特征注册表 schema

`registry.py` 每条特征声明：
```
FeatureSpec(
  name: str,                  # 如 "overnight_spx_ret"
  source: str,                # "gstock" / "astock.em_get" / "limitup_sti" / "newsradar" / "computed"
  category: str,              # external / fund_flow / behavior / sentiment / text / calendar / macro
  availability_offset: int,   # t+k 可得（0=当日收盘后, 用于 stage 映射：S1/S2/S3/S4）
  stage: str,                 # s1 / s2 / s3 / s4（哪段解锁）
  compliance_flag: str,       # "ok" / "aggregate_only"（涨停四池聚合不泄露个股名）
  description: str,
)
```
- 训练/预测时按 head 的 `feature_subset`（name 列表）拉取；预测时按 stage 过滤 `availability_offset`/`stage`，**look-ahead 在注册表层防住**。

## 3. "特征-可得时间"对齐表

核心交付物（`registry.py` 内的声明 + 一份文档表）：列明每特征在"当日收盘后预测次日"场景的可得时间。
- 隔夜美股（SPX/NDX）/恒生科技/A50 夜盘：S2（T 开盘前）可得，走 `gstock` push2（em_get 限流）。A50 secid `100.XIN9` 需加入 `_INDICES`（S017-T0b 已实测可得）。
- **美债 10Y / DXY：数据源缺口**（S017-T0b 验证 push2 候选 secid 全空），待 Fred API（`DGS10`/`DTWEXB`，免费 key 存 `~/.vibe-research/`）接入后补登 S2；**未补前不入短线头**，`availability_offset` 标 N/A。
- VIX：secid `100.VIX` 待实测确认后补登 S2。
- 北向净流入（新规则）/融资/龙虎榜/主力净流入：S1（T-1 盘后），T+1 公布。
- 集合竞价：S3（9:15-9:25）。
- 量比突变/分时量价/实时封板资金：S4（盘中）。
- 不可得者禁入短线头；`availability_offset` 不达标的特征在 stage 过滤时被剔除。

## 4. 模块设计

### 4.1 external.py（外盘 5）
- SPX/NDX 隔夜涨跌、VIX、A50 夜盘、恒生科技、美债 10Y、DXY。
- 走 `gstock.py`（扩展美债/DXY 端点）；A50 夜盘新增数据源（先验证可得性）。

### 4.2 fund_flow.py（热钱组 5，高权重）
- 主力/大单净流入（5 日累计）、龙虎榜游资接力频次（聚合，不依赖个体标签）、涨停封板资金强度（封单/流通市值比，来自涨停四池聚合）、北向净流入（分段）、融资余额变化、板块资金净流入排名与轮动速度、大宗折价。
- 北向分段：2024 规则变更日断点，前后分桶；变更后只用盘后净额并标时效下降。

### 4.3 behavior.py（行为微观组 4 + 游资画像，高权重）
- A 短期反转（过去 1-5 日累计收益，A股最强负向因子之一）。
- B 异常换手率/量比（散户注意力代理，负向）。
- C 集合竞价金额/高开幅度/竞价封单（S3 解锁）。
- D 昨涨停今表现（打板盈亏比/溢价率，情绪温度计）。
- **游资画像/一日游风险**：席位历史持仓周期聚类成"接力型 vs 一日游型"画像（事前先验，不依赖个体标签）；一日游参与过高=负向风险特征。

### 4.4 sentiment.py（情绪 2）
- 涨停四池聚合情绪（连板梯队/封板率/炸板率/晋级率）——`compliance_flag=aggregate_only`，不泄露个股名。
- 板块分歧度（复用 `SectorDivergence` 逻辑）。

### 4.5 text.py（文本 1，第二批扩展事件抽取）
- newsradar 新闻 → LLM 抽情绪分 + 事件类型（监管/并购/回购/减持/业绩预告）。
- **固定 LLM 模型版本 + 固定提示词**，结果可复算；版本升级时重算全量。

### 4.6 calendar.py / macro.py
- calendar：节假日/交割日/重要会议哑变量（几乎零成本）。
- macro：DXY 第一批；汇率/大宗/利差第二批。

### 4.7 selection.py
- SHAP 排列重要性 + Boruta；短线头目标 ≤25 稳定特征；记录保留/剔除依据，可复算。

## 5. 北向分段设计
- 2024 规则变更日为硬断点；`NorthFlowSegmenter` 按日期分桶，变更前可用实时净额、变更后只用盘后净额并标 `staleness=high`。
- 训练时禁跨段拟合；S017 `train.py` 消费分段标记。

## 6. 与数据层集成
- 新增东财端点（北向分段口径、大宗商品）走 `em_get()` 限流，不裸调 requests。
- 外盘端点在 `gstock.py` 扩展。
- `newsradar.py` 接 LLM 抽情绪/事件。
- S008 数据层迁移：特征抽取收口在 `feature_interface.py`，迁移时只换实现，注册表与选择结果保留。

## 7. 与 S017 对接
- `feature_interface.py`：`get_features(head, stage, t) -> DataFrame`，按 head.feature_subset + stage 过滤 `availability_offset` 返回。
- S017 训练/预测经此接口取数；特征列表快照固化进模型产物，保证可复现。
