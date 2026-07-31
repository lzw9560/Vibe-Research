# Plan: S017 — A股涨跌预测模型栈

> 状态：草案  日期：2026-07-29
> 关联：`spec.md`、`../S018-多源特征工程/plan.md`、`../S002`/`../S005`（数据源）、`../S006`（S008 迁移）
> 本 plan 仅定义技术实现，行为/验收以 `spec.md` 为准。

---

## 1. 架构总览

```
backend/predict/
├── __init__.py
├── labels.py                 # 标签构造（短/中、板块/个股、>0 二分类）
├── feature_interface.py      # 特征抽取接口（对接 S018 注册表，S008 迁移只换实现）
├── heads/
│   ├── short_sector.py       # 起步实现
│   ├── short_stock.py        # 空实现+接口预留
│   ├── mid_sector.py         # 空实现+接口预留
│   └── mid_stock.py          # 空实现+接口预留
├── models/
│   ├── ensemble.py           # LightGBM+CatBoost 软投票
│   ├── regime.py            # HMM 体制切换
│   └── calibration.py       # Conformal 校准
├── train.py                 # purged walk-forward + embargo + 滚动再训
├── predict.py                # S1-S3 级联推理 + snapshot store
├── evaluate.py              # 胜率/混淆矩阵/校准/衰减
└── snapshots/               # 运行时快照（实际落 ~/.vibe-research/predict/snapshots/，不入 git）

backend/routers/prediction.py   # /api/prediction/{head}?stage=s1|s2|s3 + /intraday-framework
backend/chat.py TOOLS            # 加 prediction 工具（S010 落地前暂走）
frontend/src/pages/Prediction.tsx + src/lib/prediction.ts
frontend/src/components/prediction/   # StageTimeline/ProbabilityEvolutionChart/IntradayFramework/DisclaimerWall
```

## 2. 模块设计

### 2.1 labels.py
- `build_label(target, horizon, direction)`：target∈{sector_idx, stock_code}，horizon∈{short(1-3d), mid(5-20d)}，返回 `future_return>0` 二分类。
- 板块=申万一级行业指数收盘；个股=前复权收盘。
- 纯函数、可复算、单测锁住取数时点/口径。

### 2.2 heads/{short_sector,...}.py
- 每头 `Head` 类：`feature_subset`（该头用哪些特征，来自 S018 注册表快照）、`train()`、`predict(stage)`、`evaluate()`。
- short_sector 完整实现；其余三头 `raise NotImplementedError` 占位 + 接口齐备。

### 2.3 models/
> 偏离记录（2026-07-30 实测）：lightgbm 4.7 在 Windows 本环境 access violation（OSError，可 try/except）、hmmlearn 0.3.3 fit 死循环（不可捕获 hang）——均与 numpy 无关，降 numpy 无效。经用户决策：Windows 本期用 HistGB/GaussianMixture 替代，**保留 Linux/macOS 走原 LGB+HMM 的 TODO**（跨平台部署时按 platform 切换后端）。
- `ensemble.py`：`SoftVoteEnsemble`（**sklearn HistGradientBoosting + CatBoost** predict_proba 均权；实现 try lightgbm→OSError 降级 HistGB，Linux/macOS 轻量走 LGB，Windows 走 HistGB；TODO 跨平台）。
- `regime.py`：`GaussianMixtureRegimeSwitcher`（**sklearn GaussianMixture** 2-3 状态：牛/熊/震荡）；HMM 在 Windows hang 不可 try/except，按 `platform.system()` 切换：Windows→GMM，Linux/macOS→GaussianHMM（TODO，待跨平台验证）。
- `calibration.py`：`ConformalCalibrator`（**mapie 1.4.1 `SplitConformalClassifier(confidence_level, prefit=True).conformalize`**），输出校准概率 + 收益率 10/50/90 分位区间。

### 2.4 train.py
- `purged_walk_forward(df, embargo_days)`：时序切分 + embargo 防 leakage；禁止随机 K 折。
- `roll_retrain()`：按月/季滚动再训；北向规则变更日（2024）作分段断点，禁跨段拟合。

### 2.5 predict.py（级联核心）
- `predict_stage(head, stage, t)`：按 `availability_offset` 取该阶段可得特征子集，重打分；产出 `Snapshot{head,stage,t,prob,quantiles,shap_topk,features_used}`。
- `cascade_store`：`~/.vibe-research/predict/snapshots/{head}/{date}/{stage}.json`，版本化、演进可查；概率级联不覆盖（保留各阶段历史）。

### 2.6 evaluate.py
- `win_rate / confusion_matrix / calibration_curve / decay_curve`；关键指标可经 `financial_rigor.py` 复算。

## 3. 数据流

