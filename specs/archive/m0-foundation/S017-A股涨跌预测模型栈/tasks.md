# Tasks: S017 — 预测模型栈

> 关联：`spec.md` / `plan.md`。依赖 S018 特征接口（T1 先用 stub 对接）。
> 起步范围：仅 `short_sector` 头完整实现，其余三头空实现+接口预留。
>
> **进度状态（2026-07-30）**：后端 T1-T10 落地，全离线套件 658 passed。
> Windows 适配（见 plan.md §2.3 偏离记录）：lightgbm/hmmlearn 在本机 hang，
> 经用户决策用 HistGB+CatBoost / GaussianMixture / mapie 替代；Linux/macOS
> 走 LGB+HMM 的 TODO 保留（跨平台部署时按 platform 切换）。

## 阶段 0：前置验证
- [x] T0 依赖安装验证：catboost/scikit-learn/mapie/shap/boruta 装妥；lightgbm(4.7)/hmmlearn(0.3.3) Windows 不可用（OSError/hang，与 numpy 无关）→ 用 HistGB/GaussianMixture 替代。
- [x] T0b 缺失数据源可行性：A50 夜盘(secid 100.XIN9)可达；美债10Y=DGS10、DXY→DTWEXBGS（Fred，S019 已接）。

## 阶段 1：骨架与标签
- [x] T1 `predict/` 包骨架 + `feature_interface.py` 接口定义（stub 返回空 DataFrame，S008 接 live）+ 单测。
- [x] T2 `labels.py` 标签构造（过去 horizon 收益>0 二分类，无 lookahead）+ 单测。
- [x] T3 `heads/base.py` ABC + `heads/short_sector.py` 完整接口 + 三头空实现(NotImplementedError)+ 单测。

## 阶段 2：模型栈
- [x] T4 `models/ensemble.py` SoftVoteEnsemble（HistGB+CatBoost 软投票，lightgbm 降级 HistGB）+ 单测。
- [x] T5 `models/calibration.py` ConformalCalibrator（mapie 1.4.1 SplitConformalClassifier confidence_level）+ 单测。
- [x] T6 `models/regime.py` GaussianMixtureRegimeSwitcher（牛/震荡/熊；HMM Linux/macOS TODO）+ 单测。

## 阶段 3：训练与评估
- [x] T7 `train.py` purged walk-forward+embargo+purge（无随机 K 折）+ segment_index(2024-08-19) + roll_retrain（禁跨段拟合）+ train_short_sector 编排 + 单测 15 项。
- [x] T8 `evaluate.py` win_rate/confusion/calibration_curve/decay_curve（纯函数手动 AUC 可复算）+ leakage_flag（>60% 触发自查）+ evaluate_short_sector 编排 + 单测 15 项。

## 阶段 4：级联预测与服务
- [x] T9 `predict.py` predict_stage→Snapshot + cascade_store（项目内 `.vibe-research/`，不进 git/不落 home）+ load_cascade（S1→S4 排序）+ 单测 10 项。quantiles/shap 留空 TODO（回归头/live SHAP，禁止臆造）。
- [x] T10 `routers/prediction.py`：`GET /api/prediction/{head}?stage=s1|s2|s3` + `GET /api/prediction/intraday-framework`（教育性、无交易指令词）+ 免责声明 + 单测 7 项。
- [x] T11 `chat.TOOLS` 加 `prediction_short_sector` / `prediction_intraday_framework` 工具（lazy import 路由 sync helper，MCP 自动同步）+ 单测 5 项。

## 阶段 5：前端工作流交互
- [x] T12 `frontend/src/lib/prediction.ts` 类型 + fetch（保留全信封含 disclaimer）+ 免责墙 opt-in。无 TanStack Query（项目未装，沿用 plain fetch 模式）。
- [x] T13 `pages/Prediction.tsx` 内联 DisclaimerWall/StageTimeline/ProbabilityEvolution/IntradayFramework 组件（一文件聚合，非 6 散文件）。
- [x] T14 `router.tsx` 加 `/prediction` 路由 + Layout 加「预测工作台」导航。tsc --noEmit 通过。

## 阶段 6：集成与验收
- [x] T15 `pytest -m "not live"` 663 passed + live 冒烟通过：:8900 `GET /api/prediction/intraday-framework` 与 `GET /api/prediction/short_sector?stage=s1` 均返回免责声明、无违禁词、no_snapshot 如实呈现。前端 tsc 通过。
- [ ] T16 样本外 short_sector 胜率如实报告（预期 51%-55%）；>60% 触发 leakage 自查（evaluate.py 已内建 leakage_flag）。**依赖 S008 live 取数后才有真实样本外**。
- [x] T17 合规自查：免责墙(opt-in localStorage)/无交易按钮/S4 教育性(无信号无指令词)/快照项目内不入 git/新端点走 em_get(预测端点只读快照不触网)。单测 + live 冒烟双重验证。

## 依赖图（关键路径）
T0 → T1 → T3 → T7 → T9 → T10 → T12 → T13 → T14 → T15
                  ↑T4,T5,T6 ↗   ↑T11(chat 工具)
T16/T17 真实样本外验收依赖 S008 live 取数落地。
