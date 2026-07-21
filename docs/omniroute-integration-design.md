# OmniRoute 集成设计 — 托底模型通道

## 1. 背景

当前 Vibe-Research 的 AI 对话层（`backend/chat.py`）只支持单一模型通道：
- **API Key 模式**：用户配置 `baseURL` + `apiKey` + `model`，直接调上游
- **CLI 模式**：通过 `cli_runtime.py` 调本机 CLI（Claude Code / Codex 等）

痛点：
- 单一 API Key 配额用完/限流就断了
- 没有自动切换备选模型的能力
- 无法利用多个提供商的免费额度

**OmniRoute 的定位**：在 chat.py 之上加一层**可选的** fallback 通道，不替换现有逻辑。

---

## 2. 架构设计

```
┌─────────────────────────────────────────────┐
│  Frontend (Settings / chat)                  │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │ API Key 模式 │  │ OmniRoute 托底模式    │  │
│  │ direct →    │  │ → localhost:20128/v1   │  │
│  │ upstream    │  │   (auto-fallback)      │  │
│  └─────────────┘  └──────────────────────┘  │
└──────────────────┬──────────────────────────┘
                   │
          ┌────────▼────────┐
          │  chat.py        │
          │  run_chat()     │
          │  run_chat_stream()│
          └────────┬────────┘
                   │
          ┌────────▼────────┐
          │  _call_llm()    │
          │  _call_llm_     │
          │  stream()       │
          └─────────────────┘
```

**关键原则**：
- OmniRoute 作为**可选通道**，不是默认通道
- 现有 API Key 模式不变
- 在 Settings 页新增"启用 OmniRoute 托底"开关
- 启用后，chat.py 的 `_call_llm` 通过 OmniRoute 的 `/v1` 端点调用

---

## 3. 集成方案

### 3.1 后端改动（解耦）

**新增文件**：`backend/omniroute_client.py`

```python
"""OmniRoute 托底模型通道。

可选模块：仅在用户启用且 OmniRoute 本地服务可达时工作。
不引入任何额外依赖——复用 chat.py 已有的 requests。
"""

import os
import socket
from typing import Optional

DEFAULT_OMNIRoute_URL = os.getenv("OMNIRoute_BASE_URL", "http://localhost:20128")

def _is_omniroute_available(timeout: float = 1.0) -> bool:
    """检查 OmniRoute 本地服务是否可达。"""
    from urllib.parse import urlparse
    parsed = urlparse(DEFAULT_OMNIRoute_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 20128
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False

def call_via_omniroute(messages: list, model: str = "auto", temperature: float = 0.3,
                       use_tools: bool = True, stream: bool = False) -> dict | None:
    """通过 OmniRoute 调用模型。

    返回格式与 chat.py 的 _call_llm 一致：
    {"choices": [{"message": {"content": "...", "tool_calls": [...]}}]}
    
    如果 OmniRoute 不可达，返回 None（fallback 到直接调用或报错）。
    """
    import requests
    
    if not _is_omniroute_available():
        return None
    
    base = DEFAULT_OMNIRoute_URL.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    
    payload = {
        "model": model,  # "auto" 或具体模型 ID
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if use_tools:
        # TODO: 注入 TOOLS 定义（从 chat.py 导入）
        pass
    
    endpoint = f"{base}/chat/completions"
    r = requests.post(endpoint, json=payload, timeout=120, stream=stream)
    if r.status_code != 200:
        return None
    
    if stream:
        return r  #  caller 负责解析 SSE
    
    return r.json()
```

**修改文件**：`backend/chat.py`

- 在 `run_chat` / `run_chat_stream` 开头增加 OmniRoute 通道尝试
- 如果 OmniRoute 返回 None，回退到原有直接调用逻辑
- 通过配置项控制是否启用：

```python
# 新增环境变量
OMNIRoute_ENABLED = os.getenv("VR_OMNIRoute_ENABLED", "false").lower() == "true"
OMNIRoute_MODEL = os.getenv("VR_OMNIRoute_MODEL", "auto")  # "auto" 或具体模型
```

### 3.2 Settings 前端改动

在 Settings 页新增卡片：

```
┌─────────────────────────────────────────┐
│  OmniRoute 托底通道                      │
│  ─────────────────────────────────────  │
│  ○ 不使用（默认）                         │
│  ● 启用 OmniRoute 自动切换                │
│                                         │
│  模型选择： [auto ▼]                     │
│  OmniRoute 地址： [http://localhost:20128]│
│                                         │
│  ℹ 启用后，AI 对话会先走 OmniRoute，     │
│     自动切换最便宜的可用模型。              │
└─────────────────────────────────────────┘
```

- 配置保存在 `~/.vibe-research/settings.json`
- 不修改现有 API Key / CLI 配置

### 3.3 Docker 集成（可选）

在 `docker-compose.yml` 中增加可选的 omniroute 服务：

```yaml
services:
  omniroute:
    image: diegosouzapw/omniroute:latest
    container_name: vr-omniroute
    ports:
      - "20128:20128"
    environment:
      - NODE_ENV=production
      - INITIAL_PASSWORD=${OMNIRoute_PASSWORD:-changeme}
    restart: unless-stopped
    # 仅在有 API 密钥时才需要
    profiles: ["omniroute"]  # docker compose --profile omniroute up
```

用户通过 `docker compose --profile omniroute up -d` 按需启动。

---

## 4. 依赖分析

| 模块 | 是否新增依赖 | 说明 |
|------|-------------|------|
| `requests` | 否 | chat.py 已用，复用 |
| `socket` | 否 | stdlib |
| `urllib.parse` | 否 | stdlib |
| OmniRoute 服务 | 是 | 独立 Node.js 进程 / Docker 容器 |

**结论**：后端零新增 Python 依赖。

---

## 5. 实施步骤

1. **Phase 1**：创建 `omniroute_client.py`，实现 `_is_omniroute_available` + `call_via_omniroute`
2. **Phase 2**：修改 `chat.py`，在 `run_chat` / `run_chat_stream` 开头尝试 OmniRoute 通道
3. **Phase 3**：Settings 页新增 OmniRoute 配置 UI
4. **Phase 4**：`docker-compose.yml` 增加可选 omniroute 服务
5. **Phase 5**：集成测试（本地部署 OmniRoute → 验证自动切换）

---

## 6. 风险与约束

- **本地绑定**：OmniRoute 绑定 `localhost:20128`，需确保本地运行
- **Node.js 依赖**：OmniRoute 本身需要 Node.js 环境
- **API 密钥管理**：用户仍需在各提供商注册获取密钥，填入 OmniRoute 控制台
- **合规**：OmniRoute 只是路由层，不改变"零标的红线"——数据仍来自客观 API

---

## 7. 不做什么

- 不修改现有 API Key 模式的调用逻辑
- 不强制用户安装 OmniRoute
- 不引入新的 Python 包
- 不改 chat.py 的核心 function-calling 循环
