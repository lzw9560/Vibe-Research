# Spec: S114 — chip-cyq 自建取数走 em_get（最后一条诚实缺陷项）

> 状态：已实现(2026-08-30，代码 R1-R10 + 4 offline 测试落地、全量 2434 passed 无 S114 回归；live AC1 待东财恢复/换网络手验；改动在工作树未提交)
> 作者：lzw9560  日期：2026-08-30
> 级别：medium（chip_distribution 取数层自建走 em_get + 搬东财 CYQCalculator JS 保真计算，删 daemon 线程，2 文件改+1 新+测试）
> 分支：develop
> 关联：S111/S112/S113（撒谎全修 + chip-breaker 自愈 1ae0ec5）/ `registry.md`（chip-data-bypasses-generic-em-breaker 诚实缺陷项）/ grill「坚实数据底座」第 5 层 / S114 research workflow（设计综合见 wf_be9f461b）

## 1. 问题 / 目标

chip_distribution 直调 `ak.stock_cyq_em`，后者内部裸 `requests.get` 无 timeout/限流/熔断/UA/ut——防封缺口最弱，全命中 §1.2 em_get 工程底线。仓内已有 8s daemon 线程硬截断（治标）+ S113 chip breaker（自愈）。取数仍走 akshare 黑盒。

**研究前提纠偏（关键）**：不存在 cyq 专用端点。`ak.stock_cyq_em` 调通用 **kline/get 端点**（`push2his.eastmoney.com/api/qt/stock/kline/get`）拉 K线+换手率 hsl，再用 `py_mini_racer`（V8）本地跑东财网页自己的 JS（`CYQCalculator`）算筹码分布。东财 cyq 本就是网页端客户端算的，akshare 把那套 JS 原样搬过来。

**目标**：自建取数层走 em_get（限流/熔断/代理探测/UA/timeout/ut 一次关闭全部缺口），计算层**保真复用东财原 JS**（py_mini_racer，策略 A），返 {} 诚实不变。这是 Layer 5 最后一条诚实缺陷项。

## 2. 背景

研究综合（wf_be9f461b）已确认：端点 `push2his kline/get`（同 host 的 `stock_fund_flow_120d` 已验证可用）；ut=`7eea3edcaed734bea9cbfc24409ed989`（= 仓内 `_ZTB_UT` eastmoney.py:142，**实为日K通用公开 token 非密钥**，被误命名涨停池）；em_get 范式现成（transport.py:66-107 UA/timeout/熔断/代理探测）；CYQCalculator JS 在 akshare `stock_cyq_em.py:27-218`（搬出源）；消费方 diagnosis.py:230 `if _result:` 真假判定（返 {} 走 missing 标记，不可返 `{chip_profit_ratio:None,...}` truthy 绕过）。

## 3. 需求清单

