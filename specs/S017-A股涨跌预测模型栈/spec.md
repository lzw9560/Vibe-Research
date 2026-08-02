# Spec: S017 — A股涨跌预测模型栈（短线/中长线 × 板块/个股 四头解耦）

> 状态：已实现 2026-08-01
> 作者：Claude  日期：2026-07-29
> 关联：`../S002-打板工作流重构/spec.md`（短线候选池，数据源）、`../S005-中长线价值选股漏斗/spec.md`（中长线，数据源）、`../S006-系统重写纲领/spec.md`（数据层迁移 S008）、`../S018-多源特征工程/spec.md`（特征供给，配套）、`../../ARCHITECTURE.md`、`../../CLAUDE.md` §0/§1（2026-07-29 新边界）
> 本 spec 与 S018 解耦：S017 定义模型栈与预测头/标签/训练/评估/服务；S018 定义特征供给。两者通过特征注册表接口对接。

---

## 1. 问题 / 目标

用户要私人投研助理给出板块/个股涨跌的**研究参考性概率预测**，并按短线(1-3日)/中长线(5-20日)分开建模。当前 S002/S005 漏斗只做筛选不做涨跌预测（其非目标显式排除）。本 spec 新增 ML 预测栈，与两条漏斗并列独立。

**目标**：搭建四头解耦预测栈——`短线×板块` / `短线×个股` / `中长线×板块` / `中长线×个股`，各自独立训练、独立胜率看板。**起步只做 `短线×板块` 一个头**，验证样本外有真实边缘后再扩。底座 LightGBM+CatBoost 集成 + GMM 体制切换 + Conformal 校准，输出**上涨概率 + 收益率分位区间**，非点预测。

---

## 2. 背景

- 数据层：`astock.py`(A股)/`gstock.py`(美港股)/`market.py`(情绪)/`newsradar.py`(资讯) 已有；`limitup_sti` 涨停四池聚合情绪、`risk_models.py` 风险标注可作特征/标签源。
- S006 系统重写纲领（S007-S016）将迁数据层为 Pydantic 契约（草案/长分支 `rewrite/main`）。**本期在 develop 上构建，特征抽取收口在接口后**，S008 迁移时只换实现不动模型。
- §1 新边界（2026-07-29）允许教育研究性判断（含买卖时机研判/风险标注），守"不承诺收益/可复现/私有数据隔离/四池聚合不泄露个股"。本 spec 的涨跌概率预测属研究性判断，须挂免责声明、可复算、不承诺收益。
- 与 S002/S005 关系：并列独立。S002/S005 的"不预测涨跌"非目标是其**范围选择**，非 §1 硬禁；本 spec 在新边界内显式承担预测职责。
- 2026-07-30 平台偏离（Windows 实测）：lightgbm 4.7 access violation（可 try/except 兜底）、hmmlearn 0.3.3 fit 死循环（不可捕获）；本期 Windows 以 HistGB/GMM 落地，Linux/macOS 保留 LightGBM/HMM 路线，regime 层按 `platform.system()` 切换后端（详见 plan.md 偏离记录）。

---

## 3. 需求清单

