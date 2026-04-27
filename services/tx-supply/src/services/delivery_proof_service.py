"""配送签收凭证服务（TASK-4，v369）

核心能力：
  1. submit_signature        — 提交电子签名（base64 → mock 对象存储 → URL）
  2. record_damage           — 登记损坏（自动算金额）
  3. attach_file             — 上传附件（照片/视频）
  4. get_receipt             — 查签收单
  5. get_complete_proof      — 完整凭证包：签名 + 所有损坏 + 所有附件
  6. list_pending_damages    — 列出 PENDING 损坏
  7. resolve_damage          — 处理损坏（触发 DELIVERY.DAMAGE_RESOLVED 事件；
                                RETURNED 时财务侧自动开红字凭证）
  8. get_damage_stats        — 损坏统计（按类型/严重度/处理状态）

约束：
  - 签名图大小 ≤ 200KB；附件 ≤ 5MB
  - 签名图必须是 data:image/png 或 data:image/jpeg base64
  - 同一 delivery_id 只能签一次（DB 唯一约束 + service 二次防御）
  - 异常处理只用具体类型
  - 对象存储：Mock，写入 /tmp/tunxiang-supply-uploads/{tenant_id}/{uuid}.{ext}
              真实对象存储待接入腾讯 COS（环境变量 TX_SUPPLY_OBJECT_STORE_ENDPOINT）

事件：
  DELIVERY.SIGNED            — 签收完成
  DELIVERY.DAMAGE_REPORTED   — 损坏登记
  DELIVERY.DAMAGE_RESOLVED   — 损坏处理（含 action=RETURNED 等）
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import DeliveryProofEventType

from ..models.delivery_proof import (
    DamageType,
    EntityType,
    ResolutionStatus,
    Severity,
    SignerRole,
)

# TASK-3 温度凭证 service：直接复用，不再走 information_schema 探测 + 不存在
# 的 cold_chain_evidence 表（v369 智能体当时猜的表名，与 v368 实际表 schema
# delivery_temperature_logs/_alerts 不匹配）。
try:
    from ..services import delivery_temperature_service as _temperature_service
    _TEMP_SERVICE_AVAILABLE = True
except ImportError:  # pragma: no cover — 防御性导入
    _temperature_service = None  # type: ignore[assignment]
    _TEMP_SERVICE_AVAILABLE = False

log = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 常量与异常
# ──────────────────────────────────────────────────────────────────────

MAX_SIGNATURE_SIZE_BYTES = 200 * 1024          # 200KB
MAX_ATTACHMENT_SIZE_BYTES = 5 * 1024 * 1024    # 5MB

_DEFAULT_LOCAL_DIR = "/tmp/tunxiang-supply-uploads"  # noqa: S108 - 仅 dev mock，由 env 覆盖
_LOCAL_UPLOAD_DIR = Path(
    os.environ.get("TX_SUPPLY_LOCAL_UPLOAD_DIR", _DEFAULT_LOCAL_DIR)
)
_OBJECT_STORE_BUCKET = os.environ.get("TX_SUPPLY_OBJECT_STORE_BUCKET", "tunxiang-supply")
_OBJECT_STORE_SCHEME = os.environ.get("TX_SUPPLY_OBJECT_STORE_SCHEME", "s3")

_VALID_SIGNATURE_MIME = {"image/png", "image/jpeg", "image/jpg"}
_MIME_EXT_MAP = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}


class DeliveryProofError(Exception):
    """delivery_proof_service 显式异常类（路由层捕获 → 400/422）"""


# ──────────────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────────────


def _to_uuid(val: str | uuid.UUID) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (TypeError, ValueError) as exc:
        raise DeliveryProofError(f"invalid uuid: {val!r}") from exc


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _parse_data_url(data_url: str) -> tuple[str, bytes]:
    """解析 data:image/png;base64,xxxx 形式的字符串。

    Returns:
        (mime_type, raw_bytes)
    Raises:
        DeliveryProofError: 格式不正确或 base64 解码失败。
    """
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        raise DeliveryProofError(
            "invalid base64 payload: must start with 'data:<mime>;base64,...'"
        )

    try:
        header, body = data_url.split(",", 1)
    except ValueError as exc:
        raise DeliveryProofError("invalid base64 payload: missing comma") from exc

    if ";base64" not in header:
        raise DeliveryProofError("invalid base64 payload: missing ';base64' marker")

    mime_type = header[len("data:"):].split(";", 1)[0].strip().lower()
    if not mime_type:
        raise DeliveryProofError("invalid base64 payload: empty mime type")

    try:
        raw = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DeliveryProofError(f"base64 decode failed: {exc}") from exc

    if not raw:
        raise DeliveryProofError("invalid base64 payload: decoded body is empty")

    return mime_type, raw


def _ext_for_mime(mime_type: str) -> str:
    return _MIME_EXT_MAP.get(mime_type.lower(), "bin")


def upload_to_object_storage(
    *,
    tenant_id: str,
    raw_bytes: bytes,
    mime_type: str,
    file_name: Optional[str] = None,
) -> dict[str, Any]:
    """Mock 对象存储上传。

    本地落盘到 /tmp/tunxiang-supply-uploads/{tenant_id}/{uuid}.{ext}，
    返回形如 s3://tunxiang-supply/{tenant_id}/{uuid}.{ext} 的 URL。

    真实对象存储后续接入腾讯 COS（环境变量 TX_SUPPLY_OBJECT_STORE_ENDPOINT）。

    Returns:
        {
            "url":        对象存储 URL，
            "local_path": 本地路径（仅 mock 模式有效），
            "object_key": bucket 内对象 key，
            "size":       字节数，
            "mime_type":  mime_type，
        }
    """
    ext = _ext_for_mime(mime_type)
    object_uuid = uuid.uuid4().hex
    object_key = f"{tenant_id}/{object_uuid}.{ext}"

    local_dir = _LOCAL_UPLOAD_DIR / str(tenant_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{object_uuid}.{ext}"

    try:
        local_path.write_bytes(raw_bytes)
    except OSError as exc:
        raise DeliveryProofError(f"object storage write failed: {exc}") from exc

    url = f"{_OBJECT_STORE_SCHEME}://{_OBJECT_STORE_BUCKET}/{object_key}"
    log.info(
        "object_storage_uploaded",
        tenant_id=tenant_id,
        url=url,
        size=len(raw_bytes),
        mime_type=mime_type,
        local_path=str(local_path),
        original_name=file_name,
    )
    return {
        "url": url,
        "local_path": str(local_path),
        "object_key": object_key,
        "size": len(raw_bytes),
        "mime_type": mime_type,
    }


# ──────────────────────────────────────────────────────────────────────
# 1. 提交签名
# ──────────────────────────────────────────────────────────────────────


async def submit_signature(
    *,
    delivery_id: str,
    tenant_id: str,
    db: AsyncSession,
    signer_name: str,
    signature_base64: str,
    signer_role: Optional[str] = None,
    signer_phone: Optional[str] = None,
    gps_lat: Optional[Decimal] = None,
    gps_lng: Optional[Decimal] = None,
    device_info: Optional[dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """接收签名图（base64） → mock 上传到对象存储 → 落表。

    若 delivery_id 已存在签收单，抛 DeliveryProofError（400）。
    成功后异步发射 DELIVERY.SIGNED 事件。
    若 store_receiving_confirmations 表存在该 delivery 的确认记录，
    会把 receipt_id 反写回去（best-effort，失败不阻断主流程）。
    """
    if not signer_name or not signer_name.strip():
        raise DeliveryProofError("signer_name is required")

    if signer_role is not None:
        try:
            SignerRole(signer_role)
        except ValueError as exc:
            raise DeliveryProofError(f"invalid signer_role: {signer_role}") from exc

    mime_type, raw = _parse_data_url(signature_base64)
    if mime_type not in _VALID_SIGNATURE_MIME:
        raise DeliveryProofError(
            f"signature mime must be one of {_VALID_SIGNATURE_MIME}, got {mime_type}"
        )
    if len(raw) > MAX_SIGNATURE_SIZE_BYTES:
        raise DeliveryProofError(
            f"signature image size {len(raw)} exceeds limit {MAX_SIGNATURE_SIZE_BYTES}"
        )

    delivery_uuid = _to_uuid(delivery_id)
    tenant_uuid = _to_uuid(tenant_id)
    await _set_tenant(db, tenant_id)

    # 二次防御：检查唯一约束（DB 已加约束，但我们用业务异常包装）
    existing = await db.execute(
        text(
            "SELECT id FROM delivery_receipts "
            "WHERE tenant_id = :tid AND delivery_id = :did LIMIT 1"
        ),
        {"tid": tenant_uuid, "did": delivery_uuid},
    )
    if existing.first() is not None:
        raise DeliveryProofError(
            f"delivery {delivery_id} already signed; receipt is immutable"
        )

    # 解析 store_id（从 distribution_orders；缺失时回退到 nil uuid 让上层报错）
    store_row = await db.execute(
        text(
            "SELECT target_store_id FROM distribution_orders "
            "WHERE id = :did AND tenant_id = :tid LIMIT 1"
        ),
        {"did": delivery_uuid, "tid": tenant_uuid},
    )
    store_data = store_row.first()
    if store_data is None:
        # 不强行要求一定存在 distribution_orders（可能是模拟测试或未来其他来源）
        # 但要求传入 store_id 通过 device_info 兜底——此处直接报错更安全
        raise DeliveryProofError(
            f"distribution_order {delivery_id} not found in current tenant"
        )
    store_uuid = store_data[0]

    upload_meta = upload_to_object_storage(
        tenant_id=tenant_id,
        raw_bytes=raw,
        mime_type=mime_type,
    )

    receipt_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO delivery_receipts (
                id, tenant_id, delivery_id, store_id,
                signer_name, signer_role, signer_phone,
                signed_at, signature_image_url,
                signature_location_lat, signature_location_lng,
                device_info, notes, created_at, updated_at
            ) VALUES (
                :id, :tid, :did, :sid,
                :sname, :srole, :sphone,
                :signed_at, :url,
                :lat, :lng,
                CAST(:dinfo AS JSONB), :notes, :now, :now
            )
        """),
        {
            "id": receipt_id,
            "tid": tenant_uuid,
            "did": delivery_uuid,
            "sid": store_uuid,
            "sname": signer_name.strip(),
            "srole": signer_role,
            "sphone": signer_phone,
            "signed_at": now,
            "url": upload_meta["url"],
            "lat": gps_lat,
            "lng": gps_lng,
            "dinfo": json.dumps(device_info or {}),
            "notes": notes,
            "now": now,
        },
    )
    await db.flush()

    # 反写到 store_receiving_confirmations（best-effort）
    try:
        await db.execute(
            text("""
                UPDATE store_receiving_confirmations
                SET receipt_id = :rid
                WHERE tenant_id = :tid
                  AND distribution_order_id = :did
                  AND receipt_id IS NULL
            """),
            {"rid": receipt_id, "tid": tenant_uuid, "did": delivery_uuid},
        )
    except (ProgrammingError, DBAPIError, SQLAlchemyError) as exc:
        # 反写是 best-effort：列/表不存在（UndefinedColumn/UndefinedTable）
        # 或权限失败时静默跳过，不阻断签收主流程。
        log.warning(
            "store_receiving_confirmations_writeback_skipped",
            delivery_id=delivery_id,
            tenant_id=tenant_id,
            error=str(exc),
        )

    payload = {
        "receipt_id": str(receipt_id),
        "delivery_id": delivery_id,
        "store_id": str(store_uuid),
        "signer_name": signer_name.strip(),
        "signer_role": signer_role,
        "signature_url": upload_meta["url"],
        "signed_at": now.isoformat(),
    }
    asyncio.create_task(
        emit_event(
            event_type=DeliveryProofEventType.SIGNED,
            tenant_id=tenant_uuid,
            stream_id=str(delivery_uuid),
            payload=payload,
            store_id=store_uuid,
            source_service="tx-supply",
            metadata={"signer_role": signer_role, "device": device_info or {}},
        )
    )

    log.info(
        "delivery_signed",
        receipt_id=str(receipt_id),
        delivery_id=delivery_id,
        tenant_id=tenant_id,
        signer=signer_name,
    )
    return {
        "receipt_id": str(receipt_id),
        "delivery_id": delivery_id,
        "store_id": str(store_uuid),
        "signer_name": signer_name.strip(),
        "signer_role": signer_role,
        "signed_at": now.isoformat(),
        "signature_image_url": upload_meta["url"],
        "signature_size_bytes": upload_meta["size"],
    }


