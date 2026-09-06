#!/usr/bin/env python3
"""生成企业微信回调的 Token 和 EncodingAESKey。

用法: python3 scripts/generate-wechat-credentials.py

输出：打印到 stdout，并尝试写入 backend/.env（若不存在或已存在则跳过/提示）。
"""
import base64
import secrets
import string
from pathlib import Path

# backend/.env 绝对路径（脚本相对仓库根 scripts/ 下，backend 同级）
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_PATH = REPO_ROOT / "backend" / ".env"


def generate_token(length: int = 32) -> str:
    """企业微信 Token：字母+数字，建议 32 字符（可自定义长度 3~32）。"""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def generate_aes_key() -> str:
    """企业微信 EncodingAESKey：43 字符，Base64 编码的 32 字节随机串。

    企业微信要求 43 位 Base64（对应 32 字节原始 key）。
    """
    raw = secrets.token_bytes(32)
    key = base64.b64encode(raw).decode()
    # 标准 base64 32 字节 → 44 字符（含 1 个 =），截断到 43
    return key[:43]


def main() -> None:
    token = generate_token()
    aes_key = generate_aes_key()

    print(f"Token: {token}")
    print(f"EncodingAESKey: {aes_key}")
    print()
    print("在 .env 里加：")
    print(f"WECHAT_TOKEN={token}")
    print(f"WECHAT_ENCODING_AES_KEY={aes_key}")
    print()

    # 自动写入 .env（若不存在则提示手动）
    if ENV_PATH.exists():
        content = ENV_PATH.read_text(encoding="utf-8")
        if "WECHAT_TOKEN" not in content:
            with open(ENV_PATH, "a", encoding="utf-8") as f:
                f.write(
                    f"\n# 微信企业应用回调\n"
                    f"WECHAT_TOKEN={token}\n"
                    f"WECHAT_ENCODING_AES_KEY={aes_key}\n"
                )
            print(f"✅ 已写入 {ENV_PATH}")
        else:
            print(f"⚠️  {ENV_PATH} 已有 WECHAT_TOKEN，请手动更新为新值")
    else:
        print(f"ℹ️  未找到 {ENV_PATH}，请手动添加以上变量到你的 .env")


if __name__ == "__main__":
    main()
