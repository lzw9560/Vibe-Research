# S212 tasks · S205 4 战法 caller checklist

> TDD：test 先（RED）→ 实现（GREEN）→ 验收

## T0 查 msc 来源
- [ ] T0.1 查 s205_match _msc_* 怎么 get msc dict（market structure code）——grep + read s205_match
- [ ] T0.2 定 msc 来源（新 helper or pattern_scan or None mock）

## T1 caller 核心
- [ ] T1.1 test: caller 参数化战法（main(战法名) 跑指定战法）
- [ ] T1.2 test: picks 从 zt_history + s205_match threshold 命中
- [ ] T1.3 test: compute_obs decimal 口径（gap_ret decimal）
- [ ] T1.4 test: D 日一字板 filter
- [ ] T1.5 实现: tools/s205_strategy_harness.py（picks + match + compute_obs + regime harness + drift fix）

## T2 4 战法 verdict
- [ ] T2.1 跑 ruozhuanqiang verdict
- [ ] T2.2 跑 nzi_fanji verdict
- [ ] T2.3 跑 dixi_longtou verdict
- [ ] T2.4 跑 xingtai_fanbao verdict
- [ ] T2.5 记录 4 战法 verdict（robust/underpowered/falsified）

## T3 验收
- [ ] T3.1 全 test 回归 0 break
- [ ] T3.2 memory 更新（4 战法 verdict + S205 caller）
