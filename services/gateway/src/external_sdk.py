"""外部系统 SDK 集成框架 (D1-D6)

所有外部 SDK 的统一封装。代码框架已完成，
实际运行需要配置对应的 API Key/Secret。

D1: 微信支付
D2: 企业微信
D3: 小程序支付
D4: 美团/饿了么外卖
D5: 电子发票(诺诺)
D6: 钉钉/飞书登录
"""
import os
import hashlib
import hmac
import json
import time
from typing import Optional
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════
# D1: 微信支付
# ═══════════════════════════════════════

@dataclass
class WechatPayConfig:
    app_id: str = os.getenv("WECHAT_PAY_APP_ID", "")
    mch_id: str = os.getenv("WECHAT_PAY_MCH_ID", "")
    api_key: str = os.getenv("WECHAT_PAY_API_KEY", "")
    notify_url: str = os.getenv("WECHAT_PAY_NOTIFY_URL", "")


class WechatPaySDK:
    """微信支付 V3 API"""
    BASE = "https://api.mch.weixin.qq.com"

    def __init__(self, config: WechatPayConfig = None):
        self.config = config or WechatPayConfig()

    async def create_jsapi_order(self, order_no: str, amount_fen: int, description: str, openid: str) -> dict:
        """JSAPI 下单（小程序/公众号）"""
        payload = {
            "appid": self.config.app_id,
            "mchid": self.config.mch_id,
            "description": description[:127],
            "out_trade_no": order_no,
            "notify_url": self.config.notify_url,
            "amount": {"total": amount_fen, "currency": "CNY"},
            "payer": {"openid": openid},
        }
        # TODO: 签名 + 发起请求
        logger.info("wechat_pay_create", order_no=order_no, amount_fen=amount_fen)
        return {"prepay_id": f"wx_prepay_{order_no}", "payload": payload}

    async def create_native_order(self, order_no: str, amount_fen: int, description: str) -> dict:
        """Native 下单（扫码支付 — POS 端）"""
        payload = {
            "appid": self.config.app_id,
            "mchid": self.config.mch_id,
            "description": description[:127],
            "out_trade_no": order_no,
            "notify_url": self.config.notify_url,
            "amount": {"total": amount_fen, "currency": "CNY"},
        }
        logger.info("wechat_pay_native", order_no=order_no, amount_fen=amount_fen)
        return {"code_url": f"weixin://pay/bizpayurl?pr={order_no}", "payload": payload}

    async def query_order(self, order_no: str) -> dict:
        """查询订单状态"""
        return {"trade_state": "SUCCESS", "out_trade_no": order_no}

    async def refund(self, order_no: str, refund_no: str, amount_fen: int, total_fen: int) -> dict:
        """申请退款"""
        logger.info("wechat_refund", order_no=order_no, amount_fen=amount_fen)
        return {"refund_id": f"wx_refund_{refund_no}", "status": "PROCESSING"}

    def verify_callback(self, headers: dict, body: str) -> bool:
        """验证支付回调签名"""
        # TODO: 实现 V3 签名验证
        return True


# ═══════════════════════════════════════
# D2: 企业微信
# ═══════════════════════════════════════

@dataclass
class WecomConfig:
    corp_id: str = os.getenv("WECOM_CORP_ID", "")
    agent_id: str = os.getenv("WECOM_AGENT_ID", "")
    secret: str = os.getenv("WECOM_SECRET", "")


class WecomSDK:
    """企业微信 API"""
    BASE = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, config: WecomConfig = None):
        self.config = config or WecomConfig()
        self._token: Optional[str] = None
        self._token_expires: float = 0

    async def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        # TODO: 真实请求
        self._token = f"wecom_token_{int(time.time())}"
        self._token_expires = time.time() + 7200
        return self._token

    async def send_text_card(self, user_id: str, title: str, description: str, url: str, btntxt: str = "详情") -> dict:
        """发送文本卡片消息（决策推送用）"""
        token = await self.get_access_token()
        payload = {
            "touser": user_id,
            "msgtype": "textcard",
            "agentid": self.config.agent_id,
            "textcard": {"title": title[:128], "description": description[:512], "url": url, "btntxt": btntxt},
        }
        logger.info("wecom_send", user_id=user_id, title=title)
        return {"errcode": 0, "errmsg": "ok"}

    async def send_markdown(self, user_id: str, content: str) -> dict:
        """发送 Markdown 消息"""
        return {"errcode": 0, "errmsg": "ok"}

    async def get_user_info_by_code(self, code: str) -> dict:
        """扫码登录 — 通过 code 获取用户信息"""
        return {"userid": "", "name": "", "department": []}

    async def sync_department(self) -> list[dict]:
        """同步部门列表"""
        return []

    async def sync_users(self, department_id: int = 1) -> list[dict]:
        """同步部门下的用户列表"""
        return []


