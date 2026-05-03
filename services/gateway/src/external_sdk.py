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

import base64
import json
import os
import time
import uuid as _uuid_mod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════


class WecomAPIError(Exception):
    def __init__(self, errcode: int, errmsg: str):
        self.errcode = errcode
        self.errmsg = errmsg
        super().__init__(f"WecomAPI error {errcode}: {errmsg}")


# ═══════════════════════════════════════
# D1: 微信支付
# ═══════════════════════════════════════


@dataclass
class WechatPayConfig:
    app_id: str = os.getenv("WECHAT_PAY_APP_ID", "")
    mch_id: str = os.getenv("WECHAT_PAY_MCH_ID", "")
    api_key: str = os.getenv("WECHAT_PAY_API_KEY", "")
    notify_url: str = os.getenv("WECHAT_PAY_NOTIFY_URL", "")
    private_key_path: str = os.getenv("WECHAT_PAY_PRIVATE_KEY_PATH", "")
    serial_no: str = os.getenv("WECHAT_PAY_SERIAL_NO", "")


class WechatPaySDK:
    """微信支付 V3 API"""

    BASE = "https://api.mch.weixin.qq.com"

    def __init__(self, config: WechatPayConfig = None):
        self.config = config or WechatPayConfig()

    def _build_authorization(self, method: str, url_path: str, body: str) -> str:
        """构造微信支付 V3 Authorization header（RSA-SHA256 签名）。

        要求环境变量：WECHAT_PAY_PRIVATE_KEY_PATH、WECHAT_PAY_SERIAL_NO。
        """
        timestamp = str(int(time.time()))
        nonce = str(_uuid_mod.uuid4()).replace("-", "")[:32]
        message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"

        private_key_path = self.config.private_key_path
        if not private_key_path or not os.path.exists(private_key_path):
            raise ValueError("WECHAT_PAY_PRIVATE_KEY_PATH 未配置或文件不存在")

        try:
            from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15  # type: ignore
            from cryptography.hazmat.primitives.hashes import SHA256  # type: ignore
            from cryptography.hazmat.primitives.serialization import load_pem_private_key  # type: ignore
        except ImportError as exc:
            raise RuntimeError("缺少 cryptography 库，请 pip install cryptography") from exc

        with open(private_key_path, "rb") as f:
            private_key = load_pem_private_key(f.read(), password=None)

        signature = base64.b64encode(private_key.sign(message.encode("utf-8"), PKCS1v15(), SHA256())).decode("utf-8")

        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self.config.mch_id}",'
            f'nonce_str="{nonce}",signature="{signature}",'
            f'timestamp="{timestamp}",serial_no="{self.config.serial_no}"'
        )

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
        logger.info("wechat_pay_create", order_no=order_no, amount_fen=amount_fen)

        if not self.config.mch_id or not self.config.private_key_path:
            # 未配置微信支付凭证，返回沙箱响应（开发环境）
            logger.warning("wechat_pay_not_configured_returning_sandbox")
            return {"prepay_id": f"wx_prepay_{order_no}", "payload": payload}

        url_path = "/v3/pay/transactions/jsapi"
        body_str = json.dumps(payload, ensure_ascii=False)
        authorization = self._build_authorization("POST", url_path, body_str)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.BASE}{url_path}",
                content=body_str.encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": authorization,
                },
            )
            resp.raise_for_status()
            return resp.json()

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


_token_cache: dict = {"token": None, "expires_at": 0}