# ──────────────────────────────────────────────────────────────────────
# 2. 登记损坏
# ──────────────────────────────────────────────────────────────────────


async def record_damage(
    *,
    delivery_id: str,
    tenant_id: str,
    db: AsyncSession,
    damage_type: str,
    damaged_qty: Decimal,
    item_id: Optional[str] = None,
    ingredient_id: Optional[str] = None,
    batch_no: Optional[str] = None,
    unit_cost_fen: Optional[int] = None,
    description: Optional[str] = None,
    severity: str = Severity.MINOR.value,
    reported_by: Optional[str] = None,
) -> dict[str, Any]:
    """登记一条损坏记录。damage_amount_fen 由 DB Computed 列自动计算。"""
    try:
        DamageType(damage_type)
    except ValueError as exc:
        raise DeliveryProofError(f"invalid damage_type: {damage_type}") from exc
    try:
        Severity(severity)
    except ValueError as exc:
        raise DeliveryProofError(f"invalid severity: {severity}") from exc

    if damaged_qty is None or Decimal(damaged_qty) <= 0:
        raise DeliveryProofError("damaged_qty must be > 0")
    if unit_cost_fen is not None and unit_cost_fen < 0:
        raise DeliveryProofError("unit_cost_fen must be >= 0")

    tenant_uuid = _to_uuid(tenant_id)
    delivery_uuid = _to_uuid(delivery_id)
    await _set_tenant(db, tenant_id)

    damage_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO delivery_damage_records (
                id, tenant_id, delivery_id, item_id, ingredient_id, batch_no,
                damage_type, damaged_qty, unit_cost_fen,
                description, severity, reported_by,
                reported_at, resolution_status, created_at, updated_at, is_deleted
            ) VALUES (
                :id, :tid, :did, :iid, :gid, :batch,
                :dtype, :qty, :ucf,
                :descr, :sev, :rby,
                :now, 'PENDING', :now, :now, false
            )
        """),
        {
            "id": damage_id,
            "tid": tenant_uuid,
            "did": delivery_uuid,
            "iid": _to_uuid(item_id) if item_id else None,
            "gid": _to_uuid(ingredient_id) if ingredient_id else None,
            "batch": batch_no,
            "dtype": damage_type,
            "qty": Decimal(damaged_qty),
            "ucf": unit_cost_fen,
            "descr": description,
            "sev": severity,
            "rby": _to_uuid(reported_by) if reported_by else None,
            "now": now,
        },
    )
    await db.flush()

    # 读回 damage_amount_fen（Computed 列）
    row = await db.execute(
        text(
            "SELECT damage_amount_fen FROM delivery_damage_records "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": damage_id, "tid": tenant_uuid},
    )
    fetched = row.first()
    damage_amount_fen = int(fetched[0]) if fetched and fetched[0] is not None else None

    payload = {
        "damage_id": str(damage_id),
        "delivery_id": delivery_id,
        "damage_type": damage_type,
        "damaged_qty": str(damaged_qty),
        "unit_cost_fen": unit_cost_fen,
        "damage_amount_fen": damage_amount_fen,
        "severity": severity,
    }
    asyncio.create_task(
        emit_event(
            event_type=DeliveryProofEventType.DAMAGE_REPORTED,
            tenant_id=tenant_uuid,
            stream_id=str(delivery_uuid),
            payload=payload,
            source_service="tx-supply",
            metadata={"reported_by": reported_by},
        )
    )

    log.info(
        "delivery_damage_recorded",
        damage_id=str(damage_id),
        delivery_id=delivery_id,
        tenant_id=tenant_id,
        damage_type=damage_type,
        severity=severity,
        amount_fen=damage_amount_fen,
    )
    return {
        "damage_id": str(damage_id),
        "delivery_id": delivery_id,
        "damage_type": damage_type,
        "damaged_qty": str(damaged_qty),
        "unit_cost_fen": unit_cost_fen,
        "damage_amount_fen": damage_amount_fen,
        "severity": severity,
        "resolution_status": ResolutionStatus.PENDING.value,
        "reported_at": now.isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────
# 3. 上传附件
# ──────────────────────────────────────────────────────────────────────


async def attach_file(
    *,
    tenant_id: str,
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
    file_base64: str,
    file_name: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    gps_lat: Optional[Decimal] = None,
    gps_lng: Optional[Decimal] = None,
    uploaded_by: Optional[str] = None,
) -> dict[str, Any]:
    """上传附件到 mock 对象存储 + 写表。"""
    try:
        EntityType(entity_type)
    except ValueError as exc:
        raise DeliveryProofError(f"invalid entity_type: {entity_type}") from exc

    mime_type, raw = _parse_data_url(file_base64)
    if len(raw) > MAX_ATTACHMENT_SIZE_BYTES:
        raise DeliveryProofError(
            f"attachment size {len(raw)} exceeds limit {MAX_ATTACHMENT_SIZE_BYTES}"
        )

    tenant_uuid = _to_uuid(tenant_id)
    entity_uuid = _to_uuid(entity_id)
    await _set_tenant(db, tenant_id)

    # 校验 entity 存在（在当前租户）
    table = (
        "delivery_receipts" if entity_type == EntityType.RECEIPT.value
        else "delivery_damage_records"
    )
    exists = await db.execute(
        text(f"SELECT 1 FROM {table} WHERE id = :id AND tenant_id = :tid LIMIT 1"),
        {"id": entity_uuid, "tid": tenant_uuid},
    )
    if exists.first() is None:
        raise DeliveryProofError(
            f"{entity_type} {entity_id} not found in current tenant"
        )

    upload_meta = upload_to_object_storage(
        tenant_id=tenant_id,
        raw_bytes=raw,
        mime_type=mime_type,
        file_name=file_name,
    )

    att_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO delivery_attachments (
                id, tenant_id, entity_type, entity_id,
                file_url, file_type, file_size, file_name, thumbnail_url,
                captured_at, gps_lat, gps_lng,
                uploaded_by, uploaded_at, created_at, updated_at
            ) VALUES (
                :id, :tid, :etype, :eid,
                :url, :ftype, :fsize, :fname, NULL,
                :captured, :lat, :lng,
                :uby, :now, :now, :now
            )
        """),
        {
            "id": att_id,
            "tid": tenant_uuid,
            "etype": entity_type,
            "eid": entity_uuid,
            "url": upload_meta["url"],
            "ftype": mime_type,
            "fsize": upload_meta["size"],
            "fname": file_name,
            "captured": captured_at,
            "lat": gps_lat,
            "lng": gps_lng,
            "uby": _to_uuid(uploaded_by) if uploaded_by else None,
            "now": now,
        },
    )
    await db.flush()

    log.info(
        "delivery_attachment_uploaded",
        attachment_id=str(att_id),
        entity_type=entity_type,
        entity_id=entity_id,
        size=upload_meta["size"],
        mime_type=mime_type,
    )
    return {
        "attachment_id": str(att_id),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "file_url": upload_meta["url"],
        "file_type": mime_type,
        "file_size": upload_meta["size"],
        "file_name": file_name,
        "uploaded_at": now.isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────
# 4. 查签收单
# ──────────────────────────────────────────────────────────────────────


async def get_receipt(
    *,
    delivery_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询配送签收单（不含损坏/附件，详细凭证用 get_complete_proof）。"""
    tenant_uuid = _to_uuid(tenant_id)
    delivery_uuid = _to_uuid(delivery_id)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, delivery_id, store_id, signer_name, signer_role, signer_phone,
                   signed_at, signature_image_url,
                   signature_location_lat, signature_location_lng,
                   device_info, notes, created_at
            FROM delivery_receipts
            WHERE tenant_id = :tid AND delivery_id = :did
            LIMIT 1
        """),
        {"tid": tenant_uuid, "did": delivery_uuid},
    )
    rec = row.first()
    if rec is None:
        return None
    return _serialize_receipt(rec)


