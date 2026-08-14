# 数据源可用性记录

> 回测/开发过程中探测到的数据源可用性记录。供后续开发、回测、数据补全参考。
> 维护规则：每次探测到新数据源（可用或不可用），追加到对应表格。

## 日K线源

| 源 | 端点 | 状态 | 限制 | 字段 | 备注 |
|---|---|---|---|---|---|
| 新浪财经 | money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData | 可用 | 无明显限流，1.5s 间隔安全 | date/open/high/low/close/volume | 已集成 data/sources/sina.py，注册在 kline_resolver。raw 不复权。datalen 上限 1023 |
| 东财 push2his | push2his.eastmoney.com/api/qt/stock/kline/get | 限流 | 首次可用，后续 Remote end closed | date/open/close/high/low/vol/amount/amplitude/pct_change/turnover | 含成交额+换手率，字段最全 |
| mootdx (TDX) | 通达信协议 | 不可用 | 连接成功但返回空 DataFrame | 同 mootdx 标准字段 | 2026-08-13 实测：bestip 不可用，bars() 返空。astock.kline 直接走此源，绕过 kline_resolver 多源回退 |
| 百度 | 百度股市通 | 未测试 | 依赖网络 | 百度 kline 标准字段 | 已集成 data/sources/baidu.py，kline_resolver 首选源（qfq 复权） |
| akshare | akshare 库 | 未测试 | 依赖 akshare 安装 | akshare 标准字段 | 已集成 data/sources/akshare_src.py，kline_resolver 末位回退 |

## 龙虎榜/资金流源

| 源 | 端点 | 状态 | 限制 | 字段 | 备注 |
|---|---|---|---|---|---|
| 东财 datacenter | datacenter-web.eastmoney.com/api/data/v1/get | 可用（curl 直连） | em_get 熔断器可能阻断；curl 直连可绕过 | SECURITY_CODE/TRADE_DATE/OPERATEDEPT_NAME/NET 等 | 已集成 astock.eastmoney_datacenter()。RPT_BILLBOARD_DAILYDETAILSBUY/SELL 取龙虎榜买卖席位明细 |

## 当日行情源

| 源 | 端点 | 状态 | 限制 | 字段 | 备注 |
|---|---|---|---|---|---|
| 腾讯财经 | qt.gtimg.cn | 可用 | 批量 50，限流友好 | name/price/change_pct/turnover_rate/vol_ratio/amount/amplitude/limit_up/down/float_market_cap | 已集成 data/sources/tencent.py，activity.py 当日路径使用 |

## 已知接线问题

### astock.kline 绕过多源解析器

astock.kline（来自 data/sources/mootdx_src.py）直接走 mootdx，不经过 kline_resolver 的多源回退链（baidu->sina->mootdx->akshare）。mootdx 不可用时返空，不会回退到新浪/百度。

影响：candidate_funnel/sources/activity.py 的 _fetch_activity_from_kline 调 astock.kline 取历史日K，mootdx 不可用则 vol_ratio/amount/turnover 全部 None，R2 以"换手未取得"为由剔除全部候选。

建议：activity.py 改用 astock.kline_multi（多源解析器），或在 astock.kline 内部走 kline_resolver 回退。属 medium 级改动。（已于 2026-08-14 修复）

### 其他 astock.kline 直调位置（待统一迁移）

以下 12 处也直接调 astock.kline（不走 kline_resolver 多源回退），mootdx 不可用时有同样风险：
- limitup_screener/kline_rebuild.py:121
- risk_models.py:335,357,381
- strategies/position_advisor_v2.py:162
- backfill_prediction_ledger.py:71
- routers/stock_data.py:193,227
- routers/sentiment_weather.py:1133
- prediction_verify.py:36

建议：统一迁移到 astock.kline_multi，属 large 级 spec。

## 回测数据源使用记录

| 回测 | 日期 | 数据源 | 样本量 | 结论 |
|---|---|---|---|---|
| 量比/成交额过滤 | 2026-08-13 | 新浪日K | 74 | 不加过滤胜率最优（73%），量比/成交额过滤均降低胜率 |
| 游资净流出过滤 | 2026-08-13 | 新浪日K + 东财 datacenter 龙虎榜 | 30 上榜 | 游资净流出组胜率最高（83.3%），不能作为负向过滤 |

## BaoStock（免费独立源，2026-08-14 实测确认）

| 端点 | 状态 | 字段 | 备注 |
|---|---|---|---|
| query_history_k_data_plus | 可用 | date/open/high/low/close/volume/amount/turn/pctChg | adjustflag=2=前复权，解决除权污染 |
| query_stock_industry | 可用 | code/code_name/industry/industryClassification | 5540条，证监会行业分类 |
| 登录 | 免费 | login()无需token | 独立数据库，不限流不封IP |

**S066 Phase 0a 回填首选源**。一个库解决：qfq K线 + 换手率 + 涨跌幅 + 成交额 + 行业分类 + 涨停检测。
