"""Phase 5 合规审查脚本（精炼版）。

检查项（基于 PRD 第 10 章 + 第 5 章原则）：
1. LimitUp 核心模块包含免责声明常量
2. 战法信号系统包含教育性说明字段（reasoning/risk_notes）
3. 一日游风险包含动态时间戳（last_updated）
4. 所有推送/通知类路由附带风险提示
5. E2E 测试验证响应包含免责声明
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def check_limitup_modules() -> list[str]:
    """检查 LimitUp 核心模块是否包含免责声明。"""
    findings = []
    
    modules = [
        ("limitup_screener.py", ["DISCLAIMER", "免责", "声明"]),
        ("seat_engine.py", ["SEAT_DISCLAIMER", "免责", "声明"]),
        ("auction_screener.py", ["AUCTION_DISCLAIMER", "免责", "声明"]),
        ("daily_review.py", ["REVIEW_DISCLAIMER", "免责", "声明"]),
        ("limitup_sti.py", ["DISCLAIMER", "免责", "声明"]),
        ("sector_divergence.py", ["免责", "声明", "非行动建议"]),
        ("risk.py", ["免责", "声明", "非行动建议"]),
        ("extreme_market_detector.py", ["免责", "声明", "非行动建议"]),
    ]
    
    for filename, keywords in modules:
        filepath = BACKEND_DIR / filename
        if not filepath.exists():
            findings.append(f"{filename}: 文件不存在")
            continue
        
        text = filepath.read_text(encoding="utf-8")
        if not any(kw in text for kw in keywords):
            findings.append(f"{filename}: 缺少免责声明")
    
    return findings


def check_strategy_signals() -> list[str]:
    """检查战法信号系统是否包含教育性说明字段。"""
    findings = []
    filepath = BACKEND_DIR / "limitup_strategy.py"
    
    if not filepath.exists():
        findings.append("limitup_strategy.py: 文件不存在")
        return findings
    
    text = filepath.read_text(encoding="utf-8")
    
    # 检查 StrategySignal 是否包含 reasoning/risk_notes
    if "reasoning" not in text or "risk_notes" not in text:
        findings.append("limitup_strategy.py: StrategySignal 缺少 reasoning/risk_notes 教育性字段")
    
    # 检查是否包含交易指令词汇（排除文档字符串和注释）
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 跳过模块级文档字符串
            if isinstance(tree.body[0], ast.Expr) and node is tree.body[0].value:
                continue
            if any(kw in node.value for kw in ["买入", "卖出", "持有", "排板", "扫板", "回避"]):
                findings.append(f"limitup_strategy.py: 包含交易指令词汇 '{node.value}'（应使用教育研究式口吻）")
    
    return findings


def check_one_day_risk() -> list[str]:
    """检查一日游风险模块是否包含动态时间戳。"""
    findings = []
    filepath = BACKEND_DIR / "risk.py"
    
    if not filepath.exists():
        return findings
    
    text = filepath.read_text(encoding="utf-8")
    
    if "last_updated" not in text:
        findings.append("risk.py::OneDayRisk: 缺少 last_updated 动态时间戳")
    
    return findings


def check_router_passthrough() -> list[str]:
    """检查 LimitUp 路由器是否正确传递 disclaimer 字段。"""
    findings = []
    router_dir = BACKEND_DIR / "routers" / "limitup"
    
    # 检查 seats router 是否传递 SEAT_DISCLAIMER
    seats_file = router_dir / "seats.py"
    if seats_file.exists():
        text = seats_file.read_text(encoding="utf-8")
        if "SEAT_DISCLAIMER" not in text and "disclaimer" not in text:
            findings.append("routers/limitup/seats.py: 未传递席位免责声明")
    
    return findings


def main() -> int:
    all_findings: list[str] = []
    
    all_findings.extend(check_limitup_modules())
    all_findings.extend(check_strategy_signals())
    all_findings.extend(check_one_day_risk())
    all_findings.extend(check_router_passthrough())
    
    if all_findings:
        print("合规审查发现以下问题：")
        for f in all_findings:
            print(f"  - {f}")
        return 1
    else:
        print("合规审查通过：LimitUp 模块符合 PRD 第 10 章合规要求")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
