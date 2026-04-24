"""交易域枚举定义"""

import enum


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    wechat = "wechat"
    alipay = "alipay"
    unionpay = "unionpay"
    credit_account = "credit_account"  # 挂账
    member_balance = "member_balance"  # 会员余额
    coupon = "coupon"  # 优惠券
    mixed = "mixed"  # 混合支付


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    refund_pending = "refund_pending"
    refunded = "refunded"
    partial_refund = "partial_refund"
    failed = "failed"


class TableStatus(str, enum.Enum):
    free = "free"
    occupied = "occupied"
    reserved = "reserved"
    cleaning = "cleaning"


class OrderType(str, enum.Enum):
    dine_in = "dine_in"  # 堂食（桌台就餐）
    takeout = "takeout"  # 外带（到店自取，柜台即点即付）
    delivery = "delivery"  # 外卖（平台配送：美团/饿了么/抖音）
    banquet = "banquet"  # 宴席（包场预订）
    self_pickup = "self_pickup"  # 自提（线上下单，到店自提，凭取餐码提货）
    retail = "retail"  # 零售（商品零售，非餐饮，如伴手礼/预制菜）


class PayMode(str, enum.Enum):
    """支付时序模式 — 区域/会话级别"""

    prepay = "prepay"  # 先付后餐（快餐/外带/自提默认）
    postpay = "postpay"  # 先餐后付（堂食默认）


class SettlementType(str, enum.Enum):
    daily = "daily"  # 日结
    shift = "shift"  # 班结


class RefundType(str, enum.Enum):
    full = "full"  # 整单退
    partial = "partial"  # 部分退


class PrintType(str, enum.Enum):
    receipt = "receipt"  # 客户小票
    kitchen = "kitchen"  # 厨房单
    add_dish = "add_dish"  # 加菜单
    shift_report = "shift_report"  # 交接班报表


class ReservationStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    arrived = "arrived"
    queuing = "queuing"
    seated = "seated"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class ReservationType(str, enum.Enum):
    regular = "regular"
    banquet = "banquet"
    private_room = "private_room"
    outdoor = "outdoor"
    vip = "vip"


class QueueStatus(str, enum.Enum):
    waiting = "waiting"
    called = "called"
    arrived = "arrived"
    seated = "seated"
    skipped = "skipped"
    cancelled = "cancelled"


class QueueSource(str, enum.Enum):
    walk_in = "walk_in"
    meituan = "meituan"
    reservation = "reservation"
    wechat = "wechat"


class ServiceMode(str, enum.Enum):
    """服务模式 — 区域级别，决定订单全流程走向"""
    dine_first = "dine_first"      # 先吃后付（包厢/卡座/正餐堂食）
    scan_and_pay = "scan_and_pay"  # 扫码即付（大厅快餐/茶饮/自助）
    retail = "retail"              # 纯零售（便利店窗口/外带柜台，无桌台无会话）
