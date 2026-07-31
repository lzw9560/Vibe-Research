# Baseline 录制约定

## 约定

Baseline 录制需对 10 只代表 code 跑真实接口取数，生成快照文件 `{code}_{endpoint}.json`：

- **A 股**: `600519`, `000858`, `300750`, `688981`, `000001`, `399001`
- **港股**: `00700`
- **美股**: `AAPL`
- **韩股**: `005930.KS`

## 回放逻辑

回放时 mock 网络返回上述 JSON，验证模型 round-trip（原始 JSON → 映射 → model_validate → model_dump → 关键字段一致）。

## 真实录制 TODO

> 真实录制为 **live 一次性步骤**，待人工或 live CI 跑通后替换。当前用 `backend/data/fallback/*.json` 作为已捕获形状样本临时复用。

- [ ] 对 10 只代表 code 跑真实 `capital_flow` 接口录制快照
- [ ] 对 10 只代表 code 跑真实 `dragon_tiger` 接口录制快照
- [ ] 将快照迁入 `backend/tests/contract/baseline/` 目录
- [ ] 替换 fallback 临时复用逻辑