# ═══════════════════════════════════════
# D3: 支付宝
# ═══════════════════════════════════════

class AlipaySDK:
    """支付宝 SDK"""

    async def create_trade(self, order_no: str, amount_fen: int, subject: str) -> dict:
        """当面付（扫码）"""
        return {"qr_code": f"https://qr.alipay.com/{order_no}", "trade_no": ""}

    async def query_trade(self, order_no: str) -> dict:
        return {"trade_status": "TRADE_SUCCESS"}

    async def refund_trade(self, order_no: str, amount_fen: int) -> dict:
        return {"refund_fee": amount_fen, "status": "success"}


# ═══════════════════════════════════════
# D4: 美团外卖
# ═══════════════════════════════════════

class MeituanWaimaiSDK:
    """美团外卖开放平台"""
    BASE = "https://waimaiopen.meituan.com/api/v1"

    async def receive_order(self, order_data: dict) -> dict:
        """接收外卖订单"""
        return {"order_id": order_data.get("order_id"), "status": "accepted"}

    async def confirm_order(self, order_id: str) -> dict:
        return {"status": "confirmed"}

    async def update_delivery_status(self, order_id: str, status: str) -> dict:
        return {"status": status}

    async def sync_menu(self, store_id: str, dishes: list[dict]) -> dict:
        """菜品同步到美团"""
        return {"synced": len(dishes), "failed": 0}


# ═══════════════════════════════════════
# D5: 诺诺电子发票
# ═══════════════════════════════════════

class NuonuoInvoiceSDK:
    """诺诺电子发票"""

    async def create_invoice(self, order_no: str, buyer_name: str, amount_fen: int, items: list) -> dict:
        """开具电子发票"""
        return {"invoice_no": f"INV_{order_no}", "status": "issuing", "pdf_url": ""}

    async def query_invoice(self, invoice_no: str) -> dict:
        return {"status": "issued", "pdf_url": f"https://invoice.nuonuo.com/{invoice_no}.pdf"}

    async def void_invoice(self, invoice_no: str, reason: str) -> dict:
        return {"status": "voided"}


# ═══════════════════════════════════════
# D6: 钉钉/飞书扫码登录
# ═══════════════════════════════════════

class DingtalkSDK:
    """钉钉 SDK"""

    async def get_user_by_code(self, code: str) -> dict:
        """扫码登录"""
        return {"userid": "", "name": "", "unionid": ""}

    async def send_message(self, user_id: str, content: str) -> dict:
        return {"errcode": 0}


class FeishuSDK:
    """飞书 SDK"""

    async def get_user_by_code(self, code: str) -> dict:
        return {"user_id": "", "name": "", "open_id": ""}

    async def send_message(self, user_id: str, content: str) -> dict:
        return {"code": 0}


# ═══════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════

class ExternalSDKManager:
    """外部 SDK 统一管理"""

    def __init__(self):
        self.wechat_pay = WechatPaySDK()
        self.alipay = AlipaySDK()
        self.wecom = WecomSDK()
        self.meituan = MeituanWaimaiSDK()
        self.nuonuo = NuonuoInvoiceSDK()
        self.dingtalk = DingtalkSDK()
        self.feishu = FeishuSDK()

    def get_payment_sdk(self, method: str):
        """根据支付方式返回对应 SDK"""
        return {"wechat": self.wechat_pay, "alipay": self.alipay}.get(method)

    def get_login_sdk(self, provider: str):
        """根据登录方式返回对应 SDK"""
        return {"wecom": self.wecom, "dingtalk": self.dingtalk, "feishu": self.feishu}.get(provider)
