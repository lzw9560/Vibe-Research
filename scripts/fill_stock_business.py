#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 批量补充 stocks/*.md 的"## 📊 核心业务"段正文。

对每只占位为"待补充"的股票：
1. 读 frontmatter（code/name/industry/pe_ttm/pb/market_cap/concept）
2. 构造 prompt 调百炼 LLM 生成 2-3 句核心业务简介
3. 替换占位为生成正文（带 <!-- LLM 生成，待人工校验 --> 注释）
4. 失败的标"LLM 生成失败"

并发执行（默认 8 线程），单只超时 120s，max_tokens=4096（deepseek-v4-pro 是推理模型，
reasoning 占 ~2000 tokens，content 才有空间）。

用法：
  python3 scripts/fill_stock_business.py              # 默认 8 并发, 全量
  python3 scripts/fill_stock_business.py -n 4        # 4 并发
  python3 scripts/fill_stock_business.py --limit 10  # 只处理前 10 只(测试用)
  python3 scripts/fill_stock_business.py --dry-run    # 只扫描不调 LLM 不写文件

合规：只生成客观描述，不臆造具体财务数据，不构成投资建议。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings()

# ── 路径 ────────────────────────────────────────────────────────────────────
REPO = Path("/Users/lizhiwei/project/code/stock/Vibe-Research")
ENV_FILE = REPO / "backend" / ".env"
DOCS = REPO / "docs"
VAULT_STOCKS = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/stocks")

# ── 两种占位格式 ─────────────────────────────────────────────────────────────
# A 型（指数成分股灌入，带 > quote，325 只）：
#   ## 📊 核心业务
#
#   > 待补充（从指数成分股灌入，核心业务描述后续 LLM 填充）。
#   - 所属指数：[[indices/000300]]
# B 型（涨停池灌入，无 > quote，55 只）：
#   ## 📊 核心业务
#
#   （待补充——本实体由涨停池数据自动灌入，核心业务描述待 LLM 从公告/研报抽取。）
#
# 替换策略：定位"## 📊 核心业务"段（到下一个 ## 标题或文件尾），
# 段内找"待补充"占位行替换为生成正文 + 校验注释，保留 B 型后续的结构行（如"所属指数"）。

PLACEHOLDER_A = "从指数成分股灌入"   # A 型占位的关键词
PLACEHOLDER_B = "本实体由涨停池数据自动灌入"  # B 型占位的关键词
BUSINESS_HEADER = "## 📊 核心业务"
NEXT_HEADER_RE = re.compile(r"^## ", re.MULTILINE)


def find_business_section(text: str) -> tuple[int, int] | None:
    """返回(段起始下标, 段结束下标) 或 None。

    段 = "## 📊 核心业务" 行起到下一个 ## 标题或文件尾。
    """
    idx = text.find(BUSINESS_HEADER)
    if idx < 0:
        return None
    # 找下一个 ## 标题（不含本行）
    next_m = NEXT_HEADER_RE.search(text, idx + len(BUSINESS_HEADER))
    end = next_m.start() if next_m else len(text)
    return idx, end


def is_placeholder_section(section_text: str) -> bool:
    """检查核心业务段是否含"待补充"占位。"""
    return "待补充" in section_text


def replace_section(section_text: str, llm_text: str | None) -> str:
    """替换核心业务段内的占位行为生成正文，保留段内其他内容（空行、结构行）原样。

    - llm_text 非 None: 占位行 → 校验注释 + 正文
    - llm_text None: 占位行 → 失败注释 + "待补充"
    清理上一次失败遗留的"LLM 生成失败"注释行。
    保留占位行之后的结构行（如"- 所属指数：[[indices/000300]]"）和段尾空行。
    """
    lines = section_text.split("\n")
    out: list[str] = []
    for line in lines:
        # 清理上一次失败遗留的注释行（成功重跑时也要清）
        if "LLM 生成失败" in line or "LLM 生成，待人工校验" in line:
            continue
        if "待补充" in line:
            if llm_text:
                out.append("<!-- LLM 生成，待人工校验 -->")
                out.append(llm_text)
            else:
                out.append("<!-- LLM 生成失败，待重试 -->")
                out.append("待补充")
            continue  # 跳过原占位行
        out.append(line)
    return "\n".join(out)

PROMPT = """请为以下 A 股股票写一段核心业务简介（2-3 句，约 80-120 字）。

股票代码：{code}
股票名称：{name}
所属行业：{industry}
概念标签：{concept}
PE(TTM)：{pe_ttm}
PB：{pb}
市值：{market_cap}

要求：
1. 主营业务描述（从公司名和行业推断，不臆造具体数据）
2. 行业地位/竞争格局（如"龙头"/"前三"/"细分赛道"）
3. 核心壁垒/特色（1 句）

格式：纯文本，2-3 句，不含 markdown 标记。直接输出正文，不要思考过程。"""