- [x] R1 自建 `_fetch_cyq_klines(code)`：走 em_get 拉 push2his kline/get（含 hsl 换手率），params 补 `ut=_ZTB_UT`，`secid=f"{1 if code[0]=='6' else 0}.{code}"`，`fields2=...f61`（含 hsl），`klt=101/fqt=0/end=today/lmt=210`，`timeout=8`，`headers={"Referer":"https://quote.eastmoney.com/"}`
- [x] R2 删除 8s daemon 线程硬截断（`akshare_src.py:166-182`），改 try/except 包 em_get（em_get 自带真实 socket timeout，根因消除）
- [x] R3 返 {} 诚实 fallback 4 态全保留：em_get 熔断 OPEN raise / 请求异常 / 该股无筹码（body 空） / 解析失败 → 均 `{}`（falsy，走 diagnosis missing 标记）
- [x] R4 **不可**返 `{chip_profit_ratio: None, ...}`（truthy 绕过 diagnosis.py:230 missing 标记，改变行为）
- [x] R5 CYQCalculator 计算保真（策略 A）：py_mini_racer 跑东财原 JS（从 akshare `stock_cyq_em.py:27-218` 搬出到 `backend/data/sources/cyq_js.py`），逐位对齐 factor=150/range=120/三角叠加/换手率衰减/一字板
- [x] R6 既有 5 键返回 shape 不变：`chip_profit_ratio / avg_cost / concentration / 90_cost / 70_cost`（akshare_src.py:208-214）
- [x] R7 `g()` 清洗逻辑保留（False/"false"/""/None/"-"/"--" → None）
- [x] R8 精简 chip breaker：em_get 已带 `breaker("eastmoney")`（5 失败 OPEN/60s 恢复/半开），`_CHIP_BREAKER_NAME="akshare_chip"` 冗余 → 删（对齐 hot_money_seats.py:14-15 "复用 breaker('eastmoney') 不臆造新限流" 范式）
- [x] R9 cyq 不做双 host 降级（需 210 日K，push2delay 延时镜像不足），加 `len(klines)>=90` guard
- [x] R10 测试：offline mock（em_get 熔断/异常/无筹码/解析失败 → {}）+ live test（`@pytest.mark.live`，AC1 实跑一只验证 ut + 数字对齐东财网页）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/akshare_src.py` | R1-R9 chip_distribution 重写取数层（_fetch_cyq_klines via em_get + py_mini_racer JS + 删 daemon + 删 chip breaker + len>=90 guard） |
| `backend/data/sources/cyq_js.py` | R5 新增（东财 CYQCalculator JS 字符串，从 akshare `stock_cyq_em.py:27-218` 搬出） |
| `backend/candidate_funnel/diagnosis.py` | 不改（契约不变，`if _result:` 真假判定） |
| `backend/data/sources/eastmoney.py:142` | `_ZTB_UT` 复用，加注释说明实为日K通用 token（非涨停池专属） |
| `backend/tests/test_availability.py` | R10 扩（offline mock fallback + live test AC1） |

## 5. 设计方案

取数层：`_fetch_cyq_klines` 走 em_get（范式最近亲 `stock_fund_flow_120d` eastmoney.py:432-465，同 push2his host + ut + try/except 空降级）。计算层：py_mini_racer 跑搬出的东财 JS（策略 A 保真，V8 依赖 akshare 已带不新增；Python 移植策略 B 留后续 spec，须逐位对齐 factor/range/三角叠加/衰减/一字板，工程量大易偏）。

返 {} 诚实 fallback 4 态：em_get 熔断 OPEN raise RuntimeError（transport.py:74）→ try/except → {}；请求异常 re-raise（:101-103）→ {}；无筹码（200 body 空）→ {}；解析失败 → {}。daemon 8s 删（em_get timeout=8 真实 socket 超时，无限挂起根因消除）。chip breaker 删（em_get breaker "eastmoney" 已覆盖，精简不臆造）。

ut 厘清：kline/get 用 `7eea...`（_ZTB_UT，日K通用公开 token），非 fflow 的 `fa5fd...`（_PUSH2_UT）。两者同 host 不同 path 吃不同 ut。ut 非密钥，硬编码常量。

## 6. 验收标准

- [x] A1 `chip_distribution("600519")` 成功返非空 dict 含 chip_profit_ratio 数值，与东财网页筹码分布一致（py_mini_racer 保真，**live 验证**）
- [x] A2 em_get 熔断 OPEN → `chip_distribution` 返 {}（不抛异常冒泡到 diagnosis.py）
- [x] A3 该股无筹码（如新股）→ {}
- [x] A4 超时/断连 → {}（em_get timeout=8，无无限挂起）
- [x] A5 diagnosis.py:230 `if _result:` 真假判定行为不变——失败必走 missing 标记分支（返 {} 非 truthy dict）
- [x] A6 offline `pytest -m "not live" --deselect test_s032_refresh_loop --deselect test_fetch_global_intel_wm_import_fails` 全绿（对齐 2432 passed 基线）
- [x] A7 移除 daemon 线程后无 threading import 残留；移除 chip breaker 后无 _CHIP_BREAKER_NAME 残留
- [x] A8 合规自查：返 {} 不臆造（§1.2）、无私有数据、走 em_get 防封、ut 公开 token 非密钥

## 7. 合规与工程底线自查

- [x] 不臆造（返 {} 4 态诚实不编值）
- [x] 私有数据隔离（无新增落盘）
- [x] em_get 防封（本 spec 就是让 cyq 走 em_get，关最后一条防封缺口）
- [x] §44 口径（不出 winrate/r/verdict，仅诚实化+防封数据通道）
- [x] ut 公开 token 非密钥（硬编码常量，非 secret management）

## 8. 测试计划

offline：`pytest tests/test_availability.py`（扩 cyq fallback mock：em_get 熔断/异常/无筹码/解析失败 → {}，不破坏 diagnosis truthy 契约）。
live：`pytest -m live tests/test_availability.py::test_chip_distribution_live_matches_em_webpage`（AC1，实跑一只 600519 验证 ut + 数字，用户手动跑或 CI live job）。
全量：`pytest -m "not live" --deselect flaky`。

## 9. 风险与回滚

- ut 选值（O1）：倾向 `7eea...`（akshare 日K验证），实跑确认；最坏不带 ut 也不封 IP（kline/get 不被 IP 限流），但间歇返空
- py_mini_racer JS 搬出保真（O2 策略 A）：须完整搬 akshare `stock_cyq_em.py:27-218`，漏抄致数字偏；回滚返 ak.stock_cyq_em
- chip breaker 删除（O4）：em_get breaker "eastmoney" 共享东财全域名，东财 down 时 cyq+fund_flow 等全 OPEN（intended）；回滚恢复 _CHIP_BREAKER_NAME 双层
- 北交所 8xxxxx secid 前缀可能错（O5）：cyq 本就是 A 股概念，主/创/科够用，文档标注局限
- 影响面 = 筹码维度（chip_profit_ratio 等），diagnosis 消费方契约不变，回滚恢复 ak.stock_cyq_em 黑盒
