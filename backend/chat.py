"""系统 AI 对话层 —— function calling 循环（OpenAI 兼容）。

让网页内置 AI 在回答时自己调 astock 数据工具（查行情/估值/研报/新闻），
拿到客观数据再作答。兼容豆包 / DeepSeek / 任意 OpenAI 兼容端点。

合规（按 CLAUDE.md §1 弱合规 2026-07-30，私人投研助理定位）：
工具返回客观数据；system prompt 允许方向性研判 / 买卖时机 / 收益预期 / 操作建议，
但保留轻量风险提醒，守工程底线——判断须可复现（不臆造、可复算）、不承诺确定性保证。
用户是最终决策者（半自动化助手）。
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from urllib.parse import urlparse

import requests

import cli_runtime

# S010：工具表与派发改读声明式 registry（ai.tools），消除手写 TOOLS +
# _exec_tool 硬分支。导入 ai.tools 触发 stock_tools 注册 7 个工具。
import ai.tools  # noqa: F401 — 副作用：注册工具
from ai.tools import registry

MAX_ROUNDS = 6  # 工具调用最大轮数，防死循环
_TOOL_RESULT_CAP = 6000  # 单次工具结果注入上限（控 token）

# 投研分析框架：用户要「分析个股 / 给判断 / 下结论」时，AI 一律按这五维组织，
# 让弱模型也能输出结构化、覆盖全、不漏项的专业解读。焊进 SYSTEM_PROMPT，不做成 UI 选项——
# 用户就问，给出的就是这套框架的结论。合规（§1 弱合规）：框架规定「怎么读数据」，每维陈述事实
# 与相对位置，末尾可给方向性研判/买卖时机/操作建议（研究参考性，挂轻量风险提醒，用户最终决策）。
ANALYSIS_FRAMEWORK = """【投研分析框架】当用户要你分析个股、给判断或下结论时，按下面五个维度依次组织分析，每维用一两句讲清数据事实与相对位置，末尾给方向性研判与操作建议（研究参考性，市场有风险，用户最终决策）：
1. 估值：PE / PB / PS 的绝对水平 + 处在历史区间的高 / 中 / 低位 + 同业对比 + 机构一致预期的前向估值。
2. 资金面：主力资金流方向与强度 + 融资融券趋势 + 股东户数（筹码集中 / 分散）+ 龙虎榜 / 大宗异动。
3. 财报质量：营收与扣非净利增速是否匹配 + 经营现金流含金量 + 毛利 / 净利率趋势 + 资产负债率。
4. 行业景气：板块 / 概念归属 + 板块近期强弱 + 行业内相对排名 + 关联热门概念热度。
5. 事件催化与风险：重要公告 + 解禁 + 分红 + 舆情，客观分列「催化」与「风险」两栏。

输出组织（像专业研报那样排版，末尾给方向性研判与操作建议，但须挂「历史统计特征，市场有风险，研究参考」提醒，用户最终决策）：
- 结论先行：开头一句话概括当前基本面 / 估值 / 资金面处于什么状态 + 方向性研判，再附「关键数据速览」。
- 每个维度用「**加粗小标题** + 一小段展开」，别堆流水账数字。
- 有对比就上小表格（如估值 vs 同业、财报同比）。
- 末尾分列「方向性研判/操作建议」与「风险点」两栏，挂轻量风险提醒。
（简单的事实性问题——如"现价多少"——直接答，不必套用整个框架。）"""

# 用 f-string 先把框架焊进去，只留 {{context}} 给运行时 .format() 填——4 处调用点无需改。
SYSTEM_PROMPT = f"""你是 Vibe-Research 里的投研助理。你可以调用工具获取客观数据来支撑回答，A 股工具一律传 6 位代码：

- 行情估值：query_quote（批量行情）/ query_valuation（前向 PE、PEG）/ query_valuation_percentile（估值历史分位）/ query_kline（K 线与区间涨跌）
- 基本面：query_financials（营收净利 ROE 毛利率）/ query_company_info / query_reports（研报）/ query_news
- 资金筹码：query_fund_flow（主力净流入）/ query_margin（两融）/ query_holders（股东户数）/ query_block_trade / query_dragon_tiger / query_dividend
- 事件风险：query_announcements（公告）/ query_lockup（解禁）/ query_investor_qa（互动易）
- 行业板块：query_concepts（板块归属与热门概念）/ query_industry_comparison（行业强弱）/ query_industry_reports
- 市场层：query_market（scope=indices/global/emotion/turnover/overview）/ query_news_radar（赛道资讯）
- 海外：query_global_stock（美股 AAPL / 港股 00700 / 韩股 005930.KS）/ query_hk_cashflow（港股现金流量表，仅港股）

