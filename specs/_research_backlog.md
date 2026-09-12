# 调研定论追踪表（Research Backlog）

> 所有"跑过调研 workflow 有定论、但没落地实现"的清单。每周头脑风暴过一遍推进。
> 防止调研结论飘在对话里丢失（流程缺口：调研→定论→但没"定论转 spec"那步）。

## 流程要求（SDD §0 补强）
调研 workflow 跑完有定论的 → **立刻**落 spec 草案（哪怕只问题/目标 + 定论摘要）+ 进本表 + MILESTONES，不留在对话里。spec→plan→tasks→实现闭环不断在"定论→spec"这步。

---

## 待落地（有定论，未 spec/未实现）

| 编号 | 调研 | 定论 | 状态 | 下一步 |
|---|---|---|---|---|
| RB-1 | scheduler-research（换框架/服务解耦） | **保持自实现+补强**（进程死非框架问题→healthchecks.io 解；Redis 对个人 Mac 过重 YAGNI；APScheduler 唯一增量 misfire 不痛；3 痛点自建~150 行零依赖） | ✅ 已落 spec S190（定论+补强方案 R3-R5） | 实现 S190 R3-R5（healthcheck seed / retry 接线 / depends_on 门控） |
| RB-2 | cloud-resources healthchecks.io | 免费外部心跳防 cron 静默死 | ⚠️ executor 已建（S188 data_ops.healthcheck_ping），未 seed | S190 R3 seed healthcheck_ping cron `0 * * * *`（~10 行） |
| RB-3 | data-infrastructure 全量拉取 | 每日盘后全量拉各源当日数据（stoke 研报/新闻/归因 + mootdx 分笔）沉淀 datalake + 回放引擎 | ✅ 已落 spec S191（草案） | plan→tasks→实现 daily_full_pull + datalake/replay.py |
| RB-4 | w8e2forp7 任务级重试接线 | tenacity network_retry 装饰器已写（commit 2282503）零调用方 | ⚠️ 装饰器落地未接线 | S190 R4 接线到 kline_refresh/ofi_collect（~15 行 @network_retry） |
| RB-5 | 盘后链依赖门控 | depends_on + blocked + 迟到追赶治静默陈旧数据 | ⚠️ S190 R5 落 spec（字段+迁移+_tick 门控） | 实现 S190 R5（models 加 depends_on + db 迁移 + seed 盘后链 depends_on） |
| RB-6 | gap 250 天跨 regime 复验 | 60+120 天 net 负，250 天定论性复验 | 🔄 进行中（172 天先跑，cache 不够 250） | 扩 baostock cache 回溯到 250 天 → 跑 gap 250 |
| RB-7 | breakout 1.72x 标记清理 | memory 6 处已改 naive 1.36x，可能残留 | ⚠️ 部分 | grep 残留 1.72x/PnL 0.486/0.523 标记 → 清理 |
| RB-8 | r3-enforce 接线 | 等 forward_test 到 30 天（~9-25）触发评估 | ❌ 等 30 天 | forward_test 监控 endpoint 已落（S188 P0 #3），到 30 天评估 |
| RB-9 | 每周全局优化头脑风暴 cron 触发器 | 每周一次自动触发 | ❌ 没接 cron | 手动触发为主，cron 触发器待接 |

## 已落地（参考）

| 调研 | 落地 | commit/spec |
|---|---|---|
| 涨停首板 60 日回补多源调研 | baostock/ths/hithink fallback | `data-source-capabilities` memory + 多处 |
| 世纪大辩论 w2j5srlf 10 视角 | S159-S166 部分（S162/163/164 done） | spec |
| w8e2forp7 retry 装饰器 | `scheduler/retry.py` | 2282503（但零调用方见 RB-4） |
| S185 turso 数据湖 | `turso_sync.py` sync 4 表 | d2b25f4 |
| S184 kline_refresh 性能 | 数据就绪预检 + cron 17:15 | 91fd5fd |

## 弃置（有定论不做）

| 调研 | 定论 | 原因 |
|---|---|---|
| r3-enforce + ash-mcp B 臂 | 搁置 | 用户 2026-09-10 决策（`deferred-specs-shelved` memory） |