def load_llm_config() -> tuple[str, str, str]:
    """从 backend/.env 读 LLM 配置。"""
    load_dotenv(ENV_FILE)
    base = os.environ.get("VR_LLM_BASE_URL", "").strip()
    key = os.environ.get("VR_LLM_API_KEY", "").strip()
    model = os.environ.get("VR_LLM_MODEL", "").strip()
    if not all([base, key, model]):
        raise SystemExit(f"LLM 配置缺失: base={base!r} model={model!r} key={'有' if key else '无'}")
    return base, key, model


def make_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕全局代理（百炼走内网 Tailscale HTTPS 自签证书）
    return s


def call_llm(session: requests.Session, base: str, key: str, model: str, prompt: str, timeout: int = 120) -> str | None:
    """调百炼 LLM，返回正文或 None。

    deepseek-v4-pro 是推理模型，reasoning_content 不算在 content 里但算
    completion_tokens；max_tokens 必须给足（≥4096）否则 content 为空。
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = session.post(
            f"{base}/chat/completions",
            json=payload, headers=headers,
            verify=False, timeout=timeout,
        )
    except requests.RequestException as e:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return None
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError):
        return None
    content = (choice.get("message") or {}).get("content") or ""
    content = content.strip()
    # 去除可能残留的 markdown 标记和首尾引号
    content = content.strip("`").strip()
    return content or None


def parse_frontmatter(text: str) -> dict:
    """解析 YAML frontmatter 为 dict（简易解析，不依赖 pyyaml）。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm


def find_business_placeholder(text: str) -> tuple[int, int, str] | None:
    """检查文件是否含"待补充"占位，返回 (段起始, 段结束, 段文本) 或 None。"""
    span = find_business_section(text)
    if not span:
        return None
    start, end = span
    section = text[start:end]
    if not is_placeholder_section(section):
        return None
    return start, end, section


def build_replacement(llm_text: str, tail_lines: str) -> str:
    """构造替换文本：标题 + 空行 + 注释 + 正文 + tail（保留"所属指数"等结构行）。

    tail_lines 是占位行之后的非空行内容（如"- 所属指数：[[indices/000300]]"），
    这些是数据结构行，应保留。
    """
    annotation = "<!-- LLM 生成，待人工校验 -->\n"
    body = f"{annotation}{llm_text}\n"
    if tail_lines.strip():
        # 保留 tail，但确保前面有空行分隔
        tail = tail_lines.rstrip() + "\n"
        return f"## 📊 核心业务\n\n{body}{tail}"
    return f"## 📊 核心业务\n\n{body}"


def build_failed_replacement(tail_lines: str) -> str:
    """LLM 失败时的占位替换。"""
    body = "<!-- LLM 生成失败，待重试 -->\n待补充\n"
    if tail_lines.strip():
        tail = tail_lines.rstrip() + "\n"
        return f"## 📊 核心业务\n\n{body}{tail}"
    return f"## 📊 核心业务\n\n{body}"


def process_one(stock_path: Path, session: requests.Session, base: str, key: str, model: str) -> dict:
    """处理单只股票，返回结果 dict。"""
    code = stock_path.stem
    try:
        text = stock_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"code": code, "status": "error", "reason": f"读文件失败: {e}"}

    span = find_business_placeholder(text)
    if not span:
        return {"code": code, "status": "skip", "reason": "无占位或已填充"}

    start, end, section = span

    fm = parse_frontmatter(text)
    name = fm.get("name", code)
    industry = fm.get("industry", "待核实")
    concept = fm.get("concept", "")
    pe_ttm = fm.get("pe_ttm", "")
    pb = fm.get("pb", "")
    market_cap = fm.get("market_cap", "")

    prompt = PROMPT.format(
        code=code, name=name, industry=industry, concept=concept or "（无）",
        pe_ttm=pe_ttm, pb=pb, market_cap=market_cap,
    )

    llm_text = call_llm(session, base, key, model, prompt)
    # 用新的逐行替换逻辑生成新段
    new_section = replace_section(section, llm_text)
    new_text = text[:start] + new_section + text[end:]
    try:
        stock_path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"code": code, "status": "error", "reason": f"写文件失败: {e}"}

    if llm_text:
        return {"code": code, "status": "ok", "name": name, "industry": industry,
                "text": llm_text}
    return {"code": code, "status": "failed", "reason": "LLM 返回空",
            "name": name, "industry": industry}


