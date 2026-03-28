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
    dine_in = "dine_in"
    takeout = "takeout"
    delivery = "delivery"
    banquet = "banquet"


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
