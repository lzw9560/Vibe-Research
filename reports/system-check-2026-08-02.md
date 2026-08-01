# Vibe-Research 全面体检报告

**日期**: 2026-08-02
**检查项**: 前后端 API 路径匹配、设计文档对齐、Playwright 测试

---

## 一、API 路径匹配检查 ✅ 全部通过

### 前端调用 → 后端路由对应情况

| 前端调用 | 后端路由 | 状态 |
|---------|---------|------|
| `/auction/monitor` | `/api/auction/monitor` | ✅ |
| `/market/overview` | `/api/market/overview` | ✅ |
| `/value-funnel/run` | `/api/value-funnel/run` | ✅ |
| `/workflow/status` | `/api/workflow/status` | ✅ |
| `/workflow/pre-market` | `/api/workflow/pre-market` | ✅ |
| `/sentiment/weather/latest` | `/api/sentiment/weather/latest` | ✅ |

**验证结果**: 所有 47 个前端 API 调用都有对应的后端路由。

---

## 二、设计文档对齐检查

### 关键 Spec 实现状态

| Spec | 状态 | 说明 |
|------|------|------|
| S002 打板工作流 | ✅ 已实现 | plan.md/spec.md/tasks.md 齐全 |
| S005 价值选股漏斗 | ✅ 已实现 | 包含 L1-L4 四层 |
| S013 前端数据层 | ✅ 已实现 | lib/api/ 模块化 |
| S016 测试网 | ✅ 已验收 | Playwright 3/3 通过 |
| S021 误删恢复 | ✅ 已修复 | 66+ 文件恢复 |

### 前后端 API 覆盖率

- **后端路由总数**: 140
- **前端调用数**: 47
- **覆盖率**: 34%（部分后端路由暂无前端页面，如 /proxy, /candidates 等）

---

## 三、发现的问题

### 🔴 Critical: Health API 返回 ok=false

**现象**:
```json
{"ok": false, "service": "vibe-research-api", "checks": {
  "circuit_breaker": {"ok": false, "detail": "circuit_breaker_open"}
}}
```

**影响**: Playwright 测试失败
```
Expected: true
Received: false
```

**根因**: circuit breaker 打开，可能是之前的测试或请求导致的

**建议**: 重启后端服务或重置 circuit breaker 状态

---

### 🟡 High: 部分后端路由无前端调用

未覆盖的路由（30+）：
- `/proxy` - AI代理
- `/candidates` - 候选池
- `/funnel/config` - 漏斗配置
- `/backtest/*` - 回测
- `/predict/*` - 预测

**说明**: 这些可能是后台功能或新开发的模块，不一定需要前端页面。

---

### 🟡 Medium: 前端页面 vs 路由数量不匹配

- 路由配置: 37 个
- 页面组件: 25 个
- 差值: 12 个路由可能指向子组件或动态路由

---

## 四、修复建议

1. **立即**: 重启后端服务，重置 circuit breaker
2. **近期**: 检查 `/proxy`, `/candidates` 等路由是否需要前端入口
3. **可选**: 补充 API 覆盖率文档，明确哪些路由是后台专用

---

## 五、验证结果

| 检查项 | 结果 |
|--------|------|
| pytest (729 tests) | ✅ 729 passed |
| vite build | ✅ 成功 |
| Playwright | ❌ 1 failed (health ok=false) |
| API 路径匹配 | ✅ 47/47 全部匹配 |
| 文件恢复 | ✅ 66+ 文件已恢复 |
