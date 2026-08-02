# 验收报告 · S016（Playwright 冒烟验收补充）

- 日期：2026-08-01
- 结果：✅ PASS
- 关联 spec：`specs/S016-测试网/spec.md`（测试网 · 前端验收层补充：playwright E2E 冒烟）
- 验收范围：前端 UI 冒烟 + 后端连通（AGENTS.md 验收门口径）

## 用例结果

- 通过：**3 / 3**
- 失败：0

| # | 用例 | 断言 | 结果 |
|---|---|---|---|
| 1 | backend /api/health 连通 | 直连 8900，`ok=true` + service | ✅ 202ms |
| 2 | /daily-review 渲染并落位真实数据 | heading 命中 `/日度复盘|每日复盘|Daily Review/i` + tbody 首行非空 | ✅ 4.7s |
| 3 | 导航栏入口可用 | `/` 重定向到 `/daily-review`，nav/aside/header 可见 | ✅ 10.1s |

## 失败明细

无。

## 运行时间

- 总耗时：18.4s（3 用例，2 workers 并行）
- 运行命令：`npx playwright test --reporter=list`（`frontend/` 下）

## 测试环境

- 本机：macOS 12.7.6（Apple Silicon，darwin）
- 浏览器：`channel: 'chromium'` → Chrome（`channel: 'chrome'`，复用系统 Chrome；mac12 不支持 `npx playwright install chromium`）
- 后端：`cd ../backend && .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900`，`GET /api/health` 200
- 前端 dev server：`npm run dev`（vite，端口 5899，`server.proxy /api → http://127.0.0.1:8900`）
- Playwright：@playwright/test 1.62.1；webServer 双探针（8900 + 5899），`reuseExistingServer: !CI`，超时 120s
- 前端入口：`frontend/index.html` 已从 git 历史 `185c9e4^` 恢复（dev 版，`/src/main.tsx`）

## 备注

- 前置修复：`frontend/playwright.config.ts` baseURL 与 webServer url 由 5173 对齐为 5899（vite 实际端口）。
- 关联遗留：git status 未提交改动（前端入口恢复 + playwright 基建 + 既有 working-tree 变更）尚未做验收提交；AGENTS.md 要求报告随 feature 分支提交。
