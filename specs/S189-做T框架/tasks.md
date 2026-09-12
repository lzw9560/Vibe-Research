# Tasks: S189 — 做 T 框架

> 状态：T1-T4 done，T5 待续（T4 暴露策略有效性问题，先解决再接线）。

## T1 · accounting T+0 成本 ✅
- [x] T1.1 `engine/accounting.py` 加 `t0_cost`（T+0 往返=佣金+印花+滑点，同 _cost_pct 语义）
- [x] T1.2 实测小单0.95%大单0.77%（最低佣金占比降）

## T2 · OFI 分钟级拐点检测 ✅
- [x] T2.1 `engine/intraday_ofi.py` 加 `ofi_turn_points`（正转负=卖点 负转正=买点）
- [x] T2.2 实测 [0.9,0.9,-0.1,-0.5,0.3]→卖idx2 买idx4 ✓

## T3 · JournalRecorder T+0 fill ✅
- [x] T3.1 `strategies/journal_recorder.py` 加 `record_t0_fill`（fills_json.t0_fills list）
- [x] T3.2 复用 fills_json（不加新列）+ 迁移
- [x] T3.3 实测 record_t0_fill 成功（测后已清测试数据）

## T4 · t0_simulator 历史验证 ✅（骨架 done，策略有效性暴露）
- [x] T4.1 `tools/t0_simulator.py`——mootdx tick→分钟OFI+vwap→拐点→T+0 pair 实际价 PnL
- [x] T4.2 输出对比（抽样 10 笔：管道通）
- [ ] T4.3 ⚠️ 全量 966 笔跑（确认简单拐点系统性补不回成本）
- [ ] T4.4 ⚠️ 更优拐点策略（OFI 斜率/阈值 非简单正负，或结合价格序列）

**⚠️ T4 关键发现**：抽样 10 笔 OFI proxy 简单正负拐点做 T 补不回成本 gap（688689 pair -0.746% < t0_cost 0.893%）。管道对但策略有效性存疑——先解决策略再 T5。

## T5 · forward_test arm t0_mode（待续，T4 策略有效后）
- [ ] T5.1 `strategies/forward_test.py` breakout arm 加 `t0_mode=False` 开关
- [ ] T5.2 t0_mode=True 时对每 pick 拉盘中 OFI 模拟 T+0 记 t0_fills
- [ ] T5.3 验收：False 行为不变（纯持有向后兼容），True 时 t0_fills_json 非空

## 验收
- [x] A1 t0_cost 正确（往返佣金+印花）
- [x] A2 t0_simulator 输出对比表（骨架）
- [ ] A3 ⚠️ 做 T net > 纯持有 net（抽样看不成立，需更优策略）
- [ ] A4 §44 lift 框架（≥60 天后）
- [ ] A5 pytest not live 全绿