- **训练流**：S018 特征 → labels.py 标签 → purged walk-forward → ensemble+regime+calibration → 模型权重落 `~/.vibe-research/predict/models/`。
- **预测流（S1-S3 自动级联）**：
  - S1 (T-1 收盘后)：大部分特征解锁 → P1 快照。
  - S2 (T 开盘前)：+ 隔夜 A50/美股/美债 → P2 快照。
  - S3 (T 竞价 9:15-9:25)：+ 竞价数据 → P3 快照，跳变标记。
- **S4 盘中研判框架**：`/intraday-framework` 返回教育性清单（看什么/怎么判），**非信号、非自动推送**。

## 4. 前端工作流交互设计（半自动化交易助手）

页面 `frontend/src/pages/Prediction.tsx`，入口挂"交易工作台"导航组。

### 4.1 用户旅程
1. **风险提醒 opt-in**：首次进 `/prediction` 弹「历史统计特征，市场有风险」轻量提醒确认，存 localStorage（非强制免责墙）。
2. **预测头 Tab**：短线×板块 / 短线×个股 / 中长线×板块 / 中长线×个股；起步仅短线×板块可点，其余灰显「待实现」。
3. **阶段时间线 `<StageTimeline>`**：横向 S1→S2→S3→S4 进度条；显示当前阶段、各段快照时间戳、**概率演进折线**（P1→P2→P3 随阶段变化）；当前高亮、未到灰显。
4. **S1 筛选表 `<PredictionTable>`**：Top 板块/个股，列=上涨概率/收益率分位区间/SHAP top3 驱动特征，带免责 chip；可排序筛选；行操作「加入关注」。
5. **S3 竞价跳变**：9:15-9:25 轮询（30s），P3 到达后概率显著跳变标的高亮 + `<JumpBadge>「竞价跳变」`，置顶。
6. **S3 收敛 → 人工研判**：选中候选 →「进入研判」按钮 → 推入研判面板。
7. **S4 盘中研判框架 `<IntradayFramework>`**（教育性，无信号）：对每候选展示「看什么/怎么判」清单——量比突变阈值、分时量价形态、封板资金变化、龙头属性实时；每项给「当前值 vs 阈值/参考」客观呈现 + 教育性「研判提示」文字；**无买入/卖出按钮**，仅用户自标「看好/已入/已出/不看了」。
8. **演进历史与复盘 `<ProbabilityEvolutionChart>`**：标的概率演进 S1→S2→S3→S4 + 次日实际涨跌回放，事后归因哪段信号有效/失效。

### 4.2 组件清单
- `<DisclaimerWall>` — opt-in 免责墙
- `<StageTimeline>` — 四段进度 + 演进曲线
- `<PredictionTable>` — 概率/区间/SHAP 表
- `<JumpBadge>` — 竞价跳变标记
- `<IntradayFramework>` — S4 教育性研判清单（**无交易按钮**）
- `<ProbabilityEvolutionChart>` — 演进历史复盘

### 4.3 数据层
- `src/lib/prediction.ts`：`usePrediction(head, stage)` TanStack Query hook；竞价阶段轮询 30s，盘中按需刷新。
- 统一走 `lib/api/client.ts`（S013 落地后；未落地前用现有 fetch 封装）。

### 4.4 合规 UI 约束（弱合规 2026-07-30）
- 所有概率/区间旁挂轻量风险提醒 chip「历史统计特征，市场有风险」（非强制免责墙）。
- S4 面板可出研判提示与操作建议（用户即决策者），但须挂轻量提醒、不承诺确定性收益；客观值 + 研判提示 + 用户自标状态并存。

## 5. 依赖与安装
- `lightgbm` / `catboost` / `scikit-learn` / `hmmlearn` / `mapie`（或 `mapie>=0.7`）。
- Windows `.venv` 预装验证（catboost 轮子大但官方有 Windows 预编译；lightgbm 有预编译；hmmlearn 纯 Python；mapie 纯 Python）。**装不上早暴露**——T0 任务。

## 6. 与现有系统集成
- 数据源：`astock.py`(A股价量/北向/融资/龙虎榜/行业)、`gstock.py`(外盘)、`market.py`/`limitup_sti`(情绪聚合)、`newsradar.py`(资讯)、`risk_models.py`(风险)。
- AI 出口：`chat.TOOLS` 加 `prediction_short_sector` 工具（S010 落地后转 registry）。
- 与 S002/S005 漏斗并列独立，结果分目录分页面；可选把 S002 候选/S005 终选作为 short_stock/mid_stock 头的输入（后续阶段）。
- S006/S008 数据层迁移：特征抽取收口在 `feature_interface.py`，迁移时只换实现，模型权重与快照保留。

## 7. 可复现与存储
- 固定随机种子、固定模型版本/超参、固定特征列表快照（来自 S018 注册表）。
- 模型权重→`~/.vibe-research/predict/models/`；快照→`~/.vibe-research/predict/snapshots/`；**均不进 git**。
- 训练/预测全流程可复算，关键指标跑 `financial_rigor.py` 核对。
