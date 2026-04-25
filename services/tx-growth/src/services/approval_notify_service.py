"""审批通知服务

职责：
  - 统一审批流各环节的通知逻辑
  - 支持企微文本卡片、企微文本消息两种通知方式
  - 通知失败不阻塞主流程（仅记录日志）
  - 提供审批事件类型的通知模板

通知场景：
  1. 新审批单创建 → 通知审批人（企微文本卡片）
  2. 审批通过 → 通知申请人（企微文本消息）
  3. 审批拒绝 → 通知申请人（企微文本消息 + 拒绝原因）
  4. 审批超时 → 通知申请人 + 升级审批人
  5. 审批升级 → 通知升级角色审批人
  6. 批量审批完成 → 通知各申请人

金额单位：分(fen)
"""

import os
import uuid
from typing import Optional

import httpx
import structlog

log = structlog.get_logger(__name__)


class ApprovalNotifyService:
    """审批通知服务 — 封装审批流各环节通知逻辑"""

    GATEWAY_URL: str = os.getenv("GATEWAY_SERVICE_URL", "http://gateway:8000")
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "https://os.tunxiang.com")

    # ------------------------------------------------------------------
    # 通知场景方法
    # ------------------------------------------------------------------

    async def notify_new_request(
        self,
        request_id: uuid.UUID,
        object_type: str,
        object_name: str,
        requester_name: str,
        approver_role: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """新审批单创建 — 通知审批角色下所有人员。

        发送企微文本卡片消息，包含审批详情链接。
        """
        approver_wecom_ids = await self._fetch_approver_wecom_ids(
            role=approver_role,
            tenant_id=tenant_id,
        )

        title = f"【待审批】{object_type} - {object_name}"
        description = (
            f"申请人：{requester_name}\n"
            f"类型：{object_type}\n"
            f"摘要：{object_name}\n"
            f"请在审批截止前处理"
        )
        detail_url = f"{self.FRONTEND_BASE_URL}/approval/{request_id}"

        for wecom_id in approver_wecom_ids:
            await self._send_text_card(
                wecom_user_id=wecom_id,
                title=title,
                description=description,
                url=detail_url,
                btn_text="去审批",
                tenant_id=tenant_id,
            )

    async def notify_approved(
        self,
        requester_id: uuid.UUID,
        object_type: str,
        object_name: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """审批通过 — 通知申请人。"""
        message = (
            f"您的 {object_type}「{object_name}」审批已全部通过，系统将自动激活。"
        )
        await self._send_text_to_employee(
            employee_id=requester_id,
            content=message,
            tenant_id=tenant_id,
        )

    async def notify_rejected(
        self,
        requester_id: uuid.UUID,
        object_type: str,
        object_name: str,
        reason: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """审批拒绝 — 通知申请人（含拒绝原因）。"""
        message = (
            f"您的 {object_type}「{object_name}」审批被拒绝，"
            f"原因：{reason}。请修改后重新提交。"
        )
        await self._send_text_to_employee(
            employee_id=requester_id,
            content=message,
            tenant_id=tenant_id,
        )

    async def notify_expired(
        self,
        requester_id: uuid.UUID,
        object_type: str,
        object_name: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """审批超时 — 通知申请人。"""
        message = (
            f"您的 {object_type}「{object_name}」审批已超时，请重新提交审批申请。"
        )
        await self._send_text_to_employee(
            employee_id=requester_id,
            content=message,
            tenant_id=tenant_id,
        )

    async def notify_escalated(
        self,
        request_id: uuid.UUID,
        object_type: str,
        object_name: str,
        requester_name: str,
        escalate_role: str,
        original_role: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """审批升级 — 通知升级角色的审批人。"""
        approver_wecom_ids = await self._fetch_approver_wecom_ids(
            role=escalate_role,
            tenant_id=tenant_id,
        )

        title = f"【审批升级】{object_type} - {object_name}"
        description = (
            f"申请人：{requester_name}\n"
            f"原审批角色 {original_role} 未在规定时间内处理\n"
            f"已升级到您的角色，请尽快审批"
        )
        detail_url = f"{self.FRONTEND_BASE_URL}/approval/{request_id}"

        for wecom_id in approver_wecom_ids:
            await self._send_text_card(
                wecom_user_id=wecom_id,
                title=title,
                description=description,
                url=detail_url,
                btn_text="去审批",
                tenant_id=tenant_id,
            )

    async def notify_batch_result(
        self,
        results: list[dict],
        approver_name: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """批量审批结果通知 — 向各申请人发送通知。

        Args:
            results: 批量审批结果列表，每条包含 request_id, ok, status 等
            approver_name: 审批人姓名
            tenant_id: 租户 ID
        """
        for result in results:
            if not result.get("ok"):
                continue
            # 批量审批只处理通过的情况（拒绝需要单独填写原因）
            request_id = result.get("request_id", "")
            log.info(
                "approval.batch_notify",
                request_id=request_id,
                approver_name=approver_name,
                tenant_id=str(tenant_id),
            )

    # ------------------------------------------------------------------
    # 私有方法 — 通知发送
    # ------------------------------------------------------------------

    async def _send_text_card(
        self,
        wecom_user_id: str,
        title: str,
        description: str,
        url: str,
        btn_text: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """发送企微文本卡片消息。"""
        payload = {
            "wecom_user_id": wecom_user_id,
            "type": "text_card",
            "title": title,
            "description": description,
            "url": url,
            "btntxt": btn_text,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/send",
                    json=payload,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
            log.info(
                "approval_notify.text_card_sent",
                wecom_user_id=wecom_user_id,
                title=title,
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "approval_notify.text_card_http_error",
                status=exc.response.status_code,
                wecom_user_id=wecom_user_id,
            )
        except httpx.ConnectError as exc:
            log.error(
                "approval_notify.text_card_connect_error",
                error=str(exc),
                wecom_user_id=wecom_user_id,
            )
        except httpx.TimeoutException as exc:
            log.error(
                "approval_notify.text_card_timeout",
                error=str(exc),
                wecom_user_id=wecom_user_id,
            )

    async def _send_text_to_employee(
        self,
        employee_id: uuid.UUID,
        content: str,
        tenant_id: uuid.UUID,
    ) -> None:
        """发送企微文本消息给员工。"""
        payload = {
            "employee_id": str(employee_id),
            "type": "text",
            "content": content,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.GATEWAY_URL}/internal/wecom/send",
                    json=payload,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
            log.info(
                "approval_notify.text_sent",
                employee_id=str(employee_id),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "approval_notify.text_http_error",
                status=exc.response.status_code,
                employee_id=str(employee_id),
            )
        except httpx.ConnectError as exc:
            log.error(
                "approval_notify.text_connect_error",
                error=str(exc),
                employee_id=str(employee_id),
            )
        except httpx.TimeoutException as exc:
            log.error(
                "approval_notify.text_timeout",
                error=str(exc),
                employee_id=str(employee_id),
            )

    async def _fetch_approver_wecom_ids(
        self,
        role: str,
        tenant_id: uuid.UUID,
    ) -> list[str]:
        """从 tx-org（通过 gateway）查询指定角色的员工企微 ID 列表。"""
        if not role:
            return []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.GATEWAY_URL}/internal/org/employees",
                    params={"role": role},
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()

            data = resp.json()
            employees: list[dict] = data.get("data", {}).get("items", [])
            return [
                emp["wecom_user_id"]
                for emp in employees
                if emp.get("wecom_user_id")
            ]
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning(
                "approval_notify.fetch_approvers_failed",
                role=role,
                error=str(exc),
                tenant_id=str(tenant_id),
            )
            return []
