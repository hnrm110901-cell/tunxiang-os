"""GDPR 个人信息保护合规服务

职责：
- 数据主体请求（查看/导出/删除/更正）的创建与处理
- 客户数据匿名化（手机号→hash，姓名→"已删除用户"，地址→清空）
- 同意记录管理
- GDPR 操作审计日志

注意：跨域数据操作通过 HTTP 调用各域微服务完成。
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from ..models.gdpr import (
    AuditLogEntry,
    ConsentRecord,
    DataRequestOut,
    DataRequestStatus,
    DataRequestType,
)

logger = structlog.get_logger(__name__)

# ── 域微服务地址 ──────────────────────────────────────────────────

_MEMBER_URL: str = os.getenv("TX_MEMBER_URL", "http://tx-member:8004")
_TRADE_URL: str = os.getenv("TX_TRADE_URL", "http://tx-trade:8001")
_FINANCE_URL: str = os.getenv("TX_FINANCE_URL", "http://tx-finance:8005")

# ── 内存存储（生产环境应替换为 PostgreSQL） ─────────────────────

_data_requests: dict[str, dict[str, Any]] = {}
_audit_logs: list[dict[str, Any]] = []
_consent_records: list[dict[str, Any]] = []


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class GDPRService:
    """GDPR 合规操作服务"""

    # ── 审计日志（内部） ─────────────────────────────────────────

    def _record_audit(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        action: str,
        target_customer_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "id": _new_id(),
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "action": action,
            "target_customer_id": target_customer_id,
            "detail": detail,
            "created_at": _now().isoformat(),
        }
        _audit_logs.append(entry)
        logger.info(
            "gdpr_audit",
            action=action,
            tenant_id=tenant_id,
            operator_id=operator_id,
            target_customer_id=target_customer_id,
        )
        return entry

    # ── 数据主体请求 ─────────────────────────────────────────────

    async def create_data_request(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        request_type: DataRequestType,
        reason: str | None = None,
        operator_id: str = "system",
    ) -> DataRequestOut:
        """创建数据主体请求（access/export/delete/rectify）"""
        req_id = _new_id()
        record: dict[str, Any] = {
            "id": req_id,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "request_type": request_type.value,
            "status": DataRequestStatus.PENDING.value,
            "result_url": None,
            "created_at": _now().isoformat(),
            "completed_at": None,
            "reason": reason,
        }
        _data_requests[req_id] = record

        self._record_audit(
            tenant_id=tenant_id,
            operator_id=operator_id,
            action=f"data_request_created:{request_type.value}",
            target_customer_id=customer_id,
            detail={"request_id": req_id, "reason": reason},
        )

        # 异步处理请求
        await self._dispatch_request(req_id)

        return DataRequestOut(**_data_requests[req_id])

    def get_data_request(self, *, request_id: str, tenant_id: str) -> DataRequestOut | None:
        """查询数据请求状态"""
        record = _data_requests.get(request_id)
        if record is None or record["tenant_id"] != tenant_id:
            return None
        return DataRequestOut(**record)

    async def _dispatch_request(self, request_id: str) -> None:
        """根据请求类型分发处理"""
        record = _data_requests[request_id]
        request_type = record["request_type"]
        record["status"] = DataRequestStatus.PROCESSING.value

        try:
            if request_type == DataRequestType.ACCESS.value:
                result = await self._process_access_request(
                    tenant_id=record["tenant_id"],
                    customer_id=record["customer_id"],
                )
                record["result_url"] = f"/api/v1/gdpr/data-request/{request_id}/result"
                record["_result_data"] = result
            elif request_type == DataRequestType.EXPORT.value:
                result = await self._process_export_request(
                    tenant_id=record["tenant_id"],
                    customer_id=record["customer_id"],
                )
                record["result_url"] = f"/api/v1/gdpr/data-request/{request_id}/download"
                record["_result_data"] = result
            elif request_type == DataRequestType.DELETE.value:
                await self._process_delete_request(
                    tenant_id=record["tenant_id"],
                    customer_id=record["customer_id"],
                )
            elif request_type == DataRequestType.RECTIFY.value:
                # 更正请求需要人工介入，标记为待处理
                record["status"] = DataRequestStatus.PENDING.value
                logger.info(
                    "gdpr_rectify_request_pending_manual_review",
                    request_id=request_id,
                )
                return

            record["status"] = DataRequestStatus.COMPLETED.value
            record["completed_at"] = _now().isoformat()
        except httpx.HTTPStatusError as exc:
            record["status"] = DataRequestStatus.FAILED.value
            logger.error(
                "gdpr_request_failed",
                request_id=request_id,
                status_code=exc.response.status_code,
                exc_info=True,
            )
        except httpx.ConnectError as exc:
            record["status"] = DataRequestStatus.FAILED.value
            logger.error(
                "gdpr_request_connect_error",
                request_id=request_id,
                error=str(exc),
                exc_info=True,
            )

    # ── Access：收集客户在各域的数据 ─────────────────────────────

    async def _process_access_request(
        self, *, tenant_id: str, customer_id: str
    ) -> dict[str, Any]:
        """收集客户在 会员/订单/财务 各域的数据"""
        headers = {"X-Tenant-ID": tenant_id}
        collected: dict[str, Any] = {"customer_id": customer_id, "collected_at": _now().isoformat()}

        async with httpx.AsyncClient(timeout=15) as client:
            # 会员域
            try:
                resp = await client.get(
                    f"{_MEMBER_URL}/api/v1/member/customers/{customer_id}",
                    headers=headers,
                )
                resp.raise_for_status()
                collected["member_profile"] = resp.json().get("data")
            except httpx.HTTPStatusError as exc:
                logger.warning("gdpr_access_member_error", status=exc.response.status_code)
                collected["member_profile"] = None
            except httpx.ConnectError:
                logger.warning("gdpr_access_member_unreachable")
                collected["member_profile"] = None

            # 交易域（订单）
            try:
                resp = await client.get(
                    f"{_TRADE_URL}/api/v1/trade/orders",
                    params={"customer_id": customer_id, "page": 1, "size": 1000},
                    headers=headers,
                )
                resp.raise_for_status()
                collected["orders"] = resp.json().get("data")
            except httpx.HTTPStatusError as exc:
                logger.warning("gdpr_access_trade_error", status=exc.response.status_code)
                collected["orders"] = None
            except httpx.ConnectError:
                logger.warning("gdpr_access_trade_unreachable")
                collected["orders"] = None

            # 财务域（支付记录）
            try:
                resp = await client.get(
                    f"{_FINANCE_URL}/api/v1/finance/payments",
                    params={"customer_id": customer_id, "page": 1, "size": 1000},
                    headers=headers,
                )
                resp.raise_for_status()
                collected["payments"] = resp.json().get("data")
            except httpx.HTTPStatusError as exc:
                logger.warning("gdpr_access_finance_error", status=exc.response.status_code)
                collected["payments"] = None
            except httpx.ConnectError:
                logger.warning("gdpr_access_finance_unreachable")
                collected["payments"] = None

        return collected

    # ── Export：导出为 JSON ───────────────────────────────────────

    async def _process_export_request(
        self, *, tenant_id: str, customer_id: str
    ) -> dict[str, Any]:
        """收集并序列化为可下载 JSON（GDPR Article 20 数据可携带权）"""
        data = await self._process_access_request(
            tenant_id=tenant_id, customer_id=customer_id
        )
        data["export_format"] = "json"
        data["gdpr_article"] = "Article 20 - Right to data portability"
        return data

    # ── Delete：跨域删除/匿名化 ──────────────────────────────────

    async def _process_delete_request(
        self, *, tenant_id: str, customer_id: str
    ) -> None:
        """跨域删除 / 匿名化客户数据（GDPR Article 17 被遗忘权）

        策略：
        - 手机号 → SHA-256 hash（保留统计可关联性但不可逆）
        - 姓名 → "已删除用户"
        - 地址 → 清空
        - 订单/支付记录中的个人信息字段匿名化，保留交易数据用于财务合规
        """
        await self.anonymize_customer(
            tenant_id=tenant_id,
            customer_id=customer_id,
            operator_id="system:gdpr_delete_request",
        )

    # ── 匿名化 ──────────────────────────────────────────────────

    async def anonymize_customer(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        operator_id: str = "system",
        reason: str = "gdpr_request",
    ) -> dict[str, Any]:
        """直接匿名化客户数据

        匿名化策略：
        - phone → SHA-256(phone)（不可逆 hash）
        - name → "已删除用户"
        - address → ""（清空）
        - email → ""（清空）
        """
        headers = {"X-Tenant-ID": tenant_id}
        anonymize_payload = {
            "customer_id": customer_id,
            "fields": {
                "name": "已删除用户",
                "phone": f"ANON_{hashlib.sha256(customer_id.encode()).hexdigest()[:16]}",
                "address": "",
                "email": "",
            },
            "reason": reason,
        }

        results: dict[str, Any] = {"customer_id": customer_id, "services": {}}

        async with httpx.AsyncClient(timeout=15) as client:
            # 会员域匿名化
            try:
                resp = await client.post(
                    f"{_MEMBER_URL}/api/v1/member/customers/{customer_id}/anonymize",
                    json=anonymize_payload,
                    headers=headers,
                )
                resp.raise_for_status()
                results["services"]["member"] = "anonymized"
            except httpx.HTTPStatusError as exc:
                results["services"]["member"] = f"error:{exc.response.status_code}"
                logger.error(
                    "gdpr_anonymize_member_error",
                    customer_id=customer_id,
                    status=exc.response.status_code,
                )
            except httpx.ConnectError:
                results["services"]["member"] = "unreachable"
                logger.error("gdpr_anonymize_member_unreachable", customer_id=customer_id)

            # 交易域匿名化（订单中的客户信息）
            try:
                resp = await client.post(
                    f"{_TRADE_URL}/api/v1/trade/orders/anonymize-customer",
                    json={"customer_id": customer_id},
                    headers=headers,
                )
                resp.raise_for_status()
                results["services"]["trade"] = "anonymized"
            except httpx.HTTPStatusError as exc:
                results["services"]["trade"] = f"error:{exc.response.status_code}"
                logger.error(
                    "gdpr_anonymize_trade_error",
                    customer_id=customer_id,
                    status=exc.response.status_code,
                )
            except httpx.ConnectError:
                results["services"]["trade"] = "unreachable"
                logger.error("gdpr_anonymize_trade_unreachable", customer_id=customer_id)

            # 财务域匿名化（支付记录中的客户信息）
            try:
                resp = await client.post(
                    f"{_FINANCE_URL}/api/v1/finance/payments/anonymize-customer",
                    json={"customer_id": customer_id},
                    headers=headers,
                )
                resp.raise_for_status()
                results["services"]["finance"] = "anonymized"
            except httpx.HTTPStatusError as exc:
                results["services"]["finance"] = f"error:{exc.response.status_code}"
                logger.error(
                    "gdpr_anonymize_finance_error",
                    customer_id=customer_id,
                    status=exc.response.status_code,
                )
            except httpx.ConnectError:
                results["services"]["finance"] = "unreachable"
                logger.error("gdpr_anonymize_finance_unreachable", customer_id=customer_id)

        self._record_audit(
            tenant_id=tenant_id,
            operator_id=operator_id,
            action="customer_anonymized",
            target_customer_id=customer_id,
            detail=results,
        )

        return results

    # ── 同意记录 ─────────────────────────────────────────────────

    def record_consent(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        consent_type: str,
        granted: bool,
        source: str = "web",
        operator_id: str = "system",
    ) -> ConsentRecord:
        """记录用户同意/撤销同意"""
        record = {
            "id": _new_id(),
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "consent_type": consent_type,
            "granted": granted,
            "source": source,
            "created_at": _now().isoformat(),
        }
        _consent_records.append(record)

        self._record_audit(
            tenant_id=tenant_id,
            operator_id=operator_id,
            action=f"consent_{'granted' if granted else 'revoked'}:{consent_type}",
            target_customer_id=customer_id,
            detail={"consent_type": consent_type, "granted": granted, "source": source},
        )

        return ConsentRecord(**record)

    # ── 审计日志查询 ─────────────────────────────────────────────

    def get_audit_log(
        self,
        *,
        tenant_id: str,
        page: int = 1,
        size: int = 20,
        customer_id: str | None = None,
        action: str | None = None,
    ) -> tuple[list[AuditLogEntry], int]:
        """获取 GDPR 操作审计日志（分页 + 可选过滤）"""
        filtered = [
            e for e in _audit_logs
            if e["tenant_id"] == tenant_id
            and (customer_id is None or e.get("target_customer_id") == customer_id)
            and (action is None or action in e.get("action", ""))
        ]
        # 按时间倒序
        filtered.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(filtered)
        start = (page - 1) * size
        items = [AuditLogEntry(**e) for e in filtered[start : start + size]]
        return items, total
