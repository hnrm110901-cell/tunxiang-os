"""企微自动标签服务

WecomAutoTagService 负责：
- sync_tags_to_wecom — 将会员标签同步到企微外部联系人标签
- get_wecom_tags     — 获取企微侧已配置的标签列表

标签同步流程：
1. 查询会员标签（RFM分层/菜品偏好/消费能力）
2. 调用企微 API: POST /cgi-bin/externalcontact/mark_tag
3. 返回同步报告（成功/失败/跳过）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SyncReport:
    """会员标签同步报告"""
    tenant_id: str
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


class WecomAutoTagService:
    """企微自动标签服务

    负责将会员侧标签同步到企业微信外部联系人标签体系。
    同步为"尽力而为"操作：失败仅记录日志，不阻塞业务流程。
    """

    GATEWAY_URL: str = "http://gateway:8000"

    async def sync_tags_to_wecom(
        self,
        tenant_id: str,
        member_tags: dict[str, list[str]],
    ) -> SyncReport:
        """将会员标签同步到企微外部联系人标签

        Args:
            tenant_id:    租户 ID
            member_tags:  {wecom_external_userid: [tag1, tag2, ...]}

        Returns:
            SyncReport 实例（含成功/失败/跳过统计）

        说明：
        - 只同步有 wecom_external_userid 的会员
        - 企微 API 调用频率限制：每企业调用 100 次/分钟
        - 同步为"尽力而为"：失败仅记录日志
        """
        report = SyncReport(tenant_id=tenant_id, total=len(member_tags))
        log = logger.bind(tenant_id=tenant_id, total=report.total)
        log.info("wecom_tag_sync_start")

        if not member_tags:
            log.info("wecom_tag_sync_empty")
            return report

        access_token = await self._get_wecom_token()
        if not access_token:
            log.warning("wecom_tag_sync_no_token")
            report.skipped = report.total
            return report

        semaphore = asyncio.Semaphore(10)  # 并发控制，避免触发企微限流

        async def sync_one(external_userid: str, tags: list[str]) -> dict[str, Any]:
            async with semaphore:
                return await self._mark_tag_single(
                    access_token=access_token,
                    external_userid=external_userid,
                    tags=tags,
                )

        tasks = [
            sync_one(external_userid, tags)
            for external_userid, tags in member_tags.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, result in enumerate(results):
            external_userid = list(member_tags.keys())[idx]
            if isinstance(result, Exception):
                report.failed += 1
                report.details.append({
                    "external_userid": external_userid,
                    "status": "failed",
                    "error": str(result),
                })
                logger.warning(
                    "wecom_tag_sync_item_failed",
                    external_userid=external_userid,
                    error=str(result),
                )
            elif result.get("success"):
                report.success += 1
                report.details.append({
                    "external_userid": external_userid,
                    "status": "success",
                    "tags": result.get("tags", []),
                })
            else:
                report.failed += 1
                report.details.append({
                    "external_userid": external_userid,
                    "status": "failed",
                    "error": result.get("error", "unknown"),
                })

        log.info(
            "wecom_tag_sync_done",
            success=report.success,
            failed=report.failed,
            skipped=report.skipped,
        )
        return report

    async def get_wecom_tags(self, corp_id: str) -> list[dict]:
        """获取企微侧已配置的标签列表

        GET /cgi-bin/externalcontact/get_corp_tag_list

        返回企微企业标签库中的全部标签（含分组信息）。

        Args:
            corp_id: 企业微信 corp_id

        Returns:
            [{"group_id": "xxx", "group_name": "xxx", "tag": [{"id": "xxx", "name": "xxx"}, ...]}, ...]
        """
        log = logger.bind(corp_id=corp_id)
        log.info("wecom_get_tags_start")

        token = await self._get_wecom_token()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/get_corp_tag_list",
                    params={"access_token": token},
                    json={},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    log.warning("wecom_get_tags_api_error", errcode=data["errcode"], errmsg=data.get("errmsg"))
                    return []
                tag_groups: list[dict] = data.get("tag_group", [])
                log.info("wecom_get_tags_ok", group_count=len(tag_groups))
                return tag_groups
        except httpx.HTTPStatusError as exc:
            log.warning("wecom_get_tags_http_error", status=exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            log.warning("wecom_get_tags_request_error", error=str(exc))
            return []

    # ── 内部：为单个外部联系人打标签 ─────────────────────────────

    async def _mark_tag_single(
        self,
        access_token: str,
        external_userid: str,
        tags: list[str],
    ) -> dict[str, Any]:
        """为单个外部联系人打标签（PATCH 语义：追加标签）

        POST /cgi-bin/externalcontact/mark_tag
        """
        if not access_token:
            return {"success": False, "error": "no access token"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/mark_tag",
                    params={"access_token": access_token},
                    json={"external_userid": external_userid, "add_tag": tags},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.warning(
                        "wecom_mark_tag_single_api_error",
                        external_userid=external_userid,
                        errcode=data["errcode"],
                        errmsg=data.get("errmsg"),
                    )
                    return {"success": False, "error": f"errcode {data['errcode']}: {data.get('errmsg', '')}"}
                return {"success": True, "tags": tags}
        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"http_{exc.response.status_code}"}
        except httpx.RequestError as exc:
            return {"success": False, "error": str(exc)}

    # ── 内部：获取企微 access_token ──────────────────────────────

    async def _get_wecom_token(self) -> str:
        """获取企微 access_token"""
        import os

        corp_id = os.getenv("WECOM_CORP_ID", "")
        secret = os.getenv("WECOM_SECRET", "")
        if not corp_id or not secret:
            logger.warning("wecom_auto_tag_missing_credentials")
            return ""

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                    params={"corpid": corp_id, "corpsecret": secret},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.warning("wecom_get_token_error", errcode=data["errcode"])
                    return ""
                return data.get("access_token", "")
        except httpx.RequestError as exc:
            logger.warning("wecom_get_token_request_error", error=str(exc))
            return ""


# 模块级单例
wecom_auto_tag_service = WecomAutoTagService()