- [ ] R1 四头解耦架构：`predict/heads/{short_sector, short_stock, mid_sector, mid_stock}` 各自独立标签/模型/评估，互不耦合
- [ ] R2 标签构造：短线=未来1-3日累计收益>0（二分类）；中长线=未来5-20日累计收益>0；板块=申万一级行业指数；个股=个股前复权收盘
- [ ] R3 起步范围：仅实现并训练 `short_sector` 一个头；其余三头预留接口与空实现，验证有边缘后再逐个开
- [ ] R4 模型栈：LightGBM + CatBoost 双模集成（软投票）→ GMM 体制切换（条件加权）→ Conformal 校准（输出校准概率与分位区间）
- [ ] R5 训练协议：purged walk-forward（embargo 防 leakage）+ 滚动再训；北向资金 2024 规则变更日作分段断点
- [ ] R6 评估：样本外胜率、混淆矩阵、概率校准曲线、衰减曲线；全部可经 `financial_rigor.py` 复算
- [ ] R7 服务化：`/api/prediction/{head}?stage=s1|s2|s3` 返回该阶段上涨概率+分位区间+Top板块/个股+演进历史+免责声明；MCP 工具同步（走 S010 registry，若未落地暂走 `chat.TOOLS`）；S4 盘中研判框架经 `/api/prediction/{head}/intraday-framework` 返回**教育性研判指引**（看什么/怎么判，非信号）
- [ ] R8 前端看板：`/prediction` 页，按预测头分 Tab，展示概率/区间/历史胜率衰减，卡片挂免责声明
- [ ] R9 私有数据隔离：模型产物（权重/特征快照）存 `~/.vibe-research/predict/`（VR_DATA_DIR），不进 git
- [ ] R10 可复现：固定随机种子、固定模型版本与超参、固定特征列表（来自 S018 注册表快照），训练/预测全流程可复算
- [ ] R11 **多段级联预测（S1–S3 自动 + S4 盘中研判框架，半自动化定位）**：S1(T-1收盘后)→S2(T开盘前)→S3(T竞价 9:15-9:25) 三段自动级联重打分（同模型、按 `availability_offset` 解锁特征子集、概率级联不覆盖、版本化快照+演进历史）；S3 收敛后候选已少量，**交用户人工研判**；**S4 盘中不做自动信号推送**，输出"盘中研判框架"（量比突变/分时量价/封板资金变化/龙头实时属性，看什么+怎么判）作教育性研判指引，用户据此自行决策。定位为**半自动化交易助手**：系统做重活（筛选/打分/概率/研判框架），用户做决策。S4 盘中实时在线推理/推送衔接 S002 P2 盘中信号 spec。

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/predict/__init__.py` | ➕新增包 |
| ➕`backend/predict/labels.py` | 标签构造（短/中、板块/个股、>0 二分类） |
| ➕`backend/predict/heads/{short_sector,short_stock,mid_sector,mid_stock}.py` | 四头，起步只实现 short_sector |
| ➕`backend/predict/models/ensemble.py` | LightGBM+CatBoost 软投票集成 |
| ➕`backend/predict/models/regime.py` | GMM 体制切换（HMM 留 Linux/macOS TODO） |
| ➕`backend/predict/models/calibration.py` | Conformal 校准（mapie 或自实现） |
| ➕`backend/predict/train.py` / `predict.py` / `evaluate.py` | walk-forward 训练/推理/评估 |
| ➕`backend/predict/feature_interface.py` | 特征抽取接口（对接 S018 注册表，S008 迁移时只换实现） |
| ➕`backend/routers/prediction.py` | API 路由 |
| `backend/chat.py` TOOLS | 加 prediction 工具（暂走，S010 落地后转 registry） |
| ➕`frontend/src/pages/Prediction.tsx` + `src/lib/prediction.ts` | 看板页 |
| `frontend/src/router.tsx` / `navigation` | 加入口 |
| `backend/requirements` 或 `pyproject` | 加 lightgbm/catboost/scikit-learn/hmmlearn/mapie（hmmlearn 仅 Linux/macOS 需要） |
| `specs/README.md` | 加 S017/S018 索引行 |

---

## 5. 设计方案

**四头解耦**：每个头独立标签构造 + 独立特征子集 + 独立模型 + 独立评估看板。理由：短线信噪比与特征权重与中长线差异大，板块噪声远小于个股，混训必互相拖累。解耦后单头失败不牵连其他。

**起步只做 short_sector**：信噪比最好、外部特征（A50/美股/北向）最有效、数据最全、样本充足。验证样本外胜率显著高于基准（>50% 且校准良好）再扩 short_stock，再到中长线两头。

**模型栈选择取舍**：
- LightGBM+CatBoost 而非 XGBoost：同类树模型，性价比与类别特征处理更优；不选 XGBoost 单模（集成方差更小）。
- GMM 体制切换：A 股牛/熊/震荡风格切换明显，单模跨体制拟合是重要失败源；GMM 低成本、可解释（Windows 实测 hmmlearn fit 死循环，故以 GMM 落地，HMM 留 Linux/macOS TODO）。不选深度端到端（信噪比低、样本少、过拟合重、ROI 负）。
- Conformal 校准：XGB/LGB 的 `predict_proba` 在金融上普遍过度自信；Conformal 在任意基础模型上保证覆盖率，样本外仍成立，几乎无成本。输出概率+分位区间而非点预测，更诚实也更实用。
- 不选纯 LSTM/Transformer：金融多变量时序上长期跑不过调好的树模型；留作未来可选。

**训练协议**：purged walk-forward + embargo；滚动再训（按月/季）；北向规则变更日分段。禁止随机 K 折（会 look-ahead）。

**特征权重预期**：资金面/热钱（主力净流入/龙虎榜接力/封板资金/北向/融资）预期为 `short_sector` 的 top SHAP 特征组（A 股短线资金驱动属性）；权重由模型学习、不手工设定，但验证时该组应排名靠前，否则查特征时效/口径而非盲信模型。

**期望管理**：样本外 short_sector 胜率现实区间 51%-55%；报出 60%+ 几乎必是 leakage/过拟合，先查 bug 而非庆祝。

**依赖接口**：特征抽取走 `feature_interface.py`，S018 注册表供给；S008 数据层迁移时只换实现，模型不动。

**多段级联 + 半自动化定位**：预测按 A 股信息到达分四段——S1(T-1 收盘后)→S2(T 开盘前)→S3(T 竞价 9:15-9:25) **自动级联重打分**（同模型、按 `availability_offset` 解锁特征子集、概率级联不覆盖、版本化快照+演进历史）；S3 收敛后候选已少量，交用户人工研判。**S4 盘中不做自动信号推送**，输出"盘中研判框架"（量比突变/分时量价/封板资金变化/龙头实时属性，看什么+怎么判）作教育性指引。定位为**半自动化交易助手**：系统做重活（筛选/打分/概率/研判框架），用户做决策——契合 §1"不代用户决策"。

---

## 6. 验收标准

- [ ] A1 四头目录结构建立，short_sector 完整实现（标签/训练/评估/服务），其余三头有空实现+接口预留
- [ ] A2 short_sector 标签=申万一级板块指数未来1-3日累计收益>0；可展示取数时点/口径，可复算
- [ ] A3 模型栈 LightGBM+CatBoost+GMM+Conformal 四层接通；输出=上涨概率+收益率10/50/90分位区间
- [ ] A4 训练用 purged walk-forward+embargo+滚动再训；北向规则变更日分段；无 look-ahead
- [ ] A5 样本外胜率/混淆矩阵/校准曲线/衰减曲线可产出；关键指标可经 `financial_rigor.py` 复算
- [ ] A6 `/api/prediction/short_sector` 返回 Top 板块概率+区间+免责声明；MCP 工具同步
- [ ] A7 `/prediction` 前端页可看概率/区间/历史胜率/衰减；卡片挂免责声明
- [ ] A8 模型权重/特征快照存 `~/.vibe-research/predict/`，不进 git
- [ ] A9 固定种子/版本/超参/特征列表，全流程可复现
- [ ] A10 样本外 short_sector 胜率如实报告（预期 51%-55%）；若 >60% 触发 leakage 自查并记录

---

## 7. 合规自查（按 CLAUDE.md §1 弱合规 2026-07-30；私人助理定位）

**仪式类（已降为风险提醒，非硬门槛）**：
- [ ] 预测输出挂轻量风险提醒「历史统计特征，市场有风险」，不强制「不构成投资建议」墙
- [ ] 可给方向性研判/买卖时机/收益预期/操作建议，不承诺确定性保证（给概率与区间；用户即决策者，半自动化）
- [ ] 涨停四池/连板股榜可如实呈现个股 code/name；Emotion 聚合指标不含个股名属设计选择
- [ ] `chat.SYSTEM_PROMPT` 可给方向性研判，不承诺确定性收益
- [ ] S4 盘中可出研判框架与操作建议，用户最终决策；是否自动推送由 `positioning-semi-automated-assistant` 定位决定

**工程底线（保留，保护用户自身的钱与数据）**：
- [ ] 判断可复现/不臆造/不心算（公开数据+固定规则，`financial_rigor.py`/`report_audit.py` 验算）
- [ ] 模型产物（权重/快照）存 VR_DATA_DIR，不进 git/不上传
- [ ] 新增东财端点走 `em_get()` 限流

---

## 8. 测试计划

- 单测：标签构造、purged walk-forward 切分、Conformal 覆盖率、GMM 体制识别纯函数 ≥80% 覆盖
- 回归：录 10 只代表板块/个股特征快照，训练/预测回放比对
- 集成：`pytest -m "not live"`；live 冒烟（:8900 `/api/prediction/short_sector` + MCP 工具实测）
- 数据验算：胜率/校准指标跑 `financial_rigor.py` 复算
- 前端：vitest 关键页快照

---

## 9. 风险与回滚

- 🔴 样本外胜率坍回 50%：先查 leakage/分段/特征时效，非过拟合即调权/加正则；如实记录不美化
- 🟠 S008 数据层迁移：特征接口收口后只换实现；模型权重可保留
- 🟠 北向规则变更：分段建模，禁跨段拟合
- 🟠 重依赖（lightgbm/catboost/hmmlearn/mapie）：Windows `.venv` 安装可能需编译轮子；预装验证
- 回滚：四头解耦，单头失败可单独回切；预测栈与 S002/S005 漏斗独立，不影响现有筛选功能