def _serialize_receipt(row: Any) -> dict[str, Any]:
    return {
        "receipt_id": str(row[0]),
        "delivery_id": str(row[1]),
        "store_id": str(row[2]),
        "signer_name": row[3],
        "signer_role": row[4],
        "signer_phone": row[5],
        "signed_at": row[6].isoformat() if row[6] else None,
        "signature_image_url": row[7],
        "signature_location_lat": str(row[8]) if row[8] is not None else None,
        "signature_location_lng": str(row[9]) if row[9] is not None else None,
        "device_info": row[10] or {},
        "notes": row[11],
        "created_at": row[12].isoformat() if row[12] else None,
    }


def _serialize_damage(row: Any) -> dict[str, Any]:
    return {
        "damage_id": str(row[0]),
        "delivery_id": str(row[1]),
        "item_id": str(row[2]) if row[2] else None,
        "ingredient_id": str(row[3]) if row[3] else None,
        "batch_no": row[4],
        "damage_type": row[5],
        "damaged_qty": str(row[6]),
        "unit_cost_fen": int(row[7]) if row[7] is not None else None,
        "damage_amount_fen": int(row[8]) if row[8] is not None else None,
        "description": row[9],
        "severity": row[10],
        "reported_by": str(row[11]) if row[11] else None,
        "reported_at": row[12].isoformat() if row[12] else None,
        "resolution_status": row[13],
        "resolved_by": str(row[14]) if row[14] else None,
        "resolved_at": row[15].isoformat() if row[15] else None,
        "resolve_action": row[16],
        "resolve_comment": row[17],
    }