def main():
    ap = argparse.ArgumentParser(description="批量补充股票核心业务段")
    ap.add_argument("-n", "--concurrency", type=int, default=8, help="并发线程数")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 只(测试用, 0=全部)")
    ap.add_argument("--dry-run", action="store_true", help="只扫描不调 LLM 不写文件")
    ap.add_argument("--timeout", type=int, default=120, help="单只 LLM 超时秒数")
    args = ap.parse_args()

    base, key, model = load_llm_config()
    print(f"[配置] base={base}  model={model}  并发={args.concurrency}")

    # 扫描待补充股票
    files = sorted(VAULT_STOCKS.glob("*.md"))
    files = [f for f in files if f.stem != "index"]

    pending = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if find_business_placeholder(text):
            pending.append(f)

    print(f"[扫描] 股票文件 {len(files)} 只, 待补充 {len(pending)} 只, 已填充 {len(files)-len(pending)} 只")

    if args.dry_run:
        print("[dry-run] 不调 LLM, 退出。")
        return

    if args.limit > 0:
        pending = pending[:args.limit]
        print(f"[limit] 只处理前 {len(pending)} 只")

    if not pending:
        print("[完成] 没有待补充的股票。")
        return

    session = make_session()
    results = []
    t0 = time.time()
    ok_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(process_one, f, session, base, key, model): f for f in pending}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"code": f.stem, "status": "error", "reason": f"异常: {e}"}
            results.append(r)
            if r["status"] == "ok":
                ok_count += 1
            elif r["status"] == "failed":
                fail_count += 1
            elapsed = time.time() - t0
            # 进度日志
            status_icon = {"ok": "✓", "failed": "✗", "error": "!", "skip": "-"}.get(r["status"], "?")
            name = r.get("name", "")
            print(f"[{i}/{len(pending)}] {status_icon} {r['code']} {name[:8]:<8}  "
                  f"累计 ok={ok_count} fail={fail_count}  耗时={elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"\n[完成] 共 {len(pending)} 只: 成功 {ok_count}, 失败 {fail_count}, "
          f"异常 {len(results)-ok_count-fail_count}, 耗时 {elapsed:.0f}s")

    # 生成报告
    write_report(results, ok_count, fail_count, elapsed, args.concurrency)


def write_report(results: list[dict], ok: int, fail: int, elapsed: float, concurrency: int):
    """生成 docs/stock-business-fill-report.md 统计报告。"""
    DOCS.mkdir(parents=True, exist_ok=True)
    report_path = DOCS / "stock-business-fill-report.md"

    errors = [r for r in results if r["status"] in ("failed", "error")]
    oks = [r for r in results if r["status"] == "ok"]

    lines = [
        "# 股票核心业务段 LLM 批量填充报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 耗时：{elapsed:.0f} 秒（{elapsed/60:.1f} 分钟）",
        f"> 并发：{concurrency} 线程",
        "",
        "## 统计",
        "",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| 待处理 | {len(results)} |",
        f"| 成功 | {ok} |",
        f"| 失败 | {fail} |",
        f"| 异常 | {len(results)-ok-fail} |",
        f"| 成功率 | {ok/len(results)*100:.1f}% |" if results else "| 成功率 | - |",
        "",
        "## 成功示例（前 5 条）",
        "",
    ]
    for r in oks[:5]:
        lines.append(f"### {r['code']} {r.get('name','')}（{r.get('industry','')}）")
        lines.append("")
        lines.append("> " + r["text"].replace("\n", "\n> "))
        lines.append("")

    if errors:
        lines.append("## 失败/异常列表")
        lines.append("")
        lines.append("| 代码 | 名称 | 状态 | 原因 |")
        lines.append("|---|---|---|---|")
        for r in errors:
            lines.append(f"| {r['code']} | {r.get('name','')} | {r['status']} | {r.get('reason','')} |")

    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 成功填充的段落均带 `<!-- LLM 生成，待人工校验 -->` 注释，需人工抽查校验。")
    lines.append("- 失败的段落标 `<!-- LLM 生成失败，待重试 -->` + `待补充`，可重跑本脚本自动跳过已填充、只处理失败项。")
    lines.append("- LLM 模型：`deepseek-v4-pro`（推理模型，reasoning 占 ~2000 tokens，max_tokens 设 4096）。")
    lines.append("- 不改 frontmatter，不改其他段（财务/估值/研报等）。")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[报告] 已生成 {report_path}")


if __name__ == "__main__":
    main()
