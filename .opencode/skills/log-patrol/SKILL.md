---
name: log-patrol
description: 监控 Vibe-Research 前后端运行日志，发现 bug 后建 issue 并派 fixer 修复。用于"监控日志发现 bug 修复"、"日志报错"、"看一下日志有没有 bug"、"检查运行状态"等场景。
license: MIT
metadata:
  voice: "Vibe-Research 运维 — 日志驱动、根因优先、issue 可追溯"
  version: 1.0.0
---

# Log Patrol

> 监控运行日志 → 定位根因 → 建 issue → 派 fixer 修复 → 验证。
> 本 skill 把"日志监控驱动的 bug 修复"固化为可重复流程，避免每次重新规划。

## 触发条件

- 用户说"监控日志"、"看一下日志"、"日志有没有 bug"、"检查运行状态"
- 用户说"发现 bug 修复"、"新建 issue 修复"
- 任何需要从运行日志出发定位并修复 bug 的场景

## 前提检查

开始前先确认服务在跑、日志文件存在：

```bash
# 后端
lsof -i :8900 -t 2>/dev/null && echo "backend up" || echo "backend down"
ls -la /tmp/vibe-backend.log 2>/dev/null

# 前端
lsof -i :5899 -t 2>/dev/null && echo "frontend up" || echo "frontend down"
ls -la /tmp/vibe-frontend.log 2>/dev/null
```

- 后端日志：`/tmp/vibe-backend.log`
- 前端日志：`/tmp/vibe-frontend.log`
- 后端端口：8900（uvicorn）
- 前端端口：5899（vite dev）

若服务没跑，先起服务再监控（见末尾"服务启停"）。

## 工作流

### 第 1 步：抓日志找异常

**先抓全貌，再抓细节。** 不要只看尾部几行。

```bash
# 1. 全量日志行数（判断规模）
wc -l /tmp/vibe-backend.log

# 2. 所有非 200 的 HTTP 请求（500/403/404 等）
grep -E "HTTP/1.1\" [45]" /tmp/vibe-backend.log | head -20

# 3. 所有错误/异常/警告关键词
grep -nE "ERROR|Traceback|Exception|RuntimeError|RuntimeWarning|failed|Failed|Timeout|timeout|never awaited|no running" /tmp/vibe-backend.log | grep -v "INFO:" | head -40

# 4. 日志尾部（看最近发生了什么）
tail -40 /tmp/vibe-backend.log
```

前端日志也扫一遍（vite 编译错误、运行时 error）：

```bash
grep -nE "ERROR|Error|error|warn|Warning|Failed|failed" /tmp/vibe-frontend.log | head -20
```

### 第 2 步：定位根因

发现异常行号后，**读完整 traceback**，不要只看摘要。

```bash
# 例：grep 发现第 16 行有 ERROR，读前后 60 行看完整调用栈
sed -n '14,80p' /tmp/vibe-backend.log
```

从 traceback 最底部找**用户代码帧**（非第三方库帧），格式是：

```
File "/Users/lizhiwei/project/code/stock/Vibe-Research/backend/routers/XXX.py", line NNN, in FUNC_NAME
    问题代码行
    ^^^^
RuntimeError: 错误消息
```

锁定后，读该文件该行号附近代码确认修法：

```
Read backend/routers/XXX.py offset=NNN-10 limit=40
```

### 第 3 步：建 issue

在 `.scratch/` 下建 effort + issue，格式对齐项目既有风格。

```bash
mkdir -p .scratch/<effort-slug>/issues
```

**issue 文件** `.scratch/<effort-slug>/issues/NN-<slug>.md`，内容结构：

```markdown
# NN · <简短标题>

- **级别**：small | medium | large
- **triage**：ready-for-agent
- **发现方式**：日志监控
- **复现**：<触发条件>

## 症状

后端日志：
<贴关键日志片段>

## 根因

<文件:行号> 的什么代码做了什么，为什么错。

## 修复方案

具体改什么，为什么这么改。

### 改动
<文件路径:行号> — 改什么

### 验证
1. <验证步骤>
2. ...

## 影响范围

<改了哪些文件，是否有数据层/schema 改动>
```

