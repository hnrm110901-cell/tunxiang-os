"""Sprint E3 — 小红书核销服务：webhook ingress + canonical transform

流程：
  1. 接收 webhook POST body + headers
  2. 用 binding.webhook_secret 校验 HMAC 签名 + timestamp skew
  3. 幂等存 xiaohongshu_verify_events（UNIQUE payload_sha256）
  4. 成功校验 → 调 E1 `transform("xiaohongshu", ...)` 转 canonical
  5. 持久化 canonical_delivery_orders
  6. 回写 verify_event.transform_status + canonical_order_id

失败路径：
  · 签名错 → transform_status='skipped' + signature_valid=false，不影响 200 响应
  · payload 重复 → transform_status='skipped'（幂等保护）
  · canonical transform 失败 → transform_status='failed' + transform_error

注：本服务**同步**处理（webhook 调用直接完成 canonical 写入）。实际部署建议改
异步：webhook 端点只校验 + 存原始 event + 200 响应；worker 拉事件做 canonical。
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.delivery_canonical import (
    TransformationError,
)
from shared.adapters.delivery_canonical import (
    transform as transform_canonical,
)
from shared.adapters.xiaohongshu.src.webhook_signature import (
    VerificationResult,
    extract_xhs_headers,
    verify_signature,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────


@dataclass
class WebhookIngestOutcome:
    event_id: str
    signature_valid: bool
    transform_status: str  # pending/transformed/skipped/failed/replayed
    canonical_order_id: Optional[str] = None
    error_message: Optional[str] = None
    was_duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "signature_valid": self.signature_valid,
            "transform_status": self.transform_status,
            "canonical_order_id": self.canonical_order_id,
            "error_message": self.error_message,
            "was_duplicate": self.was_duplicate,
        }


# ─────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────


class XhsVerificationService:
    """小红书 webhook ingress 服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def process_webhook(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        source_ip: Optional[str] = None,
    ) -> WebhookIngestOutcome:
        """处理一次 webhook 推送（端到端流程）"""

        # 1. 解析 payload（JSON 解析失败也要保存事件供审计）
        payload, parse_error = _safe_parse_body(body)

        # 2. 幂等：先按 payload_sha256 查重
        payload_sha = _compute_sha256(body)
        existing = await self._find_existing_event(payload_sha)
        if existing:
            return WebhookIngestOutcome(
                event_id=str(existing["id"]),
                signature_valid=bool(existing.get("signature_valid")),
                transform_status=existing["transform_status"],
                canonical_order_id=(
                    str(existing["canonical_order_id"])
                    if existing.get("canonical_order_id") else None
                ),
                was_duplicate=True,
            )

        # 3. 定位 binding（通过 payload.shop_code 找 webhook_secret）
        shop_code = payload.get("shop_code") if isinstance(payload, dict) else None
        binding = (
            await self._find_binding_by_shop(shop_code) if shop_code else None
        )

        # 4. 签名校验
        verify_result = self._verify_signature_with_binding(
            headers=headers, body=body, binding=binding
        )

        # 5. 事件类型提取
        event_type = _extract_event_type(payload) if isinstance(payload, dict) else "unknown"

        # 6. 插入事件（先占位 status='pending'）
        event_id = await self._insert_event(
            binding=binding,
            payload=payload if isinstance(payload, dict) else {},
            payload_sha=payload_sha,
            headers=headers,
            source_ip=source_ip,
            event_type=event_type,
            verify_result=verify_result,
            parse_error=parse_error,
        )

        # 7. 签名校验失败 → 跳过 canonical，但仍存事件
        if not verify_result.ok:
            await self._update_event_status(
                event_id=event_id,
                transform_status="skipped",
                transform_error=f"签名校验失败: {verify_result.error_code}",
            )
            await self._db.commit()
            return WebhookIngestOutcome(
                event_id=event_id,
                signature_valid=False,
                transform_status="skipped",
                error_message=verify_result.error_message,
            )

        # 8. 签名 OK → 调 E1 canonical transform
        if not isinstance(payload, dict) or parse_error:
            await self._update_event_status(
                event_id=event_id,
                transform_status="failed",
                transform_error=f"payload JSON 解析失败: {parse_error}",
            )
            await self._db.commit()
            return WebhookIngestOutcome(
                event_id=event_id,
                signature_valid=True,
                transform_status="failed",
                error_message=parse_error,
            )

        try:
            order = transform_canonical(
                "xiaohongshu", payload, tenant_id=self._tenant_id
            )
        except TransformationError as exc:
            await self._update_event_status(
                event_id=event_id,
                transform_status="failed",
                transform_error=f"canonical transform: {exc}",
            )
            await self._db.commit()
            return WebhookIngestOutcome(
                event_id=event_id,
                signature_valid=True,
                transform_status="failed",
                error_message=str(exc),
            )

        # 9. 补充 store_id / brand_id（从 binding）
        if binding:
            order.store_id = str(binding["store_id"])
            order.brand_id = (
                str(binding["brand_id"]) if binding.get("brand_id") else None
            )

        # 10. 持久化 canonical（幂等 UPSERT）
        canonical_order_id = await self._upsert_canonical(order=order)

        # 11. 更新 event + binding.last_webhook_at
        await self._update_event_status(
            event_id=event_id,
            transform_status="transformed",
            canonical_order_id=canonical_order_id,
        )
        if binding:
            await self._touch_binding_webhook(binding_id=str(binding["id"]))
        await self._db.commit()

        return WebhookIngestOutcome(
            event_id=event_id,
            signature_valid=True,
            transform_status="transformed",
            canonical_order_id=canonical_order_id,
        )

    # ─────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────

    async def _find_existing_event(
        self, payload_sha: str
    ) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT id, transform_status, signature_valid, canonical_order_id
                FROM xiaohongshu_verify_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND payload_sha256 = :sha
                LIMIT 1
            """),
            {"tenant_id": self._tenant_id, "sha": payload_sha},
        )
        rec = row.mappings().first()
        return dict(rec) if rec else None

    async def _find_binding_by_shop(
        self, shop_code: str
    ) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT id, store_id, brand_id, xhs_merchant_id,
                       webhook_secret, status
                FROM xiaohongshu_shop_bindings
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND xhs_shop_code = :shop_code
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tenant_id": self._tenant_id, "shop_code": shop_code},
        )
        rec = row.mappings().first()
        return dict(rec) if rec else None

    def _verify_signature_with_binding(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
        binding: Optional[dict[str, Any]],
    ) -> VerificationResult:
        """有 binding 则用其 webhook_secret 校验；没有 binding 视为失败"""
        if not binding:
            return VerificationResult.failure(
                "BINDING_NOT_FOUND",
                "未找到对应 shop_code 的 binding，可能是配置错误或攻击",
            )
        if binding.get("status") not in ("active", "pending"):
            return VerificationResult.failure(
                "BINDING_INACTIVE",
                f"binding 状态 {binding['status']}，不处理 webhook",
            )
        hdrs = extract_xhs_headers(headers)
        return verify_signature(
            secret=binding["webhook_secret"],
            signature=hdrs["signature"],
            timestamp=hdrs["timestamp"],
            nonce=hdrs["nonce"],
            body=body,
        )

    async def _insert_event(
        self,
        *,
        binding: Optional[dict[str, Any]],
        payload: dict[str, Any],
        payload_sha: str,
        headers: dict[str, str],
        source_ip: Optional[str],
        event_type: str,
        verify_result: VerificationResult,
        parse_error: Optional[str],
    ) -> str:
        params: dict[str, Any] = {
            "tenant_id": self._tenant_id,
            "binding_id": str(binding["id"]) if binding else None,
            "store_id": str(binding["store_id"]) if binding else None,
            "event_type": event_type,
            "verify_code": payload.get("verify_code"),
            "xhs_shop_code": payload.get("shop_code"),
            "xhs_order_id": payload.get("order_id") or payload.get("verify_code"),
            "raw_payload": json.dumps(payload, ensure_ascii=False),
            "payload_sha256": payload_sha,
            "received_headers": json.dumps(
                _sanitize_headers(headers), ensure_ascii=False
            ),
            "signature_valid": verify_result.ok,
            "signature_error": verify_result.error_code if not verify_result.ok else None,
            "transform_status": "pending",
            "source_ip": source_ip,
        }
        row = await self._db.execute(
            text("""
                INSERT INTO xiaohongshu_verify_events (
                    tenant_id, binding_id, store_id, event_type,
                    verify_code, xhs_shop_code, xhs_order_id,
                    raw_payload, payload_sha256, received_headers,
                    signature_valid, signature_error, transform_status,
                    source_ip
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:binding_id AS uuid),
                    CAST(:store_id AS uuid), :event_type,
                    :verify_code, :xhs_shop_code, :xhs_order_id,
                    CAST(:raw_payload AS jsonb), :payload_sha256,
                    CAST(:received_headers AS jsonb),
                    :signature_valid, :signature_error, :transform_status,
                    CAST(:source_ip AS inet)
                )
                RETURNING id
            """),
            params,
        )
        return str(row.scalar_one())

    async def _update_event_status(
        self,
        *,
        event_id: str,
        transform_status: str,
        transform_error: Optional[str] = None,
        canonical_order_id: Optional[str] = None,
    ) -> None:
        await self._db.execute(
            text("""
                UPDATE xiaohongshu_verify_events SET
                    transform_status = :status,
                    transform_error = COALESCE(:error, transform_error),
                    canonical_order_id = COALESCE(
                        CAST(:canonical_id AS uuid), canonical_order_id
                    ),
                    processed_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """),
            {
                "id": event_id,
                "status": transform_status,
                "error": transform_error,
                "canonical_id": canonical_order_id,
            },
        )

    async def _upsert_canonical(self, order: Any) -> str:
        """写入 canonical_delivery_orders（E1 表）。幂等 UPSERT"""
        params = order.to_insert_params()
        params["tenant_id"] = self._tenant_id
        # canonical_order_no 由 E1 API 层生成；webhook 走内部路径需自己补
        if not order.canonical_order_no:
            order.canonical_order_no = _generate_no(order.placed_at)
            params["canonical_order_no"] = order.canonical_order_no

        row = await self._db.execute(
            text("""
                INSERT INTO canonical_delivery_orders (
                    tenant_id, canonical_order_no, platform, platform_order_id,
                    platform_sub_type, store_id, brand_id, order_type, status,
                    platform_status_raw,
                    customer_name, customer_phone_masked, customer_address,
                    customer_address_hash,
                    gross_amount_fen, discount_amount_fen, platform_commission_fen,
                    platform_subsidy_fen, delivery_fee_fen, delivery_cost_fen,
                    packaging_fee_fen, tax_fen, tip_fen, paid_amount_fen, net_amount_fen,
                    placed_at, accepted_at, dispatched_at, delivered_at, completed_at,
                    cancelled_at, expected_delivery_at,
                    raw_payload, payload_sha256, platform_metadata,
                    transformation_errors, canonical_version, ingested_by
                ) VALUES (
                    CAST(:tenant_id AS uuid), :canonical_order_no, :platform,
                    :platform_order_id, :platform_sub_type,
                    CAST(:store_id AS uuid), CAST(:brand_id AS uuid),
                    :order_type, :status, :platform_status_raw,
                    :customer_name, :customer_phone_masked, :customer_address,
                    :customer_address_hash,
                    :gross_amount_fen, :discount_amount_fen, :platform_commission_fen,
                    :platform_subsidy_fen, :delivery_fee_fen, :delivery_cost_fen,
                    :packaging_fee_fen, :tax_fen, :tip_fen, :paid_amount_fen, :net_amount_fen,
                    :placed_at, :accepted_at, :dispatched_at, :delivered_at, :completed_at,
                    :cancelled_at, :expected_delivery_at,
                    CAST(:raw_payload AS jsonb), :payload_sha256,
                    CAST(:platform_metadata AS jsonb),
                    CAST(:transformation_errors AS jsonb),
                    :canonical_version, :ingested_by
                )
                ON CONFLICT (tenant_id, platform, platform_order_id)
                    WHERE is_deleted = false
                DO UPDATE SET
                    status = EXCLUDED.status,
                    platform_status_raw = EXCLUDED.platform_status_raw,
                    completed_at = COALESCE(EXCLUDED.completed_at, canonical_delivery_orders.completed_at),
                    raw_payload = EXCLUDED.raw_payload,
                    payload_sha256 = EXCLUDED.payload_sha256,
                    platform_metadata = EXCLUDED.platform_metadata,
                    updated_at = NOW()
                RETURNING id
            """),
            params,
        )
        return str(row.scalar_one())

    async def _touch_binding_webhook(self, *, binding_id: str) -> None:
        await self._db.execute(
            text("""
                UPDATE xiaohongshu_shop_bindings
                SET last_webhook_at = NOW(), updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": binding_id},
        )


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────


