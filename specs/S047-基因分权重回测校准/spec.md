# Spec: S047 — 基因分权重口径回测校准（22cae04 推迟项兑现）

> 状态：已实现（2026-08-10，阶段 A 证据 + 阶段 B 权重改稿与历史复算）——full 权重改 40/25/25/0/10；eastmoney_live 历史 2023 行复算（345 变更，qualify 46，备份+校验）；rebuild 行不碰。见 证据报告.md §6 执行记录
> 级别：**medium**（纯研究分析 + 既有 backtest_lite 机制复用；阶段 A 不改任何生产权重，产出证据与改稿提案；改权重另立阶段 B）
> 关联：`../S041-回测定时任务与趋势看板/spec.md`（回测基础设施）、`../S043-次日溢价率单因子分析/spec.md`（`_calc_factor_percentile_analysis` 泛化分位）、`backend/backtest_lite.py`、`backend/limitup_screener/models.py`（权重口径）
> 缘起：`22cae04`/`556c6e4` grill 结论——强封板市况下「炸板后溢价」恒 0 占 15% 权重 → total_score 上限 ~52，阈值 60 清空候选池；阈值 60→50 为止血，**权重口径待回测后改稿**。S040（149 交易日基因数据）+ S041（回测）落地后前提已备。

## 1. 问题 / 目标

`GENE_QUALIFY_THRESHOLD` 与 total_score 权重是拍定的，从未用真实次日收益验证：
1. total_score 是否真有预测力（高分组 hit_rate/avg_return 是否更高）？
2. 五个因子（次日溢价率/封板率/红盘率/炸板后溢价/频次分）各自预测力如何？
3. 「炸板后溢价」15% 权重在强封板市况恒 0 贡献——是否该降权/改口径？
4. 阈值 50 是否合适（50 上下分组的 hit_rate 差异）？

**目标**（阶段 A，仅研究）：跑全量回测（2026-01-05~2026-08-10，gene_scores.db 149 交易日 5783 候选，kline 走 mootdx 不碰东财），产出分桶证据表 + 校准提案。**不改生产代码**。

## 2. 需求清单

- [x] R1 全量 scatter 生成脚本（149 日；mootdx kline 按股缓存；产物落 `.scratch/s047-gene-calibration/scatter.json`）
- [x] R2 total_score 分位证据：既有三档（0-60/60-75/75-100）+ 阈值区细档（<45/45-50/50-55/55-60/60+）
- [x] R3 五因子各自分位证据（复用 S043 `_calc_factor_percentile_analysis`）
- [x] R4 证据报告 + 校准提案（改权重/改阈值/不改——据数据说话；数值经 `~/tools/financial_rigor.py` 或脚本复算，禁止心算）

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `.scratch/s047-gene-calibration/`（新，不入 git 生产路径） | 运行脚本 + scatter.json + 证据表 |
| `backend/backtest_lite.py` | **不改**（复用 generate_scatter_data / 分位函数） |
| `backend/limitup_screener/models.py` | **阶段 A 不改**（阶段 B 据提案另立） |

## 4. 验收标准

- [x] A1 scatter 覆盖 ≥140 交易日、样本 ≥5000（缺 kline 的样本剔除并计数）
- [x] A2 total_score 细档分位表含 count/avg_return/hit_rate
- [x] A3 五因子分位表同上
- [x] A4 结论可复现：脚本 + scatter.json 重跑数字一致
- [x] A5 合规：客观历史统计特征；不碰东财（mootdx kline）；无私有数据；无臆造

## 5. 合规与工程底线自查

- 回测只读 gene_scores.db + mootdx K 线，**不碰东财**（今日 push2 限流史，全程无 em 调用）✓
- 统计结果客观复算（脚本产出，非心算）；缺数据剔除计数不臆造 ✓
- 阶段 A 无方向性输出变更（不改生产权重/阈值/展示）✓

---

# 阶段 B — 权重改稿 + 历史复算（grill 锁定，2026-08-10）

> 用户决策：按新权重**复算历史**（推翻"只前向生效"建议）；经 grill 锁定边界。
> grill 锁定：①复算仅限 eastmoney_live 行（rebuild 行无替代权重证据，不动，维持 40/40/20）；
> ②qualify/high_gene 同步重算；③winrate_records 不动（结算快照语义=结算时刻所见，接受双体制混杂并标注）；
> ④备份+因子列逐行不变校验（私有数据改写可逆可审计）；⑤GENE_HIGH_THRESHOLD=75 恒不可达（死字段）本轮不动只标注。

## 6. 阶段 B 需求清单

- [x] B1 `calc_total_score` "full" 权重改稿：次日溢价率 40% / 红盘率 25% / 封板率 25% / 炸板后溢价 0% / 涨停频次 10%（据阶段 A 证据：溢价最强单调、炸板 live 零方差）
- [x] B2 一次性复算脚本：仅 `data_source='eastmoney_live'` 行，从存储因子列重算 total_score + qualify + high_gene；rebuild 行不碰
- [x] B3 复算前备份 `gene_scores.db.bak-*`（.gitignore 已含 *.db.bak）；脚本校验因子列逐行不变、行数不变
- [x] B4 测试：新权重纯函数测试（炸板因子不再影响总分）+ 临时 DB 复算 dry-run 测试

## 7. 阶段 B 验收标准

- [x] A-B1 `calc_total_score` 新权重数值正确（炸板后溢价任意值不影响总分）
- [x] A-B2 复算后 live 行 total_score/qualify/high_gene 与纯函数重算一致；rebuild 行逐行不变
- [x] A-B3 因子列复算前后逐行相等；行数不变；备份文件存在
- [x] A-B4 `pytest -m "not live"` 全过
- [x] A-B5 合规：复算为纯算术重导（因子不变，非臆造）；winrate/工作流历史不改写；无私有数据出 `.vibe-research/`
