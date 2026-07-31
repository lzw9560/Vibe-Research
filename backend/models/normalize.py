"""S007 契约层 — 代码归一化。"""

from models.enums import Market


def normalize_stock_code(code: str | None) -> tuple[str, Market]:
    """将各类股票代码归一化为 (code, Market)。

    支持格式：
    - A 股：6 位数字（如 600519）
    - 港股：5 位数字（如 00700）
    - 美股：ticker（如 AAPL）
    - 韩股：6 位数字，可选 .KS 后缀（如 005930.KS → 005930）
    """
    if not code:
        raise ValueError("code cannot be empty or None")

    code = code.strip()

    if code.endswith(".KS"):
        return (code[:-3], Market.KR)

    if code.isdigit():
        if len(code) == 6:
            # 6 位纯数字默认 A 股（本项目 A 股优先；韩股识别依赖 .KS 后缀）
            return (code, Market.A)
        if len(code) == 5:
            return (code, Market.HK)
        # 其余纯数字长度（非 5/6 位）：兜底归韩股，调用方应优先带 .KS 后缀
        return (code, Market.KR)

    # 美股 ticker（非数字或数字+字母混合）
    return (code, Market.US)