用工具的方式：**先想清楚要回答什么，再挑最相关的 2-5 个工具**，不要一次把所有工具都调一遍。
估值贵贱看 query_valuation_percentile，资金动向看 query_fund_flow，风险排查看 query_announcements + query_lockup。

规则（按 §1 弱合规，私人投研助理定位）：
- 可给方向性研判、买卖时机研判、收益预期（三情景测算）、模式识别、战法匹配、风险标注、明确操作建议——你是半自动化助手，给建议，用户是最终决策者。
- 需要数据时先调工具拿客观数据，再基于数据回答；判断须基于公开数据 + 既定规则可复算，不要编造数字、不要心算。
- 收益预期是研究参考性测算，不得承诺确定性保证（可给三情景概率/分位区间，不得说「必涨/必跌 X%」）。
- 涉及个股时用工具查到的真实数据；讲清多空两面与风险；研判输出挂轻量风险提醒「历史统计特征，市场有风险，研究参考」。
- 用简洁中文回答。

{ANALYSIS_FRAMEWORK}

当前页面上下文：
{{context}}"""

# 对不支持 function calling 的模型使用的精简版 system prompt（不提及工具）。
SYSTEM_PROMPT_NO_TOOLS = f"""你是 Vibe-Research 里的投研助理。

规则（按 §1 弱合规，私人投研助理定位）：
- 可给方向性研判、买卖时机研判、收益预期（三情景测算）、模式识别、战法匹配、风险标注、明确操作建议——你是半自动化助手，给建议，用户是最终决策者。
- 基于用户提供的客观数据回答；判断须基于公开数据 + 既定规则可复算，不要编造数字、不要心算。
- 收益预期是研究参考性测算，不得承诺确定性保证（可给三情景概率/分位区间，不得说「必涨/必跌 X%」）。
- 涉及个股时用提供的真实数据；讲清多空两面与风险；研判输出挂轻量风险提醒「历史统计特征，市场有风险，研究参考」。
- 用简洁中文回答。

{ANALYSIS_FRAMEWORK}

