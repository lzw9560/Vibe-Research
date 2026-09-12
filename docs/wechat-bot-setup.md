# 微信 Bot 配置指南

企业微信回调 → Vibe-Research 后端的完整配置流程。微信 bot 路由实现见 `backend/routers/wechat_bot.py`。

## 前置条件

- Vibe-Research 后端在跑（默认 `http://127.0.0.1:8900`，启动命令 `uvicorn app:app --host 127.0.0.1 --port 8900`）
- 微信 bot 路由已注册（`routers/wechat_bot.py`，`app.include_router(wechat_bot_router.router)`）
- 本地开发需公网可达——用内网穿透（Cloudflare Tunnel / ngrok）

## 步骤

### 1. 生成 Token + AESKey

```bash
python3 scripts/generate-wechat-credentials.py
```

脚本会打印 `WECHAT_TOKEN` 和 `WECHAT_ENCODING_AES_KEY`，并尝试写入 `backend/.env`（已有则跳过，提示手动更新）。两个值的规格：

- `WECHAT_TOKEN`：32 字符，字母 + 数字（企业微信要求 3~32 字符）
- `WECHAT_ENCODING_AES_KEY`：43 字符 Base64（对应 32 字节原始 key，企业微信要求 43 位）

### 2. 启动隧道

```bash
bash scripts/setup-wechat-tunnel.sh 8900
```

脚本优先用 Cloudflare Tunnel（免费、无需注册），未装则回退 ngrok。启动后输出形如：

```
公网 URL: https://xxx-yyy.trycloudflare.com
```

复制这个 URL，保持终端运行（Ctrl+C 关闭隧道）。

### 3. 企业微信配置

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/) → 应用管理 → 自建应用
2. 进入应用 → "接收消息" → "设置 API 接收"
3. **URL** 填：`https://xxx-yyy.trycloudflare.com/api/wechat/bot`
   - 注意路径是 `/api/wechat/bot`（GET 用于微信回调校验，POST 用于接收消息）
4. **Token** + **EncodingAESKey** 从步骤 1 复制粘贴
5. 保存——企业微信会回调 GET 做校验，成功后才生效

### 4. 测试

在微信里 @ 应用发：

- `查所有股票` → bot 返回当前股票池列表
- `600519 关联` → 返回贵州茅台的图谱关联实体
- `图谱健康` → 返回知识图谱健康检查

更多命令见 `backend/routers/wechat_bot.py` 注释。

## 注意事项

### 隧道 URL 不稳定

- **Cloudflare Tunnel 免费版**（quick tunnel）：每次启动 URL 都变，需在企业微信后台重新填
- **ngrok 免费版**：同样每次变 URL
- 需要固定域名：
  - Cloudflare Named Tunnel（需自己的域名 + Cloudflare 账号，仍免费）
  - ngrok 付费版（固定子域名）

### 回调校验失败排查

企业微信保存时若提示 "URL 验证失败"：

1. 确认后端在跑：`curl http://127.0.0.1:8900/api/wechat/bot?msg_signature=x&timestamp=1&nonce=1&echostr=1` 应返回 200（哪怕签名错）
2. 确认隧道通：浏览器访问 `https://xxx.trycloudflare.com/api/wechat/bot` 应返回内容（不是 502/404）
3. 确认 Token / EncodingAESKey 与 `backend/.env` 里一致，且后端重启过（env 改了要重启 uvicorn）
4. 查后端日志：微信校验请求会打到 `wechat_bot.py` 的 `GET /api/wechat/bot`

### 安全

- `backend/.env` 已在 `.gitignore`，不会提交。但生成脚本打印的 Token/AESKey 会出现在终端历史里，敏感环境记得清理
- 企业微信回调的消息体是加密的（用 EncodingAESKey 解），即使公网传输也安全
- 本地开发用临时 Token 即可，生产环境务必换新

## 相关文件

- `backend/routers/wechat_bot.py`：bot 路由（GET 校验 + POST 消息 + /direct /test 辅助端点）
- `backend/config.py`：读 `WECHAT_TOKEN` / `WECHAT_ENCODING_AES_KEY` 环境变量
- `scripts/setup-wechat-tunnel.sh`：穿透启动脚本
- `scripts/generate-wechat-credentials.py`：凭证生成脚本