**map.md** `.scratch/<effort-slug>/map.md`：

```markdown
# Effort: <effort-slug>

> <一句话描述>。<日期> 日志监控发现。

## Issues

| # | slug | 标题 | 级别 | triage |
|---|---|---|---|---|
| 01 | <slug> | <标题> | <级别> | ready-for-agent |
```

### 第 4 步：grill 确认修复方案

issue 建好后，**不急着派 fixer**。先调 `grill-me` skill 对修复方案做一轮审问，确认根因判断对、改法无副作用、验证路径可靠，再动手改代码。

**触发方式**：加载 grill-me skill，把 issue 内容当作被审问的方案喂给它。

```
skill(name: "grill-me")

# 喂给 grill 的方案摘要
- bug：<文件:行号> 的什么代码做了什么，为什么错>
- 根因：<从 traceback 读到的用户代码帧 + 原因>
- 修复方案：<具体改什么>
- 验证：<重启 + 触发 bug 路径 + 检查日志>
```

grill 会一次一个问题、每个问题带推荐答案，逐分支走完。常见的审问点：

- **根因是否真的在用户代码帧？** 第三方库帧也可能是问题源（如 starlette middleware bug）。
- **改法是否有副作用？** `def` → `async def` 是否影响 FastAPI 的 threadpool 行为？是否影响并发守卫的 check→set 原子性？
- **是否有更深的同类 bug？** 同一个 `asyncio.create_task in sync endpoint` 模式是否在别的 router 里也出现？grep 全仓确认。
- **验证路径是否真能复现？** 触发 bug 路径的 curl 命令是否对？日志关键词是否抓得准？
- **影响范围是否低估？** 是否有调用方依赖原签名？是否需要同时改测试？

**grill 收敛标准**：

- 所有分支问题都已回答
- 用户确认修复方案（或 grill 发现问题后调整方案）
- 无遗留的"待 live 后定"占位项

**grill 通过后才进第 5 步。** 若 grill 发现根因判断错或改法有副作用，回到第 2 步重新定位根因，或调整 issue 里的修复方案，重新 grill。

### 第 5 步：派 fixer 修复

grill 确认后，派 fixer 执行修复。**给 fixer 完整上下文**：文件路径、行号、根因、具体改法、验证命令。

```
task(subagent_type: "fixer", description: "Fix: <简短描述>", prompt: """
在 /Users/lizhiwei/project/code/stock/Vibe-Research 修复一个 bug。

## Bug
<文件:行号> 的什么代码做了什么，为什么错。

## 修复
<具体改什么，为什么>

## 验证
1. 改完跑 <验证命令> 确认无语法错误
2. 确认改动（grep 那一行）
3. 报告改了哪个文件哪一行
""")
```

### 第 6 步：重启验证

fixer 完成后，重启服务触发 bug 路径验证修复生效。

```bash
# 重启后端
pkill -f "uvicorn app:app" 2>/dev/null; sleep 1
cd /Users/lizhiwei/project/code/stock/Vibe-Research && nohup .venv/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8900 --app-dir backend > /tmp/vibe-backend.log 2>&1 &

# 等 startup complete（intraday 采样 + advisory 预热慢，约 2 分钟）
for i in $(seq 1 60); do
  lsof -i :8900 -t >/dev/null 2>&1 && break
  sleep 2
done

# 触发 bug 路径
curl -s -w "\nHTTP:%{http_code}\n" <复现命令>

# 验证日志无原错误
grep -E "<原错误关键词>" /tmp/vibe-backend.log | head -5 || echo "无相关错误"
```

### 第 7 步：收尾

- 更新 todo 标记完成
- 向用户报告：发现什么 bug、根因、改了什么、验证结果

## 规则

