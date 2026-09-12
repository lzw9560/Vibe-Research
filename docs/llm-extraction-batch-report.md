# LLM 抽取 Pipeline 批量跑报告

> 日期：2026-09-07
> 脚本：`scripts/llm_extract.py`（规则模式） + `scripts/llm_extract_batch.sh`（批量驱动） + `scripts/llm_extract_dedup.py`（去重）
> 数据源：`eastmoney_reports`（东方财富研报接口，`data/sources/eastmoney.py`）

## 1. 运行参数

| 参数 | 值 |
|---|---|
| 股票范围 | 前 50 只（`10_Reference/investing/stocks/*.md` 字典序，跳过 index） |
| 每只研报条数 | `--limit 2` |
| 抽取模式 | 规则抽取（不调 LLM，LLM key 未配置） |
| 限流间隔 | `sleep 2`/只 |
| 落盘位置 | `10_Reference/investing/inbox/` |
| 文件名前缀 | `{timestamp}-{type}-{name}[-n].md`（时间戳 + 防重名计数器，天然防重） |

## 2. 抽取总数

| 阶段 | 文件数 |
|---|---|
| 抽取产出（原始） | 192 |
| 去重后保留 | **170** |
| 删除重复 | 22 |

50 只股票中 47 只有研报数据（3 只 `000009/000592/000635` 无研报返回，跳过——`eastmoney_reports` 返回空）。覆盖率 47/50 = 94%。

## 3. 类型分布（去重后）

| 实体类型 | 数量 | 占比 | confidence |
|---|---:|---:|---|
| analyst（分析师） | 119 | 70.0% | medium |
| stock（股票） | 47 | 27.6% | high |
| industry（行业） | 4 | 2.4% | medium |
| **合计** | **170** | 100% | — |

说明：
- **analyst 占大头**：研报接口返回 `researcher` 字段（多名逗号分隔），规则按 `研究员 {name}，` 前缀逐名抽取，2 份研报 × 平均 2 名 = 约 4 名/股。
- **stock 47 个**：每只有研报的股票抽 1 个，confidence: high（6 位代码正则，确定性强）。
- **industry 仅 4 个**：研报标题里偶现「xx行业/板块」字样，但组装的抽取文本是「标题+机构+研究员+EPS+PE」，不含行业描述句，故命中率低。LLM 模式或全文化抽取能补这块（待 LLM key 恢复）。
- **concept/metric/event**：本次 0。研报接口无营收/净利/ROE 数值字段（只有 EPS/PE），规则 metric 正则不匹配；concept 同 industry 理由。

## 4. 重复率

| 项 | 值 |
|---|---|
| 原始文件 | 192 |
| 唯一实体键 | 170 |
| 重复键数 | 18 |
| 重复文件数 | 22 |
| 重复率 | 22/192 = **11.5%** |

重复全部为 **analyst**（同一研究员覆盖多只股票，跨股重复出现）。stock 无重复（每只 code 只从一只股票抽取一次）。去重策略：以 `(entity_type, code|name)` 为键，保留 confidence 最高（并列取 quality_score 最高，再并列取最早文件名），删除其余。

## 5. Confidence / Quality 分布（去重后）

| confidence | 数量 | 占比 | quality_score |
|---|---:|---:|---|
| high | 47 | 27.6% | 80 |
| medium | 123 | 72.4% | 50 |
| low | 0 | 0% | — |

- **high（47）**：全部是 stock 实体（6 位代码正则，确定性高，quality_score 80）。
- **medium（123）**：analyst 119 + industry 4。analyst 名字从研报 `researcher` 字段抽取，字段可信但规则匹配有边界误差风险，标 medium 合理；industry 同理。
- **low（0）**：本次无 low。规则推断的 stock→industry 关系（confidence: low）不落 inbox（只落实体，关系留在抽取结果 dict 里未持久化）。

## 6. 审核优先级建议

| 优先级 | 实体 | 数量 | 理由 |
|---|---|---:|---|
| **P0 立即审** | stock | 47 | confidence high，6 位代码确定，可直接灌入 `stocks/`（部分已存在，需合并而非新建）。 |
| **P1 批量审** | analyst | 119 | medium，名字来自研报字段可信，但需核对是否与 `analysts/` 已有记录重名（同姓同名不同人风险）。建议按机构聚类审核。 |
| **P2 抽查** | industry | 4 | medium，数量少，抽查标题里抓出的行业名是否准确（前缀剔除规则可能误伤）。 |
| **P3 补抽** | concept/metric | 0 | 本次规则模式抓不到，待 LLM key 恢复后用 `--use-llm` 全文化抽取补足。 |

## 7. 已知限制与后续

1. **LLM key 失效**：本次纯规则模式，只能抓研报结构化字段（代码/研究员/标题里的行业词）。营收/净利/ROE、概念题材、事件类实体需 LLM 全文语义抽取——待 `VR_LLM_*` 环境变量配置后跑 `--use-llm` 二轮补抽。
2. **industry 命中低**：根因是 `fetch_report_text` 组装的文本只含「标题+机构+研究员+EPS+PE」，不含行业描述句。可考虑后续拉研报正文摘要（若接口提供）提升 industry/concept 命中。
3. **analyst 跨股重复**：是真实重复（一人覆盖多股），去重后保留单条，但丢失了「该分析师覆盖哪些股」的覆盖关系。若要保留覆盖关系，应灌入 `covered_by` 关系而非重复落 analyst 实体——这是 inbox 待审区下一步的设计取舍。
4. **metric 0**：研报接口 `predictNextYearEps/predictNextYearPe` 是预测值，规则 metric 正则匹配「营收xx亿/净利xx亿/ROE xx%」字样，与 EPS/PE 字段不对应。可加规则直接把 EPS/PE 字段抽成 metric 实体（值来自接口，非臆造）。

## 8. 产出文件

- `10_Reference/investing/inbox/*.md`：170 个待审实体（去重后）
- `scripts/llm_extract.py`：新增 `--quiet` 标志；`fetch_report_text` 现在拼入 `researcher` 字段（真实数据，非臆造）
- `scripts/llm_extract_batch.sh`：批量驱动（50 股 × limit 2 × sleep 2）
- `scripts/llm_extract_dedup.py`：inbox 去重工具（`--dry-run` 预览）