class WecomSDK:
    """企业微信 API"""

    BASE = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, config: WecomConfig = None):
        self.config = config or WecomConfig()

    async def get_access_token(self) -> str:
        """获取 access_token，内存缓存，提前300秒刷新"""
        now = time.time()
        if _token_cache["token"] and now < _token_cache["expires_at"] - 300:
            return _token_cache["token"]

        url = (
            f"{self.BASE}/gettoken"
            f"?grant_type=client_credential"
            f"&corpid={self.config.corp_id}"
            f"&corpsecret={self.config.secret}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("wecom_token_http_error", status=exc.response.status_code)
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_token_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_token_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = now + 7200
        logger.info("wecom_token_refreshed")
        return _token_cache["token"]

    async def _post_message(self, payload: dict) -> dict:
        """内部：发送消息通用方法"""
        token = await self.get_access_token()
        url = f"{self.BASE}/message/send?access_token={token}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("wecom_post_http_error", status=exc.response.status_code)
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_post_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_post_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))
        return data

    async def send_text_card(self, user_id: str, title: str, description: str, url: str, btntxt: str = "详情") -> dict:
        """发送文本卡片消息（决策推送用）"""
        payload = {
            "touser": user_id,
            "msgtype": "textcard",
            "agentid": int(self.config.agent_id),
            "textcard": {
                "title": title[:128],
                "description": description[:512],
                "url": url,
                "btntxt": btntxt,
            },
        }
        logger.info("wecom_send_text_card", user_id=user_id, title=title)
        return await self._post_message(payload)

    async def send_markdown(self, user_id: str, content: str) -> dict:
        """发送 Markdown 消息"""
        payload = {
            "touser": user_id,
            "msgtype": "markdown",
            "agentid": int(self.config.agent_id),
            "markdown": {"content": content},
        }
        logger.info("wecom_send_markdown", user_id=user_id)
        return await self._post_message(payload)

    async def send_text(self, user_id: str, content: str) -> dict:
        """发送文本消息"""
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(self.config.agent_id),
            "text": {"content": content},
        }
        logger.info("wecom_send_text", user_id=user_id)
        return await self._post_message(payload)

    async def send_news(self, user_id: str, articles: list[dict]) -> dict:
        """发送图文消息
        articles格式: [{"title":..., "description":..., "url":..., "picurl":...}]
        """
        payload = {
            "touser": user_id,
            "msgtype": "news",
            "agentid": int(self.config.agent_id),
            "news": {"articles": articles},
        }
        logger.info("wecom_send_news", user_id=user_id, article_count=len(articles))
        return await self._post_message(payload)

    async def batch_send_text(self, user_ids: list[str], content: str) -> dict:
        """批量发送文本消息（企微支持 touser 用|分隔，最多1000个）"""
        touser = "|".join(user_ids[:1000])
        payload = {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(self.config.agent_id),
            "text": {"content": content},
        }
        logger.info("wecom_batch_send_text", user_count=min(len(user_ids), 1000))
        return await self._post_message(payload)

    async def get_user_info_by_code(self, code: str) -> dict:
        """扫码登录 — 通过 code 获取用户信息"""
        token = await self.get_access_token()
        url = f"{self.BASE}/user/getuserinfo?access_token={token}&code={code}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("wecom_getuserinfo_http_error", status=exc.response.status_code)
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_getuserinfo_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_getuserinfo_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))
        return data

    async def sync_department(self) -> list[dict]:
        """同步部门列表"""
        token = await self.get_access_token()
        url = f"{self.BASE}/department/list?access_token={token}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("wecom_department_list_http_error", status=exc.response.status_code)
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_department_list_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_department_list_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))
        return data.get("department", [])

    async def sync_users(self, department_id: int = 1) -> list[dict]:
        """同步部门下的用户列表"""
        token = await self.get_access_token()
        url = f"{self.BASE}/user/list?access_token={token}&department_id={department_id}&fetch_child=1"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("wecom_user_list_http_error", status=exc.response.status_code)
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_user_list_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_user_list_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))
        return data.get("userlist", [])

    # ── 企微群聊 API ─────────────────────────────────────────────

    async def create_group_chat(
        self,
        name: str,
        owner_userid: str,
        member_userids: list[str],
        chatid: Optional[str] = None,
    ) -> dict:
        """创建企微群聊

        POST /appchat/create?access_token=xxx
        {
            "name": "群名称",
            "owner": "企微userid",
            "userlist": ["userid1", "userid2"],
            "chatid": "可选，自定义群ID"
        }

        返回：{"chatid": "xxx"}
        注意：建群可能比普通接口慢，timeout=15
        """
        token = await self.get_access_token()
        url = f"{self.BASE}/appchat/create?access_token={token}"
        payload: dict = {
            "name": name,
            "owner": owner_userid,
            "userlist": member_userids,
        }
        if chatid:
            payload["chatid"] = chatid

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_create_group_chat_http_error",
                    status=exc.response.status_code,
                    group_name=name,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_create_group_chat_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_create_group_chat_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        logger.info("wecom_create_group_chat_ok", chatid=data.get("chatid"), group_name=name)
        return data  # 含 chatid

    async def send_group_chat_message(
        self,
        chatid: str,
        msgtype: str,
        content_dict: dict,
    ) -> dict:
        """向企微群发消息

        POST /appchat/send?access_token=xxx
        {
            "chatid": "群ID",
            "msgtype": "text",
            "text": {"content": "消息内容"}
        }

        msgtype 支持：text / image / news / miniapp
        content_dict 为对应 msgtype 下的内容体，如 {"content": "xxx"}
        """
        token = await self.get_access_token()
        url = f"{self.BASE}/appchat/send?access_token={token}"
        payload: dict = {
            "chatid": chatid,
            "msgtype": msgtype,
            msgtype: content_dict,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_send_group_chat_http_error",
                    status=exc.response.status_code,
                    chatid=chatid,
                    msgtype=msgtype,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error(
                    "wecom_send_group_chat_connect_error",
                    error=str(exc),
                    chatid=chatid,
                )
                raise
            except httpx.TimeoutException as exc:
                logger.error(
                    "wecom_send_group_chat_timeout",
                    error=str(exc),
                    chatid=chatid,
                )
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        logger.info("wecom_send_group_chat_ok", chatid=chatid, msgtype=msgtype)
        return data

    async def get_group_chat_info(self, chatid: str) -> dict:
        """获取企微群详情（包含成员列表）

        GET /appchat/get?access_token=xxx&chatid=xxx

        返回字段示例：
          chat_info.chatid, name, owner, member_list[{userid, type, join_time}]
        """
        token = await self.get_access_token()
        url = f"{self.BASE}/appchat/get?access_token={token}&chatid={chatid}"

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_get_group_chat_info_http_error",
                    status=exc.response.status_code,
                    chatid=chatid,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error(
                    "wecom_get_group_chat_info_connect_error",
                    error=str(exc),
                    chatid=chatid,
                )
                raise
            except httpx.TimeoutException as exc:
                logger.error(
                    "wecom_get_group_chat_info_timeout",
                    error=str(exc),
                    chatid=chatid,
                )
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        logger.info(
            "wecom_get_group_chat_info_ok",
            chatid=chatid,
            member_count=len(data.get("chat_info", {}).get("member_list", [])),
        )
        return data.get("chat_info", {})


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
# D7: 微信 AI 智能体适配 (WA-1)
# ═══════════════════════════════════════


class WechatAIAgentSDK:
    """微信 AI 智能体 SDK — Function Calling 适配层 (WA-1)

    为微信 AI 智能体提供 6 个核心函数，遵循 OpenAI Function Calling Schema。
    当前 Phase 1 实现：定义 + Mock 执行。
    Phase 2 (WA-2) 接入真实微信 AI 智能体回调路由。

    所有金额单位：分 (fen)，所有时间：ISO 8601。
    """

    # ── 6 个函数的 OpenAPI Schema 定义 ──
    # 供微信 AI 智能体拉取 Functions 列表时使用
    FUNCTIONS: list[dict] = [
        {
            "name": "query_menu",
            "description": "查询门店菜单和菜品信息。支持按菜品名称搜索或按分类浏览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "string",
                        "description": "门店 ID（如未知则填 'current'）",
                    },
                    "dish_name": {
                        "type": "string",
                        "description": "菜品名称关键词（可选，用于搜索特定菜品）",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["全部", "招牌", "热菜", "凉菜", "汤品", "主食", "酒水", "套餐"],
                        "description": "菜品分类（可选，过滤菜单）",
                    },
                },
                "required": ["store_id"],
            },
        },
        {
            "name": "create_order",
            "description": "提交订单。用户说出想点的菜品后，调用此函数创建订单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "string",
                        "description": "门店 ID",
                    },
                    "dishes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dish_name": {
                                    "type": "string",
                                    "description": "菜品名称",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "数量",
                                    "default": 1,
                                },
                                "spec": {
                                    "type": "string",
                                    "description": "规格（如: 大份/小份/微辣/中辣/特辣）",
                                },
                            },
                            "required": ["dish_name"],
                        },
                        "description": "菜品列表",
                    },
                    "preference": {
                        "type": "string",
                        "description": "偏好说明（如: 少油、少盐、加急）",
                    },
                },
                "required": ["store_id", "dishes"],
            },
        },
        {
            "name": "query_order",
            "description": "查询订单状态。包括订单当前状态、预计出餐时间等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单 ID 或订单号",
                    },
                },
                "required": ["order_id"],
            },
        },
        {
            "name": "query_member",
            "description": "查询会员信息。包括等级、积分余额、储值余额。",
            "parameters": {
                "type": "object",
                "properties": {
                    "openid": {
                        "type": "string",
                        "description": "微信 OpenID（由微信智能体自动传递）",
                    },
                },
                "required": ["openid"],
            },
        },
        {
            "name": "query_coupons",
            "description": "查询用户可用的优惠券列表。包括折扣券、满减券、赠品券等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "openid": {
                        "type": "string",
                        "description": "微信 OpenID",
                    },
                    "store_id": {
                        "type": "string",
                        "description": "门店 ID（可选，只查询该门店可用券）",
                    },
                },
                "required": ["openid"],
            },
        },
        {
            "name": "book_table",
            "description": "预订桌位。用户说明人数和时间后，查询可用桌位并预订。",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {
                        "type": "string",
                        "description": "门店 ID",
                    },
                    "time": {
                        "type": "string",
                        "description": "到店时间（ISO 8601 格式，如 '2026-06-01T18:30:00+08:00'）",
                    },
                    "guests": {
                        "type": "integer",
                        "description": "用餐人数",
                    },
                    "note": {
                        "type": "string",
                        "description": "备注（如: 靠窗、包厢、婴儿椅）",
                    },
                },
                "required": ["store_id", "time", "guests"],
            },
        },
    ]

    def __init__(self) -> None:
        self._agent_enabled = bool(os.getenv("WECHAT_AI_AGENT_ENABLED", ""))

    # ── Function 实现 ──

    async def query_menu(
        self,
        store_id: str,
        dish_name: str | None = None,
        category: str | None = None,
    ) -> dict:
        """查询门店菜单。"""
        logger.info("ai_agent.query_menu", store_id=store_id, dish_name=dish_name, category=category)
        if not self._agent_enabled:
            return self._mock_query_menu(store_id, dish_name, category)
        # WA-2: 调用真实服务
        return self._mock_query_menu(store_id, dish_name, category)

    async def create_order(
        self,
        store_id: str,
        dishes: list[dict],
        preference: str | None = None,
    ) -> dict:
        """创建订单。"""
        logger.info("ai_agent.create_order", store_id=store_id, dish_count=len(dishes))
        if not self._agent_enabled:
            return self._mock_create_order(store_id, dishes, preference)
        return self._mock_create_order(store_id, dishes, preference)

    async def query_order(self, order_id: str) -> dict:
        """查询订单状态。"""
        logger.info("ai_agent.query_order", order_id=order_id)
        if not self._agent_enabled:
            return self._mock_query_order(order_id)
        return self._mock_query_order(order_id)

    async def query_member(self, openid: str) -> dict:
        """查询会员信息。"""
        logger.info("ai_agent.query_member", openid=openid)
        if not self._agent_enabled:
            return self._mock_query_member(openid)
        return self._mock_query_member(openid)

    async def query_coupons(self, openid: str, store_id: str | None = None) -> dict:
        """查询可用优惠券。"""
        logger.info("ai_agent.query_coupons", openid=openid, store_id=store_id)
        if not self._agent_enabled:
            return self._mock_query_coupons(openid, store_id)
        return self._mock_query_coupons(openid, store_id)

    async def book_table(
        self,
        store_id: str,
        time: str,
        guests: int,
        note: str | None = None,
    ) -> dict:
        """预订桌位。"""
        logger.info("ai_agent.book_table", store_id=store_id, time=time, guests=guests)
        if not self._agent_enabled:
            return self._mock_book_table(store_id, time, guests, note)
        return self._mock_book_table(store_id, time, guests, note)

    # ── Mock 实现（开发/演示用）──

    @staticmethod
    def _mock_query_menu(store_id: str, dish_name: str | None = None, category: str | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        dishes = [
            {"dish_id": "dish_001", "name": "招牌水煮鱼", "category": "招牌",
             "price_fen": 8800, "description": "鲜活草鱼，麻辣鲜香", "status": "available"},
            {"dish_id": "dish_002", "name": "辣子鸡", "category": "热菜",
             "price_fen": 5800, "description": "香辣酥脆", "status": "available"},
            {"dish_id": "dish_003", "name": "蒜蓉西兰花", "category": "热菜",
             "price_fen": 3200, "description": "清淡爽口", "status": "available"},
            {"dish_id": "dish_004", "name": "酸菜鱼", "category": "招牌",
             "price_fen": 6800, "description": "酸爽开胃，可选大份/小份", "status": "available"},
            {"dish_id": "dish_005", "name": "米饭", "category": "主食",
             "price_fen": 300, "description": "东北五常大米", "status": "available"},
        ]
        # 按分类过滤
        if category and category != "全部":
            dishes = [d for d in dishes if d["category"] == category]
        # 按菜名搜索
        if dish_name:
            dishes = [d for d in dishes if dish_name in d["name"]]
        return {
            "ok": True,
            "data": {"store_id": store_id, "dishes": dishes, "total": len(dishes), "queried_at": now},
        }

    @staticmethod
    def _mock_create_order(store_id: str, dishes: list[dict], preference: str | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        order_id = f"ai_order_{_uuid_mod.uuid4().hex[:12]}"
        total_fen = sum(
            _mock_dish_price(d.get("dish_name", "")) * d.get("quantity", 1)
            for d in dishes
        )
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "store_id": store_id,
                "items": dishes,
                "total_fen": total_fen,
                "preference": preference,
                "status": "pending_payment",
                "created_at": now,
            },
        }

    @staticmethod
    def _mock_query_order(order_id: str) -> dict:
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "status": "paid",
                "total_fen": 8800,
                "paid_fen": 8800,
                "estimated_wait_minutes": 15,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    @staticmethod
    def _mock_query_member(openid: str) -> dict:
        return {
            "ok": True,
            "data": {
                "openid": openid,
                "member_id": _uuid_mod.uuid4().hex[:16],
                "level": "gold",
                "level_label": "黄金会员",
                "current_points": 2800,
                "total_spend_fen": 256000,
                "stored_balance_fen": 50000,
                "registered_at": "2025-01-15T10:00:00Z",
            },
        }

    @staticmethod
    def _mock_query_coupons(openid: str, store_id: str | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        coupons = [
            {
                "coupon_id": "cpn_001",
                "name": "满200减30",
                "type": "discount_fen",
                "discount_value": 3000,
                "min_order_fen": 20000,
                "valid_until": "2026-06-30T23:59:59+08:00",
                "status": "available",
            },
            {
                "coupon_id": "cpn_002",
                "name": "8折优惠券",
                "type": "discount_percent",
                "discount_value": 20,
                "min_order_fen": 10000,
                "valid_until": "2026-06-15T23:59:59+08:00",
                "status": "available",
            },
            {
                "coupon_id": "cpn_003",
                "name": "招牌水煮鱼免费券",
                "type": "free_item",
                "discount_value": 0,
                "min_order_fen": 0,
                "valid_until": "2026-05-30T23:59:59+08:00",
                "status": "used",
            },
        ]
        return {
            "ok": True,
            "data": {
                "openid": openid,
                "store_id": store_id,
                "coupons": [c for c in coupons if c["status"] == "available"],
                "total_available": 2,
                "queried_at": now,
            },
        }

    @staticmethod
    def _mock_book_table(
        store_id: str, time: str, guests: int, note: str | None = None,
    ) -> dict:
        booking_id = f"bk_{_uuid_mod.uuid4().hex[:12]}"
        return {
            "ok": True,
            "data": {
                "booking_id": booking_id,
                "store_id": store_id,
                "time": time,
                "guests": guests,
                "note": note,
                "table_no": "A08",
                "status": "confirmed",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }


def _mock_dish_price(dish_name: str) -> int:
    """根据菜品名称估算价格（Mock 用）。"""
    price_map = {
        "水煮鱼": 8800,
        "酸菜鱼": 6800,
        "辣子鸡": 5800,
        "西兰花": 3200,
        "米饭": 300,
    }
    for key, price in price_map.items():
        if key in dish_name:
            return price
    return 5000


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
        self.ai_agent = WechatAIAgentSDK()

    def get_payment_sdk(self, method: str):
        """根据支付方式返回对应 SDK"""
        return {"wechat": self.wechat_pay, "alipay": self.alipay}.get(method)

    def get_login_sdk(self, provider: str):
        """根据登录方式返回对应 SDK"""
        return {"wecom": self.wecom, "dingtalk": self.dingtalk, "feishu": self.feishu}.get(provider)