1. **根因优先。** 不只看症状（500/Warning），必须读到用户代码帧定位根因再建 issue。
2. **issue 可追溯。** 每个 bug 都建 issue 文件，记录根因+修复方案+验证步骤，不留口头记忆。
3. **fixer 给全上下文。** 派 fixer 时给文件路径、行号、根因、具体改法、验证命令，不让 fixer 自己猜。
4. **重启验证。** 修复后必须重启服务+触发 bug 路径+检查日志，确认原错误消失。不只靠 import 通过。
5. **不臆造。** 日志里没有的 bug 不建 issue。外部源连接超时（如 worldmonitor ConnectTimeout）属网络问题非代码 bug，降级为 WARNING 不立项。

## 噪声过滤

这些日志不算 bug，不立项：

- `worldmonitor ... ConnectTimeout` — 外部源连不上，网络问题
- `INFO: ... HTTP/1.1" 200 OK` 大量重复 — 正常轮询
- `factors.registry: 因子 XXX 采集耗时 Ns` — 慢但不报错，属性能问题非 bug（除非用户要求优化）
- `LSP ... could not be resolved` — 编辑器解释器没指向 .venv，非真实代码错误

## 服务启停

```bash
# 起后端（后台）
cd /Users/lizhiwei/project/code/stock/Vibe-Research && nohup .venv/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8900 --app-dir backend > /tmp/vibe-backend.log 2>&1 &

# 起前端（后台）
cd /Users/lizhiwei/project/code/stock/Vibe-Research/frontend && nohup npm run dev > /tmp/vibe-frontend.log 2>&1 &

# 停
pkill -f "uvicorn app:app"
pkill -f "vite"
```

后端 startup 慢（intraday 采样 + advisory 回测预热，约 2 分钟），轮询端口直到监听再验证。

## 常驻监控模式

skill 本身是指令集（被动加载），不能常驻。但可以启动**后台监控脚本** `scripts/patrol.sh`，它持续 tail 前后端日志，发现异常写告警文件到 `.scratch/log-patrol-alerts/`，会话结束也不停。

### 启动常驻监控

```bash
# 启动（nohup 后台，会话结束不停）
nohup bash /Users/lizhiwei/project/code/stock/Vibe-Research/.opencode/skills/log-patrol/scripts/patrol.sh > /tmp/log-patrol.log 2>&1 &
echo $! > /tmp/log-patrol.pid

# 验证进程在跑
ps -p $(cat /tmp/log-patrol.pid) -o pid,state,etime,command
```

### 查看告警

```bash
# 列出告警文件
ls -lt /Users/lizhiwei/project/code/stock/Vibe-Research/.scratch/log-patrol-alerts/ 2>/dev/null | head

# 读最新告警
cat /Users/lizhiwei/project/code/stock/Vibe-Research/.scratch/log-patrol-alerts/*.alert 2>/dev/null | head -40
```

告警文件命名：`<backend|frontend>-<时间戳>.alert`，内容含 ALERT 标记、时间、日志路径、命中的错误行、上下文 20 行。

### 处理告警

发现新告警文件后，走本 skill 的第 2-7 步（定位根因 → 建 issue → grill 确认 → 派 fixer → 重启验证 → 收尾）。告警文件里的 CONTEXT 段已含 traceback 上下文，可直接用。

### 停止常驻监控

```bash
kill $(cat /tmp/log-patrol.pid) 2>/dev/null && rm /tmp/log-patrol.pid
```

### 监控覆盖的错误模式

`patrol.sh` 命中以下关键词即告警：

- `RuntimeError` / `RuntimeWarning`
- `Traceback` / `Exception in ASGI`
- `HTTP/1.1" 5XX`（500-599 状态码）
- `no running event loop` / `never awaited` / `coroutine.*was never`

噪声过滤（命中但不算 bug，不告警）：

- `worldmonitor.*ConnectTimeout` — 外部源网络问题
- `LSP.*could not be resolved` / `Import.*could not be resolved` — 编辑器解释器误报

### 轮询频率

每 10 秒扫描一次新增日志行（基于 offset 增量，不重读全文件）。日志被截断（重启清空）自动重置 offset。

---

**Version:** 1.1.0
**项目：** Vibe-Research