当前页面上下文：
{{context}}"""

# S010：声明式工具表——registry 反射 stock_tools 签名生成 schema，
# 与旧手写 TOOLS 逐字一致（见 tests/test_registry.py 比对）。mcp_server /
# cli_runtime 共读同一 registry。
TOOLS = registry.get_openai_tools()


# S010 后为 registry.execute 的薄壳：保留模块级属性名 `_exec_tool`
# 以兼容（1）mcp_server / routers 的 `chat._exec_tool(...)` 调用，
# （2）测试 `monkeypatch chat._exec_tool` 拦截 run_chat 工具调用。
# 派发与异常语义集中在 `tools.exec_tool`（经 _HANDLERS，支持 monkeypatch 兼容）。
from tools import exec_tool as _exec_tool  # noqa: E402 — 别名，使 chat._exec_tool is tools.exec_tool


# —— 防 SSRF：用户可自带 OpenAI 兼容端点，但后端替其发请求前要挡住指向云元数据/内网的地址 ——
_PUBLIC_MODE = bool(os.environ.get("VR_API_KEY", "").strip())  # 设了鉴权≈公网部署姿态
_METADATA_NETS = [ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("fe80::/10")]
_PRIVATE_NETS = [ipaddress.ip_network(n) for n in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")]


def _get_env_llm_config() -> dict:
    """从环境变量读 LLM 兜底配置（前端未传字段时补全）。

    读 VR_LLM_BASE_URL / VR_LLM_API_KEY / VR_LLM_MODEL，缺省返回空串。
    仅返回配置，不输出建议/标的/预测（合规）。不向非鉴权接口暴露敏感值。
    """
    return {
        "baseURL": os.getenv("VR_LLM_BASE_URL", ""),
        "apiKey": os.getenv("VR_LLM_API_KEY", ""),
        "model": os.getenv("VR_LLM_MODEL", ""),
    }


def _ip_blocked(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 非字面 IP（域名）——交给 _check_base_url 决定是否解析核对
    if any(ip in n for n in _METADATA_NETS):  # 云元数据 / 链路本地：SSRF 头号目标，始终禁
        return True
    if _PUBLIC_MODE and any(ip in n for n in _PRIVATE_NETS):  # 公网姿态再禁内网 / 本机
        return True
    return False


def _check_base_url(url: str) -> None:
    """挡住把用户自带 baseURL 指向云元数据 / 内网的 SSRF。
    本地单用户（未设 VR_API_KEY）放行 127.0.0.1 等本机地址（方便接本机 Ollama / 网关），只挡 169.254 元数据；
    公网部署（设了 VR_API_KEY）额外禁内网，并解析域名核对，防 DNS 指向内网。"""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https"):
        raise RuntimeError("Base URL 必须以 http:// 或 https:// 开头")
    host = p.hostname or ""
    if not host:
        raise RuntimeError("Base URL 缺少主机名")
    if _ip_blocked(host):
        raise RuntimeError("Base URL 指向了不允许的地址（云元数据 / 内网）")
    if _PUBLIC_MODE:  # 公网姿态：域名也解析核对，防 DNS rebinding 指向内网
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            raise RuntimeError("Base URL 域名无法解析") from e
        for info in infos:
            if _ip_blocked(info[4][0]):
                raise RuntimeError("Base URL 解析到了不允许的内网地址")


def _call_llm(cfg: dict, messages: list, use_tools: bool) -> dict:
    _check_base_url(cfg.get("baseURL", ""))
    base = cfg["baseURL"].rstrip("/")
    if not base.endswith(("/v1", "/v3", "/api/v3", "/v4")):
        # 多数 OpenAI 兼容端点需要 /v1；已带版本段则不动。
        base = base + "/v1"
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.3}
    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['apiKey']}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"模型接口 HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def run_chat(cfg: dict, user_messages: list, context: str = "") -> dict:
    """跑一轮完整对话（含 function calling 循环）。

    cfg: {baseURL, apiKey, model}
    user_messages: [{role, content}, ...]
    返回: {content, trace:[{tool,args}], rounds}
    """
    # Agnes 等不支持 function calling 的模型：用精简 prompt，跳过工具调用
    no_tools_cfg = str(cfg.get("provider", "")) == "agnes"
    sys_prompt = SYSTEM_PROMPT_NO_TOOLS.format(context=context or "（无）") if no_tools_cfg else SYSTEM_PROMPT.format(context=context or "（无）")
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(user_messages)
    trace: list[dict] = []

    if no_tools_cfg:
        # 非 function-calling 模式：直接调一次，返回答案
        data = _call_llm(cfg, messages, use_tools=False)
        return {"content": data["choices"][0]["message"].get("content") or "", "trace": [], "rounds": 1}

    for rnd in range(1, MAX_ROUNDS + 1):
        data = _call_llm(cfg, messages, use_tools=True)
        choice = data["choices"][0]["message"]
        messages.append(choice)
        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            return {"content": choice.get("content") or "", "trace": trace, "rounds": rnd}

        for tc in tool_calls:
            fn = tc["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _exec_tool(name, args)
            trace.append({"tool": name, "args": args})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False)[:_TOOL_RESULT_CAP],
            })

    # 超过最大轮数，最后再要一次不带工具的收尾回答
    data = _call_llm(cfg, messages, use_tools=False)
    return {"content": data["choices"][0]["message"].get("content") or "", "trace": trace, "rounds": MAX_ROUNDS}


def run_chat_cli(cfg: dict, user_messages: list, context: str = "") -> dict:
    """订阅接入：用本机已登录的 CLI 一次性作答（无 function-calling）。

    CLI 不能像 API 那条自己调数据工具，所以数据必须已在 context 里（每日复盘 / 今日要点 /
    个股页问 AI 等场景，前端已把当页数据塞进 context）。
    """
    provider = str(cfg.get("provider", ""))
    kind = provider[4:] if provider.startswith("cli-") else provider
    system = SYSTEM_PROMPT.format(context=context or "（无）")
    user = "\n\n".join(m.get("content", "") for m in user_messages if m.get("content")) or "（无问题）"
    content = cli_runtime.run_cli(kind, system, user)
    return {"content": content, "trace": [], "rounds": 1}


# ---------------------------------------------------------------------------
# 流式版：yield 事件字典 {type: tool|delta|done|error}，供 /api/chat 以 NDJSON 推给前端
# ---------------------------------------------------------------------------

def _resolve_base(cfg: dict) -> str:
    base = cfg["baseURL"].rstrip("/")
    if not base.endswith(("/v1", "/v3", "/api/v3", "/v4")):
        base = base + "/v1"
    return base


def _call_llm_stream(cfg: dict, messages: list, use_tools: bool):
    _check_base_url(cfg.get("baseURL", ""))
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.3, "stream": True}
    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    r = requests.post(
        f"{_resolve_base(cfg)}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['apiKey']}", "Content-Type": "application/json"},
        json=payload, timeout=120, stream=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"模型接口 HTTP {r.status_code}: {r.text[:300]}")
    return r


def _iter_sse_deltas(resp):
    """解析上游 SSE 流，逐个 yield choices[0].delta。

    按字节缓冲、只解码「完整行」——`\\n` 是 ASCII(0x0A)不会落在多字节 UTF-8 字符内部，
    故按 `\\n` 切分再解码，避免 iter_lines(decode_unicode=True) 在网络分块处切断中文导致乱码。
    """
    buf = b""
    for chunk in resp.iter_content(chunk_size=None):
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                j = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = j.get("choices") or []
            if choices:
                yield choices[0].get("delta") or {}


def run_chat_stream(cfg: dict, user_messages: list, context: str = ""):
    """API 接入流式：function-calling 循环，边流答案边推工具调用事件。"""
    no_tools_cfg = str(cfg.get("provider", "")) == "agnes"
    sys_prompt = SYSTEM_PROMPT_NO_TOOLS.format(context=context or "（无）") if no_tools_cfg else SYSTEM_PROMPT.format(context=context or "（无）")
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(user_messages)
    trace: list[dict] = []

    if no_tools_cfg:
        # 非 function-calling 模式：非流式调一次，逐字拆成 delta 推送
        data = _call_llm(cfg, messages, use_tools=False)
        text = data["choices"][0]["message"].get("content") or ""
        chunk_size = 4
        for i in range(0, len(text), chunk_size):
            yield {"type": "delta", "text": text[i:i+chunk_size]}
        yield {"type": "done", "trace": [], "rounds": 1}
        return

    for rnd in range(1, MAX_ROUNDS + 1):
        resp = _call_llm_stream(cfg, messages, use_tools=True)
        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        for delta in _iter_sse_deltas(resp):
            if delta.get("content"):
                content_parts.append(delta["content"])
                yield {"type": "delta", "text": delta["content"]}
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index")
                if idx is None:
                    # 非标「OpenAI 兼容」网关可能不带 index：有 id 按 id 归位（新 id 开新槽），
                    # 无 id 则续拼最后一个调用，避免多个调用的 arguments 串到一起
                    tc_id = tc.get("id") or ""
                    idx = next((k for k, v in tool_acc.items() if tc_id and v["id"] == tc_id), None)
                    if idx is None:
                        idx = len(tool_acc) if (tc_id or not tool_acc) else max(tool_acc)
                acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    acc["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    acc["name"] = fn["name"]
                if fn.get("arguments"):
                    acc["arguments"] += fn["arguments"]

        if not tool_acc:  # 本轮是纯答案（已流完）→ 结束
            yield {"type": "done", "trace": trace, "rounds": rnd}
            return

        # 有工具调用：回填 assistant 消息 + 执行工具 + 推事件
        messages.append({
            "role": "assistant",
            "content": "".join(content_parts) or None,
            "tool_calls": [{
                "id": tool_acc[i]["id"], "type": "function",
                "function": {"name": tool_acc[i]["name"], "arguments": tool_acc[i]["arguments"]},
            } for i in sorted(tool_acc)],
        })
        for i in sorted(tool_acc):
            a = tool_acc[i]
            try:
                args = json.loads(a["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "tool": a["name"], "args": args}
            result = _exec_tool(a["name"], args)
            trace.append({"tool": a["name"], "args": args})
            messages.append({
                "role": "tool", "tool_call_id": a["id"],
                "content": json.dumps(result, ensure_ascii=False)[:_TOOL_RESULT_CAP],
            })

    # 超过最大轮数：不带工具收尾（非流式一次拿完再吐）
    data = _call_llm(cfg, messages, use_tools=False)
    yield {"type": "delta", "text": data["choices"][0]["message"].get("content") or ""}
    yield {"type": "done", "trace": trace, "rounds": MAX_ROUNDS}


def run_chat_cli_stream(cfg: dict, user_messages: list, context: str = ""):
    """订阅接入流式：CLI stdout 边出边推 delta。"""
    provider = str(cfg.get("provider", ""))
    kind = provider[4:] if provider.startswith("cli-") else provider
    system = SYSTEM_PROMPT.format(context=context or "（无）")
    user = "\n\n".join(m.get("content", "") for m in user_messages if m.get("content")) or "（无问题）"
    for chunk in cli_runtime.run_cli_stream(kind, system, user):
        yield {"type": "delta", "text": chunk}
    yield {"type": "done", "trace": [], "rounds": 1}
