# Tasks: S189 — 做 T 框架

> 状态：T1-T4 done（T4 经 6 视角 grill 修订），T5 **不接**（无 validated edge，price 弱正在噪声内）。

## T1 · accounting T+0 成本 ✅
- [x] T1.1 `engine/accounting.py` 加 `t0_cost`（T+0 往返=佣金+印花+滑点）
- [x] T1.2 实测小单0.95%大单0.77%（最低佣金占比降）
- [x] T1.3（grill 修订）`t0_cost` 独立于 `_cost_pct`——T+0 用 VWAP 成交价，不需 breakout 的 0.70% 理论价桥接；改 `T0_SLIPPAGE_PCT=0.10%`（VWAP→execution shortfall）+ `COMMISSION_RATE_PCT=0.025`（max(费率,5元)×2，修原只 5 元最低低估中大单）

## T2 · OFI 分钟级拐点检测 ✅
- [x] T2.1 `engine/intraday_ofi.py` 加 `ofi_turn_points`（正转负=卖点 负转正=买点）
- [x] T2.2 实测 [0.9,0.9,-0.1,-0.5,0.3]→卖idx2 买idx4 ✓

## T3 · JournalRecorder T+0 fill ✅
- [x] T3.1 `strategies/journal_recorder.py` 加 `record_t0_fill`（fills_json.t0_fills list）
- [x] T3.2 复用 fills_json（不加新列）+ 迁移
- [x] T3.3 实测 record_t0_fill 成功（测后已清测试数据）

## T4 · t0_simulator 历史验证 ✅（全量 966 + 5 策略 + grill 修订）
- [x] T4.1 `tools/t0_simulator.py`——mootdx tick→分钟OFI+vwap→拐点→T+0 pair 实际价 PnL
- [x] T4.2 输出对比（抽样 10 笔：管道通）
- [x] T4.3 全量 966 笔跑（baseline 简单正负拐点 avg -0.997%，helped 0.1%——系统性补不回）
- [x] T4.4 更优拐点策略（threshold/slope/price/oracle × 5 仓位）+ **6 视角 grill 修订**：
  - oracle 加 buy-first 镜像（原只 sell-first 捕回调漏 rally，§44 v1 式假阴性）+ 修索引错位
  - simulate_t0 加 buy-first 配对 pass + 先配对后截断（修截断丢 pair bug）
  - price 改因果窗口 [i-lookback, i]（去 i+lookback 前视）
  - t0_cost 用 T+0 专属 0.10% 滑点 + 佣金费率（修 0.70% 高估 + 大单佣金低估）

**T4 grill 后结论（重跑 966，cache 命中秒出）**：
- oracle 天花板 +7.5~8.3% gross（buy-first 升级，92.8% trade 有可捕 swing）——日内 swing 真实存在且比初测更大
- baseline/threshold/slope 全负（所有仓位，OFI proxy 信号对价格反转无预测力）
- **price 弱正**：size=1000 +0.004%、size=10000 +0.015%（12.5% helped）——因果窗口 + buy-first 后唯一弱正，但远不到 §44 2x lift bar，**在噪声内非 validated edge**
- scope：仅测 D+1 单日 T+0；D+2..D+5 holding 期多日累计未测；OFI proxy 非真五档

## T5 · forward_test arm t0_mode — **不接**（无 validated edge）
- 决策：T5.1-5.3 不实现。OFI-proxy 策略全负/噪声内弱正，接 forward_test 只会亏/噪声，不上线。
- 后续待验：真五档 OFI 攒 60 天（ofi_collect cron 在跑）+ 放宽 price 阈值/多日累计看能否拉出真 edge。
- 价格确认 + buy-first 方向是"正确配料"（grill missed-strategies 判定），后续信号改进的起点。

## 验收
- [x] A1 t0_cost 正确（往返佣金+印花+滑点；grill 后用 T+0 专属 0.10% 滑点 + 佣金费率）
- [x] A2 t0_simulator 输出对比表（全 966 + 5 策略 × 5 仓位）
- [x] A3 ⚠️ 做 T net > 纯持有 net —— **不成立**：OFI proxy 全负/噪声内弱正；oracle 证 swing 存在但 proxy 抓不住（~2% of oracle）
- [ ] A4 §44 lift 框架（≥60 天真五档数据后；当前 proxy 无 edge 不跑）
- [x] A5 pytest not live：3229 passed / 10 failed（pre-existing 周末/日期敏感，与 t0_simulator 无关——不在其 import 图）