def _serialize_attachment(row: Any) -> dict[str, Any]:
    return {
        "attachment_id": str(row[0]),
        "entity_type": row[1],
        "entity_id": str(row[2]),
        "file_url": row[3],
        "file_type": row[4],
        "file_size": int(row[5]) if row[5] is not None else None,
        "file_name": row[6],
        "thumbnail_url": row[7],
        "captured_at": row[8].isoformat() if row[8] else None,
        "gps_lat": str(row[9]) if row[9] is not None else None,
        "gps_lng": str(row[10]) if row[10] is not None else None,
        "uploaded_by": str(row[11]) if row[11] else None,
        "uploaded_at": row[12].isoformat() if row[12] else None,
    }


# ──────────────────────────────────────────────────────────────────────
# 5. 完整凭证包
# ──────────────────────────────────────────────────────────────────────


async def get_complete_proof(
    *,
    delivery_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """组装完整凭证：签名 + 全部损坏 + 全部附件 + TASK-3 温度凭证。

    温度凭证通过直接调用 delivery_temperature_service.get_temperature_proof
    获取（TASK-3 / v368 提供）。若该 service 不可用或查询失败，温度部分降级
    为空数据但不阻断签收凭证返回，便于断网或部分服务故障时仍能出凭证。
    """
    tenant_uuid = _to_uuid(tenant_id)
    delivery_uuid = _to_uuid(delivery_id)
    await _set_tenant(db, tenant_id)

    # 签名
    receipt = await get_receipt(delivery_id=delivery_id, tenant_id=tenant_id, db=db)

    # 损坏
    damage_rows = await db.execute(
        text("""
            SELECT id, delivery_id, item_id, ingredient_id, batch_no, damage_type,
                   damaged_qty, unit_cost_fen, damage_amount_fen,
                   description, severity, reported_by, reported_at,
                   resolution_status, resolved_by, resolved_at,
                   resolve_action, resolve_comment
            FROM delivery_damage_records
            WHERE tenant_id = :tid AND delivery_id = :did AND is_deleted = false
            ORDER BY reported_at DESC
        """),
        {"tid": tenant_uuid, "did": delivery_uuid},
    )
    damages = [_serialize_damage(r) for r in damage_rows.fetchall()]
    damage_ids = [_to_uuid(d["damage_id"]) for d in damages]

    # 附件：RECEIPT 附件 + DAMAGE 附件
    receipt_attach: list[dict[str, Any]] = []
    if receipt is not None:
        att_rows = await db.execute(
            text("""
                SELECT id, entity_type, entity_id, file_url, file_type, file_size,
                       file_name, thumbnail_url, captured_at, gps_lat, gps_lng,
                       uploaded_by, uploaded_at
                FROM delivery_attachments
                WHERE tenant_id = :tid AND entity_type = 'RECEIPT' AND entity_id = :eid
                ORDER BY uploaded_at DESC
            """),
            {"tid": tenant_uuid, "eid": _to_uuid(receipt["receipt_id"])},
        )
        receipt_attach = [_serialize_attachment(r) for r in att_rows.fetchall()]

    damage_attach: list[dict[str, Any]] = []
    if damage_ids:
        # 用 ANY 而不是 IN，避免大数组语法问题
        att_rows = await db.execute(
            text("""
                SELECT id, entity_type, entity_id, file_url, file_type, file_size,
                       file_name, thumbnail_url, captured_at, gps_lat, gps_lng,
                       uploaded_by, uploaded_at
                FROM delivery_attachments
                WHERE tenant_id = :tid
                  AND entity_type = 'DAMAGE'
                  AND entity_id = ANY(:eids)
                ORDER BY uploaded_at DESC
            """),
            {"tid": tenant_uuid, "eids": damage_ids},
        )
        damage_attach = [_serialize_attachment(r) for r in att_rows.fetchall()]

    # 温度凭证（TASK-3 v368）— 直接调用 delivery_temperature_service.get_temperature_proof
    # 该 service 返回 summary（min/max/avg/超限秒数）+ alerts + 抽样时序 + GPS 摘要，
    # 我们在签收凭证里把它打平为：
    #   temperature_evidence  = 抽样时序（向后兼容：原字段名保留）
    #   temperature_summary   = TASK-3 摘要（最高/最低/超限次数/告警等）
    #   temperature_record_count = 总样本数
    temperature_evidence: list[dict[str, Any]] = []
    temperature_summary: dict[str, Any] = {}
    temperature_alerts: list[dict[str, Any]] = []

    if _TEMP_SERVICE_AVAILABLE:
        try:
            proof = await _temperature_service.get_temperature_proof(
                tenant_id=tenant_id,
                delivery_id=delivery_id,
                db=db,
            )
            temperature_evidence = proof.get("timeline_sampled", []) or []
            temperature_summary = proof.get("summary", {}) or {}
            temperature_alerts = proof.get("alerts", []) or []
        except (LookupError, ValueError, ProgrammingError, DBAPIError, SQLAlchemyError) as exc:
            # TASK-3 表/数据缺失或瞬态查询失败时降级（不阻断签收凭证返回）
            log.warning(
                "temperature_proof_unavailable",
                delivery_id=str(delivery_id),
                error=str(exc),
            )

    # 总样本数：优先取 TASK-3 给的 timeline_full_count（抽样前），否则回退到抽样长度
    temperature_full_count = (
        temperature_summary.get("sample_count")
        if isinstance(temperature_summary, dict)
        else None
    )
    if temperature_full_count is None:
        temperature_full_count = len(temperature_evidence)

    summary = {
        "delivery_id": delivery_id,
        "has_signature": receipt is not None,
        "damage_count": len(damages),
        "pending_damage_count": sum(
            1 for d in damages if d["resolution_status"] == ResolutionStatus.PENDING.value
        ),
        "total_damage_amount_fen": sum(
            (d["damage_amount_fen"] or 0) for d in damages
        ),
        "attachment_count": len(receipt_attach) + len(damage_attach),
        # 向后兼容字段：原值含义为温度记录条数
        "temperature_record_count": int(temperature_full_count or 0),
        "temperature_alert_count": len(temperature_alerts),
    }

    return {
        "summary": summary,
        "receipt": receipt,
        "damages": damages,
        "receipt_attachments": receipt_attach,
        "damage_attachments": damage_attach,
        # 向后兼容：保留 temperature_evidence 字段名（前端已在用）
        "temperature_evidence": temperature_evidence,
        # 新增：TASK-3 的完整摘要 + 告警
        "temperature_summary": temperature_summary,
        "temperature_alerts": temperature_alerts,
    }


# ──────────────────────────────────────────────────────────────────────
# 6. 待处理损坏列表
# ──────────────────────────────────────────────────────────────────────


async def list_pending_damages(
    *,
    tenant_id: str,
    db: AsyncSession,
    store_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """列出 PENDING 状态的损坏记录，可按门店/严重度过滤。

    门店过滤通过 join distribution_orders.target_store_id 实现。
    """
    if severity is not None:
        try:
            Severity(severity)
        except ValueError as exc:
            raise DeliveryProofError(f"invalid severity: {severity}") from exc

    tenant_uuid = _to_uuid(tenant_id)
    await _set_tenant(db, tenant_id)

    params: dict[str, Any] = {"tid": tenant_uuid, "limit": limit, "offset": offset}
    where = [
        "d.tenant_id = :tid",
        "d.is_deleted = false",
        "d.resolution_status = 'PENDING'",
    ]

    if severity is not None:
        where.append("d.severity = :sev")
        params["sev"] = severity

    join_clause = ""
    if store_id is not None:
        join_clause = (
            " JOIN distribution_orders o "
            "ON o.id = d.delivery_id AND o.tenant_id = d.tenant_id"
        )
        where.append("o.target_store_id = :sid")
        params["sid"] = _to_uuid(store_id)

    where_sql = " AND ".join(where)

    rows = await db.execute(
        text(f"""
            SELECT d.id, d.delivery_id, d.item_id, d.ingredient_id, d.batch_no,
                   d.damage_type, d.damaged_qty, d.unit_cost_fen, d.damage_amount_fen,
                   d.description, d.severity, d.reported_by, d.reported_at,
                   d.resolution_status, d.resolved_by, d.resolved_at,
                   d.resolve_action, d.resolve_comment
            FROM delivery_damage_records d
            {join_clause}
            WHERE {where_sql}
            ORDER BY d.reported_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [_serialize_damage(r) for r in rows.fetchall()]

    count_row = await db.execute(
        text(f"""
            SELECT COUNT(*) FROM delivery_damage_records d
            {join_clause}
            WHERE {where_sql}
        """),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_row.scalar_one()

    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


# ──────────────────────────────────────────────────────────────────────
# 7. 处理损坏
# ──────────────────────────────────────────────────────────────────────


_TERMINAL_ACTIONS = {
    ResolutionStatus.RETURNED.value,
    ResolutionStatus.COMPENSATED.value,
    ResolutionStatus.ACCEPTED.value,
}


async def resolve_damage(
    *,
    damage_id: str,
    tenant_id: str,
    db: AsyncSession,
    action: str,
    comment: Optional[str] = None,
    resolve_action_code: Optional[str] = None,
    resolved_by: Optional[str] = None,
) -> dict[str, Any]:
    """处理损坏记录 → 写终态 + 发事件。

    action 必须是 RETURNED|COMPENSATED|ACCEPTED 之一；PENDING 不允许。
    若状态已经是终态，抛 DeliveryProofError（防止重复处理）。
    RETURNED 时事件 metadata 标记 triggers_red_invoice=True，
    财务侧 projector 据此自动开红字凭证（不直接调用财务服务）。
    """
    if action not in _TERMINAL_ACTIONS:
        raise DeliveryProofError(
            f"invalid action {action!r}; must be one of {_TERMINAL_ACTIONS}"
        )

    tenant_uuid = _to_uuid(tenant_id)
    damage_uuid = _to_uuid(damage_id)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT delivery_id, resolution_status, damage_type, damaged_qty,
                   unit_cost_fen, damage_amount_fen, severity, ingredient_id, batch_no
            FROM delivery_damage_records
            WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            LIMIT 1
        """),
        {"id": damage_uuid, "tid": tenant_uuid},
    )
    record = row.first()
    if record is None:
        raise DeliveryProofError(f"damage record {damage_id} not found")
    if record[1] != ResolutionStatus.PENDING.value:
        raise DeliveryProofError(
            f"damage {damage_id} already resolved as {record[1]}; cannot re-resolve"
        )

    delivery_uuid = record[0]
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE delivery_damage_records
            SET resolution_status = :status,
                resolve_action = :ract,
                resolve_comment = :rcom,
                resolved_by = :rby,
                resolved_at = :now,
                updated_at = :now
            WHERE id = :id AND tenant_id = :tid
        """),
        {
            "status": action,
            "ract": resolve_action_code,
            "rcom": comment,
            "rby": _to_uuid(resolved_by) if resolved_by else None,
            "now": now,
            "id": damage_uuid,
            "tid": tenant_uuid,
        },
    )
    await db.flush()

    triggers_red_invoice = action == ResolutionStatus.RETURNED.value
    payload = {
        "damage_id": str(damage_id),
        "delivery_id": str(delivery_uuid),
        "action": action,
        "resolve_action_code": resolve_action_code,
        "comment": comment,
        "damage_type": record[2],
        "damaged_qty": str(record[3]),
        "unit_cost_fen": int(record[4]) if record[4] is not None else None,
        "damage_amount_fen": int(record[5]) if record[5] is not None else None,
        "severity": record[6],
        "ingredient_id": str(record[7]) if record[7] else None,
        "batch_no": record[8],
        "triggers_red_invoice": triggers_red_invoice,
    }
    asyncio.create_task(
        emit_event(
            event_type=DeliveryProofEventType.DAMAGE_RESOLVED,
            tenant_id=tenant_uuid,
            stream_id=str(delivery_uuid),
            payload=payload,
            source_service="tx-supply",
            metadata={
                "resolved_by": resolved_by,
                "triggers_red_invoice": triggers_red_invoice,
            },
        )
    )

    log.info(
        "delivery_damage_resolved",
        damage_id=str(damage_id),
        action=action,
        triggers_red_invoice=triggers_red_invoice,
        tenant_id=tenant_id,
    )
    return {
        "damage_id": str(damage_id),
        "delivery_id": str(delivery_uuid),
        "resolution_status": action,
        "resolve_action": resolve_action_code,
        "resolved_at": now.isoformat(),
        "triggers_red_invoice": triggers_red_invoice,
    }


# ──────────────────────────────────────────────────────────────────────
# 8. 损坏统计
# ──────────────────────────────────────────────────────────────────────


async def get_damage_stats(
    *,
    tenant_id: str,
    db: AsyncSession,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    store_id: Optional[str] = None,
) -> dict[str, Any]:
    """损坏统计（按 damage_type / severity / resolution_status 维度）。"""
    tenant_uuid = _to_uuid(tenant_id)
    await _set_tenant(db, tenant_id)

    where = ["d.tenant_id = :tid", "d.is_deleted = false"]
    params: dict[str, Any] = {"tid": tenant_uuid}

    if from_date is not None:
        where.append("d.reported_at >= :fdate")
        params["fdate"] = datetime.combine(from_date, datetime.min.time(), timezone.utc)
    if to_date is not None:
        where.append("d.reported_at < :tdate")
        params["tdate"] = datetime.combine(to_date, datetime.max.time(), timezone.utc)

    join_clause = ""
    if store_id is not None:
        join_clause = (
            " JOIN distribution_orders o "
            "ON o.id = d.delivery_id AND o.tenant_id = d.tenant_id"
        )
        where.append("o.target_store_id = :sid")
        params["sid"] = _to_uuid(store_id)

    where_sql = " AND ".join(where)

    # 总览
    total_row = await db.execute(
        text(f"""
            SELECT COUNT(*),
                   COALESCE(SUM(d.damage_amount_fen), 0),
                   COUNT(DISTINCT d.delivery_id)
            FROM delivery_damage_records d
            {join_clause}
            WHERE {where_sql}
        """),
        params,
    )
    total_count, total_amount, distinct_delivery = total_row.first()

    # 按 damage_type
    type_rows = await db.execute(
        text(f"""
            SELECT d.damage_type, COUNT(*),
                   COALESCE(SUM(d.damage_amount_fen), 0)
            FROM delivery_damage_records d
            {join_clause}
            WHERE {where_sql}
            GROUP BY d.damage_type
            ORDER BY COUNT(*) DESC
        """),
        params,
    )
    by_type = [
        {"damage_type": r[0], "count": int(r[1]), "amount_fen": int(r[2])}
        for r in type_rows.fetchall()
    ]

    # 按 severity
    sev_rows = await db.execute(
        text(f"""
            SELECT d.severity, COUNT(*),
                   COALESCE(SUM(d.damage_amount_fen), 0)
            FROM delivery_damage_records d
            {join_clause}
            WHERE {where_sql}
            GROUP BY d.severity
        """),
        params,
    )
    by_severity = [
        {"severity": r[0], "count": int(r[1]), "amount_fen": int(r[2])}
        for r in sev_rows.fetchall()
    ]

    # 按 resolution_status
    status_rows = await db.execute(
        text(f"""
            SELECT d.resolution_status, COUNT(*),
                   COALESCE(SUM(d.damage_amount_fen), 0)
            FROM delivery_damage_records d
            {join_clause}
            WHERE {where_sql}
            GROUP BY d.resolution_status
        """),
        params,
    )
    by_status = [
        {"status": r[0], "count": int(r[1]), "amount_fen": int(r[2])}
        for r in status_rows.fetchall()
    ]

    return {
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "store_id": store_id,
        "total_count": int(total_count or 0),
        "total_amount_fen": int(total_amount or 0),
        "distinct_delivery_count": int(distinct_delivery or 0),
        "by_type": by_type,
        "by_severity": by_severity,
        "by_status": by_status,
    }
