"""S007 契约层 — 龙虎榜 / 席位明细模型。

S008 T13e 新增。对齐 astock.dragon_tiger_board / eastmoney_datacenter 返回：
- DragonTiger：龙虎榜（records 席位明细 + institution 机构净额）
- DragonTigerRecord：单条席位明细（net_buy 净买入额，元）
- BillboardDetail：东财龙虎榜明细行（BUY/SELL/NET/SECURITY_CODE/TRADE_DATE/OPERATEDEPT_NAME）

注：DragonTiger.records 来自 dragon_tiger_board（席位净买口径）；
BillboardDetail 来自 eastmoney_datacenter billboard（买卖额明细口径）——
两者数据源不同、字段不同，并列不互投。
"""

from pydantic import BaseModel, ConfigDict


class DragonTigerRecord(BaseModel):
    """龙虎榜单条席位明细。"""

    model_config = ConfigDict(frozen=True)

    net_buy: float | None = None  # 净买入额，元


class DragonTiger(BaseModel):
    """龙虎榜（席位明细 + 机构净额）。"""

    model_config = ConfigDict(frozen=True)

    records: tuple[DragonTigerRecord, ...] = ()
    institution_net: float | None = None  # 机构净额，元


class BillboardDetail(BaseModel):
    """东财龙虎榜明细行（买卖额口径）。"""

    model_config = ConfigDict(frozen=True)

    buy: float | None = None  # BUY，元
    sell: float | None = None  # SELL，元
    net: float | None = None  # NET，元
    security_code: str | None = None  # SECURITY_CODE
    trade_date: str | None = None  # TRADE_DATE（YYYY-MM-DD）
    operate_dept_name: str | None = None  # OPERATEDEPT_NAME 席位名
    operate_dept_code: str | None = None  # OPERATEDEPT_CODE 席位代码（"0"=机构专用）