def _safe_parse_body(body: bytes) -> tuple[Any, Optional[str]]:
    """JSON 解析 body；失败返回 (None, error_message)"""
    if not body:
        return (None, "body 为空")
    try:
        return (json.loads(body.decode("utf-8")), None)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return (None, str(exc))


def _compute_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _extract_event_type(payload: dict[str, Any]) -> str:
    """从 payload 提取 event_type

    小红书 webhook 的 event_type 字段：
      · verify_success     团购券核销成功
      · verify_cancel      核销撤销
      · refund             退款
      · status_update      订单状态变更
    """
    et = payload.get("event_type") or payload.get("type")
    if isinstance(et, str) and et:
        return et
    if payload.get("verify_code") and payload.get("pay_price"):
        # 典型核销推送
        return "verify_success"
    return "unknown"


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """归档 headers 时只保留小红书相关，过滤敏感字段（如 Authorization）"""
    allowed_prefixes = ("x-xhs-", "user-agent", "content-type", "x-request-id")
    return {
        k: v
        for k, v in headers.items()
        if any(k.lower().startswith(p) for p in allowed_prefixes)
    }


def _generate_no(placed_at: datetime) -> str:
    """canonical_order_no 格式：XHS + YYYYMMDD + 8 hex"""
    import secrets as _secrets

    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=timezone.utc)
    date_part = placed_at.strftime("%Y%m%d")
    return f"XHS{date_part}{_secrets.token_hex(4).upper()}"
