"""支付渠道抽象基类 — 所有渠道必须实现

设计原则：
  1. 统一接口：pay / query / refund / verify_callback 四个原子操作
  2. 金额单位：分（int），不使用浮点
  3. 渠道无状态：Channel 实例不持有数据库连接，由 Orchestrator 管理事务
  4. 可测试：每个渠道可独立 mock，不依赖其他渠道
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ─── 支付方式枚举（全局统一） ───────────────────────────────────────────


class PayMethod(str, Enum):
    """支付方式 — tx-pay 全局统一枚举"""

    WECHAT = "wechat"  # 微信支付
    ALIPAY = "alipay"  # 支付宝
    UNIONPAY = "unionpay"  # 银联
    CASH = "cash"  # 现金
    MEMBER_BALANCE = "member_balance"  # 会员储值余额
    CREDIT_ACCOUNT = "credit_account"  # 企业挂账
    COUPON = "coupon"  # 优惠券抵扣
    DIGITAL_RMB = "digital_rmb"  # 数字人民币（预留）


class PayStatus(str, Enum):
    """支付状态"""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CLOSED = "closed"
    REFUNDED = "refunded"
    PARTIAL_REFUND = "partial_refund"


class TradeType(str, Enum):
    """交易类型"""

    B2C = "b2c"  # B扫C（商户扫顾客条码）
    C2B = "c2b"  # C扫B（顾客扫商户码）
    JSAPI = "jsapi"  # JSAPI（小程序/公众号内支付）
    APP = "app"  # APP支付
    H5 = "h5"  # H5支付
    NATIVE = "native"  # Native（生成二维码）


# ─── 统一请求/响应模型 ────────────────────────────────────────────────


class PaymentRequest(BaseModel):
    """统一支付请求 — 所有渠道入参的超集"""

    tenant_id: str
    store_id: str
    order_id: str
    amount_fen: int = Field(..., gt=0, description="支付金额（分）")
    method: PayMethod
    trade_type: TradeType = TradeType.B2C
    auth_code: Optional[str] = None  # B扫C 条码
    openid: Optional[str] = None  # JSAPI 场景
    description: str = ""  # 商品描述
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="幂等键（格式：{device_id}-{order_id[:8]}-{unix_ts}）",
    )
    notify_url: Optional[str] = None  # 异步通知地址
    metadata: dict = Field(default_factory=dict)  # 业务扩展字段


class PaymentResult(BaseModel):
    """统一支付结果"""

    payment_id: str
    status: PayStatus
    method: PayMethod
    amount_fen: int
    trade_no: Optional[str] = None  # 第三方流水号
    paid_at: Optional[datetime] = None
    channel_data: dict = Field(default_factory=dict)  # 渠道特有数据（prepay_id 等）
    error_code: Optional[str] = None
    error_msg: Optional[str] = None


class RefundResult(BaseModel):
    """统一退款结果"""

    refund_id: str
    payment_id: str
    status: str  # success / pending / failed
    amount_fen: int
    refund_trade_no: Optional[str] = None  # 第三方退款流水号
    refunded_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_msg: Optional[str] = None


class CallbackPayload(BaseModel):
    """回调解析结果"""

    payment_id: str
    trade_no: str
    status: PayStatus
    amount_fen: int
    paid_at: Optional[datetime] = None
    raw: dict = Field(default_factory=dict)  # 原始回调数据（留存审计）


# ─── 渠道抽象基类 ─────────────────────────────────────────────────────


class BasePaymentChannel(ABC):
    """支付渠道抽象基类

    所有第三方支付渠道（微信/支付宝/拉卡拉/收钱吧等）
    和内部支付渠道（现金/储值/挂账）都必须实现此接口。
    """

    # 渠道标识（子类必须覆盖）
    channel_name: str = ""
    supported_methods: list[PayMethod] = []
    supported_trade_types: list[TradeType] = []

    @abstractmethod
    async def pay(self, request: PaymentRequest) -> PaymentResult:
        """发起支付

        B2C 场景：同步返回结果（收钱吧/拉卡拉扫码枪）
        C2B/JSAPI 场景：返回 pending + prepay_id/qr_code
        """

    @abstractmethod
    async def query(self, payment_id: str, trade_no: Optional[str] = None) -> PaymentResult:
        """查询支付状态

        用于轮询确认和对账。
        """

    @abstractmethod
    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        """退款

        支持全额退款和部分退款。refund_id 用于幂等。
        """

    async def close(self, payment_id: str) -> bool:
        """关闭未支付的交易（可选实现）

        默认返回 True（现金/储值等无需关闭）。
        """
        return True

    async def verify_callback(self, headers: dict, body: bytes) -> CallbackPayload:
        """验证回调签名并解析数据（可选实现）

        仅在线支付渠道需要实现（微信/支付宝）。
        现金/储值/挂账无回调，默认抛出异常。
        """
        raise NotImplementedError(f"{self.channel_name} 不支持异步回调")

    def supports(self, method: PayMethod, trade_type: TradeType) -> bool:
        """检查渠道是否支持指定的支付方式和交易类型"""
        return method in self.supported_methods and trade_type in self.supported_trade_types
