"""S007 契约层 — 共享枚举。"""

from enum import Enum


class Market(str, Enum):
    """市场类型（A/美/港/韩）。"""

    A = "A"
    US = "US"
    HK = "HK"
    KR = "KR"


class ReportType(str, Enum):
    """研报评级。"""

    BUY = "买入"
    OVERWEIGHT = "增持"
    NEUTRAL = "中性"
    UNDERWEIGHT = "减持"
    SELL = "卖出"


class STIPhase(str, Enum):
    """STI 情绪周期阶段。"""

    HIGH = "高潮"
    START = "启动"
    DIVERGE = "分歧"
    LOW = "冰点"
    EBB = "退潮"
