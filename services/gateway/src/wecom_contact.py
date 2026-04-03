"""企业微信客户联系 SDK 扩展 (SCRM)

在 WecomSDK 基础上扩展"客户联系"相关 API，独立维护便于测试和复用。

API 文档参考：
  https://developer.work.weixin.qq.com/document/path/92114  — 获取客户详情
  https://developer.work.weixin.qq.com/document/path/92571  — 获取跟进成员列表
  https://developer.work.weixin.qq.com/document/path/92572  — 配置客户联系二维码
  https://developer.work.weixin.qq.com/document/path/92113  — 获取客户列表
"""
from __future__ import annotations

from typing import Optional

import httpx
import structlog

from .external_sdk import WecomAPIError, WecomSDK

logger = structlog.get_logger()


class WecomContactSDK(WecomSDK):
    """企微客户联系 API — 继承 WecomSDK，共享 access_token 缓存和 BASE URL"""

    async def get_external_contact(self, external_userid: str) -> dict:
        """获取客户详情

        GET /externalcontact/get?access_token=xxx&external_userid=xxx

        返回字段示例：
          external_contact.external_userid, name, gender, unionid, mobile
          follow_info（跟进信息）
        """
        token = await self.get_access_token()
        url = (
            f"{self.BASE}/externalcontact/get"
            f"?access_token={token}&external_userid={external_userid}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_get_external_contact_http_error",
                    status=exc.response.status_code,
                    external_userid=external_userid,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error(
                    "wecom_get_external_contact_connect_error",
                    error=str(exc),
                    external_userid=external_userid,
                )
                raise
            except httpx.TimeoutException as exc:
                logger.error(
                    "wecom_get_external_contact_timeout",
                    error=str(exc),
                    external_userid=external_userid,
                )
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        logger.info("wecom_get_external_contact_ok", external_userid=external_userid)
        return data  # 含 external_contact + follow_info

    async def get_follow_user_list(self) -> list[str]:
        """获取已开通客户联系功能的成员列表

        GET /externalcontact/get_follow_user_list?access_token=xxx

        返回：[userid, ...]
        """
        token = await self.get_access_token()
        url = f"{self.BASE}/externalcontact/get_follow_user_list?access_token={token}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_get_follow_user_list_http_error",
                    status=exc.response.status_code,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_get_follow_user_list_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_get_follow_user_list_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        follow_users: list[str] = data.get("follow_user", [])
        logger.info("wecom_get_follow_user_list_ok", count=len(follow_users))
        return follow_users

    async def add_contact_way(
        self,
        state: str,
        config_id: Optional[str] = None,
        remark: str = "门店扫码",
    ) -> dict:
        """创建/更新企微活码（门店专属二维码）

        POST /externalcontact/add_contact_way

        type=2（多人），scene=5（小程序）
        state 传入 store_id，回调事件中可用于识别来源门店

        返回：{config_id, qr_code}
        """
        token = await self.get_access_token()
        url = f"{self.BASE}/externalcontact/add_contact_way?access_token={token}"
        payload: dict = {
            "type": 2,
            "scene": 5,
            "remark": remark,
            "state": state,
            "is_temp": False,
            "conclusions": {},
        }
        if config_id:
            payload["config_id"] = config_id

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_add_contact_way_http_error",
                    status=exc.response.status_code,
                    state=state,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error("wecom_add_contact_way_connect_error", error=str(exc))
                raise
            except httpx.TimeoutException as exc:
                logger.error("wecom_add_contact_way_timeout", error=str(exc))
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        logger.info("wecom_add_contact_way_ok", state=state, config_id=data.get("config_id"))
        return {"config_id": data.get("config_id"), "qr_code": data.get("qr_code")}

    async def batch_get_external_contact(self, userid: str) -> list[str]:
        """获取某导购的所有客户外部联系人 ID 列表

        GET /externalcontact/list?access_token=xxx&userid=xxx

        返回：[external_userid, ...]
        """
        token = await self.get_access_token()
        url = (
            f"{self.BASE}/externalcontact/list"
            f"?access_token={token}&userid={userid}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "wecom_batch_get_external_contact_http_error",
                    status=exc.response.status_code,
                    userid=userid,
                )
                raise
            except httpx.ConnectError as exc:
                logger.error(
                    "wecom_batch_get_external_contact_connect_error",
                    error=str(exc),
                    userid=userid,
                )
                raise
            except httpx.TimeoutException as exc:
                logger.error(
                    "wecom_batch_get_external_contact_timeout",
                    error=str(exc),
                    userid=userid,
                )
                raise

        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WecomAPIError(data["errcode"], data.get("errmsg", ""))

        external_ids: list[str] = data.get("external_userid", [])
        logger.info(
            "wecom_batch_get_external_contact_ok",
            userid=userid,
            count=len(external_ids),
        )
        return external_ids


# 模块级单例（与 ExternalSDKManager 中 wecom 实例保持一致的配置）
wecom_contact_sdk = WecomContactSDK()
