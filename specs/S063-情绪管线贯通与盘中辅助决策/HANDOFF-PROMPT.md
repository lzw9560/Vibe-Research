# S063 实施提示词（交给 Claude Code）

## 复制以下内容作为 Claude Code 的初始 prompt

---

你正在 Vibe-Research 项目实施 **S063 · 情绪管线贯通与盘中辅助决策**。

### 必读文件（按顺序）

1. `specs/S063-情绪管线贯通与盘中辅助决策/spec.md` — 完整 spec（10 节 + 7 节补充）
2. `specs/S063-情绪管线贯通与盘中辅助决策/plan.md` — 4 阶段实现计划
3. `specs/S063-情绪管线贯通与盘中辅助决策/tasks.md` — 34 个原子任务表
4. `specs/S063-情绪管线贯通与盘中辅助决策/ui-mockup.html` — 高保真 UI mockup（浏览器打开，4 页可切换，所有数据项可点击跳详情）
5. `AGENTS.md` — 分级工作流（本 spec 是 large 级）
6. `CLAUDE.md` — 项目约束

### 环境（注意：CLAUDE.md 写的是 Windows 路径，实际在 macOS）

- 仓库根：`/Users/lizhiwei/project/code/stock/Vibe-Research`
- 当前分支：`develop` @ `6750c2f`
- Python venv：`.venv/`（Python 3.11.8），解释器 `.venv/bin/python`
- 后端启动：`cd backend && ../.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8900`
- 前端启动：`cd frontend && npm run dev`（:5899，Vite 代理 /api→:8900）
- 后端测试：`cd backend && ../.venv/bin/python -m pytest -m "not live" -x`
- 前端类型检查：`cd frontend && npx tsc --noEmit`
- 数据库在 `.vibe-research/`（gitignored）：gene_scores.db / winrate.db / sti_timeline.db

### 分支

```
git checkout develop
git pull
git checkout -b feature/S063-sentiment-pipeline
```

### 实施顺序

严格按 tasks.md 的 4 阶段 + 依赖链执行：

**Phase 1（后端基础 T1-T9）→ Phase 2（盘中后端 T10-T16）→ Phase 3（前端 T17-T29）→ Phase 4（测试 T30-T34）**

每个 Phase 完成后：
1. `pytest -m "not live" -x` 全过
2. `npx tsc --noEmit` 零错误（Phase 3+）
3. 勤 commit（`wip:` 前缀可，引用 task ID）
4. Phase 1+2 合并一次 squash commit，Phase 3 合并一次

### 核心设计决策（讨论确认，不可偏离）

1. **T-1 情绪是硬标准**：盘前读 T-1 的 STI/weather_state，不实时计算。STI 盘后定时任务（交易日 15:30）计算当日 STI → 持久化 → 成为 T+1 的硬标准。

2. **SentimentContext 一次采集逐级下传**：`build_context(T)` 在管线头部构造一次，下传给 `PreMarketBriefing` / `resolve_thresholds` / `StrategyMatcher` / `PositionAdvisor` / `Funnel` / `IntradayMonitor`。不再三处独立调。

3. **盘中 4 维度固定阈值**：涨停家数/封板率/炸板率/涨跌比，固定阈值映射 0-100，加权平均。不用 8 维度百分位归一化（盘中历史不足）。

4. **盘中不做天气标签投影**：只给分数+趋势箭头+T-1 基线色带（绿/黄/红）。不给"投影天气"标签。T-1 weather_state 独占天气标签。

5. **盘中不自动切换战法**：T-1 硬标准不被动摇。盘中只做辅助（4 层）：分数色带（被动）、持仓×情绪联动（主动关联）、条件场景 if-then（主动推理）、T+1 预判（14:30 专项）。

6. **采样按黄金窗口**：9:25-9:45 每 5min，9:45-10:30 每 15min，10:30-11:30 每 30min，13:00-14:30 每 30min，14:30-15:00 每 5min。一天约 12-14 个 snapshot。

7. **T+1 预判不做告警推送**：不弹窗不推送。用户看色带自行判断。T+1 预判标注"投影，非最终判定"。

8. **历史参照诚实标注样本量**：首日样本=0，逐日积累。不编准确率。

9. **`calc_weather_fit` 终于被调用**：战法匹配时调 `calc_weather_fit(code, weather_state)` 标注适配/不适配/中性。不适配的战法在简报标灰不删除。

10. **`PositionAdvisor` 接 weather_state**：暴风雨→仓位上限=0（禁止开仓），极端反弹→50%，晴天/阴天→正常。

### 合规底线（不可违反）

- **不臆造数据**：历史参照样本量不足时标注"样本不足"，不编准确率
- **盘中预判标注"投影，非最终判定"**
- **em_zt_topic_pool 限流防封**：复用 TTL 缓存，采样间隔不低于 5 分钟，走 `data/transport.py`
- **私有数据隔离**：持仓联动只读 `workflow_state_repo`，不输出个股推荐

### 未提交的工作树改动（不归你管，不要动）

```
M backend/candidate_funnel/funnel.py     — 上一会话 R1 回填改动
M backend/limitup_sti/models.py          — percentile_rank 去 n<60
M backend/seat_profiles.json
M frontend/src/pages/DailyReview.tsx      — STITimelineChart
M frontend/src/pages/workflow/PreMarketBriefing.tsx — entryFor 合并
```

这些改动是前一会话的，你在 `feature/S063` 分支上会带过去。如果它们和你的改动冲突，以你的改动为准（但不要 revert 它们，merge 处理）。

### AC 清单（最终验收）

后端：AC1-AC10
前端：AC11-AC19
合规：CC1-CC4
详见 spec.md §6

### 完成标准

1. 34 个 task 全部完成
2. `pytest -m "not live"` 全过
3. `npx tsc --noEmit` 零错误
4. 简化 playwright：盘前 WeatherDecisionBar + 盘中四层布局渲染
5. live 冒烟（交易日）：盘前→盘中→盘后三页验证
6. `feature/S063-sentiment-pipeline` 分支 squash merge 到 develop，合并后删分支

### 全程中文交流

commit message 中文，spec/issue 中文，代码标识符英文。中间更新和最终回复一律中文。
