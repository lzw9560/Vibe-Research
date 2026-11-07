# backtest-discipline-guard

> **没有对照组的胜率 = 确认偏误。** 任何交易策略回测在投入真金前必须通过四步验证。

通用策略回测验证框架——把"看起来有效"翻译成"统计上有效"的 AI agent skill。

## Who it helps

任何做交易策略回测的 AI agent 用户：

- 用 Claude Code / OpenCode / Cursor / Codex 做策略研究的量化爱好者
- 想验证自己手写或 AI 生成策略是否真有 alpha 的散户/小团队
- 厌倦"回测胜率 90% 实盘亏成狗"的新手——想搞清楚为什么
- 需要 agent 在回测时自动套统计纪律，而不是靠人记得加对照组

不限于市场（A股 / 美股 / 加密 / 期货皆可），不限于品种，只要你有 K 线数据 + 信号数据。

## What problem it solves

**确认偏误是回测的默认失败模式，不是个例。**

三个"有效"策略（笼统跟庄、弱转强、尾盘错杀）表面胜率 59%~67%，加随机对照组后**全部退化到与随机无差异**（似然比 0.49x~1.1x，p > 0.08）。这不是策略不好，而是方法论错误——

| 常见错误 | 后果 | 本 skill 强制的修正 |
|---|---|---|
| 报胜率不报基准率 | "胜率 59%" 在某些基准下可能是 6x，在另一些基准下可能是 0.5x | 第1步先算基准率分母 |
| 表面 IC 当结论 | 涨幅发生在信号日之前，你买不进去——表面 9x 是假象 | 第3步幸存者偏差修正 |
| 不止损回测 | 期望收益看着正，但一次 -50% 吃掉十次盈利 | 第4步多档止损回测 |
| 混算子类 | 有效子类和陷阱子类混在一起，平均成负期望 | 鼓励分桶单独验证 |

## What evidence / workflow

四步验证流程，缺一不可：

1. **基准率（分母）**——随机选 N 只标的，统计 K 日涨 > X% 的概率。没有这个，所有"胜率"都是确认偏误。
2. **信号 IC（分子）**——有信号 vs 随机标的的收益差异，似然比 > 1.5 有效 / 1.2-1.5 弱 / < 1.2 无效。表面 IC 通过不算数。
3. **幸存者偏差（修正项）**——拆 pre/post 收益，真实口径似然比 = post_ret 对基准率。最致命陷阱：表面 9x 常修正后回到 0.49x。
4. **止损回测（风险）**——-5%/-7%/-10%/-15% 多档测试，找平均收益最高且误杀率可接受的那档。止损必须匹配策略，用 ATR 校准。

完整纪律与示例案例见 [`SKILL.md`](./SKILL.md)。

## What platforms

通过 `.agents/skills/` 目录的**便携式约定**支持多平台：

| 平台 | 安装路径 | 备注 |
|---|---|---|
| OpenCode | `~/.config/opencode/skills/` | 原生 skill 机制 |
| Claude Code | `.agents/skills/`（项目内）或 `~/.claude/skills/` | 项目级 / 用户级 |
| Cursor | `.agents/skills/`（项目内） | 规则文件方式 |
| Codex | `.agents/skills/`（项目内） | 规则文件方式 |

`.agents/skills/` 是跨平台事实标准——仓库内自带一份，克隆即装。

## What is NOT included

诚实声明边界：

- ❌ **不含特定市场数据源**——示例用 `<temp>/` 占位符，你接 akshare / tushare / yfinance / 自有 CSV 都行
- ❌ **不含实盘交易指令**——纯方法论，不生成下单信号，不接券商 API
- ❌ **不保证盈利**——框架只保证"不犯方法论错误"，不保证策略本身有 alpha
- ❌ **不替代专业建议**——样本量 <30 自动标"探索性"，不作为定稿依据

## 安装

### 方式 1：便携式（推荐，跨平台）

```bash
# 克隆本仓库后
cp -r .agents/skills/backtest-discipline-guard/ ~/.config/opencode/skills/
```

### 方式 2：OpenCode 原生

```bash
# 直接把根目录的 SKILL.md 复制过去
mkdir -p ~/.config/opencode/skills/backtest-discipline-guard
cp SKILL.md ~/.config/opencode/skills/backtest-discipline-guard/SKILL.md
```

### 方式 3：项目内（Cursor / Codex / Claude Code 项目级）

```bash
# 仓库内已自带 .agents/skills/backtest-discipline-guard/SKILL.md
# 克隆即可用，无需额外安装
```

## 用例

### 用例 1：验证一个新策略是否真有 alpha

向你的 AI agent 说：

> 我有一个策略：龙虎榜净买入的标的，次日开盘买入持有 20 日。帮我用 backtest-discipline-guard 的四步验证跑一遍。

agent 会自动套四步流程，先算基准率，再算信号 IC，再做幸存者偏差修正，最后做止损回测。结论是"有效"还是"假象"一目了然。

### 用例 2：审计已有的回测报告

> 这份回测报告说策略胜率 65%，帮我用 backtest-discipline-guard 审计它有没有确认偏误。

agent 会检查：基准率算了吗？似然比修正了吗？子类分桶了吗？止损匹配策略了吗？漏哪步补哪步。

### 用例 3：防止 agent 自己拍脑袋给结论

skill 的 description 以 `Use when backtesting any trading strategy` 开头，agent 在任何回测任务中会自动触发，强制套四步流程。你不需要每次提醒"记得加对照组"。

## License

MIT — 见 [LICENSE](./LICENSE)。
