"""S007 契约层 — 龙虎榜 / 席位明细模型。

S008 T13e 新增。对齐 astock.dragon_tiger_board / eastmoney_datacenter 返回：
- DragonTiger：龙虎榜（records 席位明细 + institution 机构净额 + buy/sell_seats 买卖 TOP5 席位）
- DragonTigerRecord：单条上榜记录净买额（元）
- Seat：买卖 TOP5 席位明细（name + buy_amt/sell_amt/net，万元；S085 A2 新增）
- BillboardDetail：东财龙虎榜明细行（BUY/SELL/NET/SECURITY_CODE/TRADE_DATE/OPERATEDEPT_NAME）

注：DragonTiger.records 来自 dragon_tiger_board（席位净买口径）；
BillboardDetail 来自 eastmoney_datacenter billboard（买卖额明细口径）——
两者数据源不同、字段不同，并列不互投。
S085 A2：buy_seats/sell_seats 复用 dragon_tiger_board 的 raw['seats']（name/buy_amt/sell_amt/net，
万元），与 BillboardDetail（元 + OPERATEDEPT_NAME）口径/单位不同，故新建独立 Seat 模型不复用 BillboardDetail。
"""

from pydantic import BaseModel, ConfigDict


class DragonTigerRecord(BaseModel):
    """龙虎榜单条上榜记录。"""

    model_config = ConfigDict(frozen=True)

    net_buy: float | None = None  # 净买入额，元


class Seat(BaseModel):
    """龙虎榜买卖 TOP5 单席位明细（S085 A2）。

    来源：eastmoney.dragon_tiger_board 的 raw['seats']['buy'/'sell']，
    字段 name/BUYAmt/SELLAmt/NET 均已换算为万元（见 eastmoney.py:400-408）。
    与 BillboardDetail（元 + OPERATEDEPT_NAME）口径不同，不复用。
    """

    model_config = ConfigDict(frozen=True)

    name: str | None = None  # OPERATEDEPT_NAME 席位名（营业部全名 / "机构专用"）
    buy_amt: float | None = None  # 买入额，万元
    sell_amt: float | None = None  # 卖出额，万元
    net: float | None = None  # 净额，万元


class DragonTiger(BaseModel):
    """龙虎榜（席位明细 + 机构净额 + 买卖 TOP5 席位）。"""

    model_config = ConfigDict(frozen=True)

    records: tuple[DragonTigerRecord, ...] = ()
    institution_net: float | None = None  # 机构净额，元
    # S085 A2：买卖 TOP5 席位明细（万元），默认空 tuple 保向后兼容；
    # institution_net 消费方（fund_flow R2 / first_board_filter dim7）不读此字段，新增不破坏。
    buy_seats: tuple[Seat, ...] = ()
    sell_seats: tuple[Seat, ...] = ()


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
