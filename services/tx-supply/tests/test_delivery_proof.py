"""配送签收凭证 API + 服务测试（TASK-4，v369）

覆盖 9 个用例：
  1. test_submit_signature_creates_receipt
  2. test_submit_signature_rejects_invalid_base64
  3. test_submit_signature_idempotent_per_delivery        — 第二次签收被拒
  4. test_record_damage_calculates_amount                 — DB Computed 列回读
  5. test_attach_file_to_damage
  6. test_get_complete_proof_aggregates_signature_and_damages
  7. test_resolve_damage_emits_event                      — RETURNED 事件含 triggers_red_invoice
  8. test_cross_tenant_isolation                          — 跨租户必须不可见
  9. test_signature_size_limit_enforced                   — > 200KB 必须拒收

策略：service 层用纯 mock DB（AsyncMock + 自定义 execute side effect 模拟 RLS+查询），
不连真实 PostgreSQL。emit_event 通过 patch 拦截。
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.tx_supply.src.services import delivery_proof_service as svc
from services.tx_supply.src.services.delivery_proof_service import (
    DeliveryProofError,
)

# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
DELIVERY_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())

# 1x1 透明 PNG（67 字节）
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
TINY_PNG_DATA_URL = f"data:image/png;base64,{TINY_PNG_B64}"


# ──────────────────────────────────────────────────────────────────────
# Mock DB 工厂
# ──────────────────────────────────────────────────────────────────────


def _result(rows=None, scalar=None):
    """构造一个 SQLAlchemy Result 替身。

    支持 .first() / .fetchall() / .scalar_one() / .mappings().fetchall()。
    """
    res = MagicMock()
    res.first.return_value = rows[0] if rows else None
    res.fetchall.return_value = rows or []
    res.scalar_one.return_value = scalar if scalar is not None else len(rows or [])
    res.scalar.return_value = scalar
    mapping_res = MagicMock()
    mapping_res.fetchall.return_value = []
    res.mappings.return_value = mapping_res
    return res


def _make_db(execute_side_effect):
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _isolated_upload_dir(monkeypatch, tmp_path: Path) -> Path:
    """让对象存储 mock 写到测试隔离目录，避免污染 /tmp。"""
    monkeypatch.setattr(svc, "_LOCAL_UPLOAD_DIR", tmp_path)
    return tmp_path


# ──────────────────────────────────────────────────────────────────────
# 1. submit_signature 创建签收单
# ──────────────────────────────────────────────────────────────────────


class TestSubmitSignature:
    @pytest.mark.asyncio
    async def test_submit_signature_creates_receipt(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        _isolated_upload_dir(monkeypatch, tmp_path)
        store_uuid = uuid.uuid4()

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql:
                return _result()
            if "FROM delivery_receipts" in sql and "SELECT id" in sql:
                # 唯一性预检：未存在
                return _result(rows=[])
            if "FROM distribution_orders" in sql and "target_store_id" in sql:
                return _result(rows=[(store_uuid,)])
            if "INSERT INTO delivery_receipts" in sql:
                return _result()
            if "UPDATE store_receiving_confirmations" in sql:
                return _result()
            return _result()

        db = _make_db(execute)

        with patch(
            "services.tx_supply.src.services.delivery_proof_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
            side_effect=lambda coro: coro.close() or MagicMock(),
        ):
            result = await svc.submit_signature(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                signer_name="王店长",
                signature_base64=TINY_PNG_DATA_URL,
                signer_role="STORE_MANAGER",
                signer_phone="13800138000",
                gps_lat=Decimal("28.1234567"),
                gps_lng=Decimal("112.7654321"),
                device_info={"model": "Sunmi T2", "os": "Android 11"},
            )

        assert result["delivery_id"] == DELIVERY_ID
        assert result["signer_name"] == "王店长"
        assert result["signature_image_url"].startswith("s3://tunxiang-supply/")
        assert result["signature_size_bytes"] > 0
        assert "receipt_id" in result
        # 文件确实落到隔离目录
        files = list(tmp_path.rglob("*.png"))
        assert len(files) == 1

    @pytest.mark.asyncio
    async def test_submit_signature_rejects_invalid_base64(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        _isolated_upload_dir(monkeypatch, tmp_path)

        async def execute(stmt, params=None):
            return _result()

        db = _make_db(execute)

        # 不是 data:image/... 前缀
        with pytest.raises(DeliveryProofError, match="data:"):
            await svc.submit_signature(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                signer_name="王店长",
                signature_base64="not a base64 image",
            )

        # 错误 mime（gif 不被允许做签名图）
        with pytest.raises(DeliveryProofError, match="signature mime"):
            await svc.submit_signature(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                signer_name="王店长",
                signature_base64=f"data:image/gif;base64,{TINY_PNG_B64}",
            )

        # base64 内容损坏
        with pytest.raises(DeliveryProofError, match="base64 decode failed"):
            await svc.submit_signature(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                signer_name="王店长",
                signature_base64="data:image/png;base64,!!!notbase64!!!",
            )

    @pytest.mark.asyncio
    async def test_submit_signature_idempotent_per_delivery(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        _isolated_upload_dir(monkeypatch, tmp_path)
        existing_receipt_id = uuid.uuid4()

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql:
                return _result()
            if "FROM delivery_receipts" in sql:
                # 已存在签收单 → 唯一性预检命中
                return _result(rows=[(existing_receipt_id,)])
            return _result()

        db = _make_db(execute)

        with pytest.raises(DeliveryProofError, match="already signed"):
            await svc.submit_signature(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                signer_name="后到的人",
                signature_base64=TINY_PNG_DATA_URL,
            )


# ──────────────────────────────────────────────────────────────────────
# 4. record_damage 自动计算金额
# ──────────────────────────────────────────────────────────────────────


class TestRecordDamage:
    @pytest.mark.asyncio
    async def test_record_damage_calculates_amount(self) -> None:
        # damaged_qty=2.5, unit_cost_fen=8800 → 22000
        expected_amount = 22000

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql:
                return _result()
            if "INSERT INTO delivery_damage_records" in sql:
                return _result()
            if "SELECT damage_amount_fen" in sql:
                # DB Computed 列回读
                return _result(rows=[(expected_amount,)])
            return _result()

        db = _make_db(execute)

        with patch(
            "services.tx_supply.src.services.delivery_proof_service.emit_event",
            new_callable=AsyncMock,
        ), patch(
            "asyncio.create_task",
            side_effect=lambda coro: coro.close() or MagicMock(),
        ):
            result = await svc.record_damage(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                damage_type="BROKEN",
                damaged_qty=Decimal("2.5"),
                unit_cost_fen=8800,
                ingredient_id=INGREDIENT_ID,
                batch_no="B20260427-01",
                description="纸箱破损 + 内容物挤压",
                severity="MAJOR",
                reported_by=USER_ID,
            )

        assert result["damage_amount_fen"] == expected_amount
        assert result["damage_type"] == "BROKEN"
        assert result["severity"] == "MAJOR"
        assert result["resolution_status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_record_damage_rejects_invalid_type(self) -> None:
        db = _make_db(lambda *a, **k: _result())

        with pytest.raises(DeliveryProofError, match="invalid damage_type"):
            await svc.record_damage(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                damage_type="MELTED",  # 不存在的枚举
                damaged_qty=Decimal("1"),
            )


# ──────────────────────────────────────────────────────────────────────
# 5. attach_file 给损坏记录上传附件
# ──────────────────────────────────────────────────────────────────────


class TestAttachFile:
    @pytest.mark.asyncio
    async def test_attach_file_to_damage(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        _isolated_upload_dir(monkeypatch, tmp_path)
        damage_id = str(uuid.uuid4())

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql:
                return _result()
            if "FROM delivery_damage_records" in sql and "SELECT 1" in sql:
                return _result(rows=[(1,)])
            if "INSERT INTO delivery_attachments" in sql:
                return _result()
            return _result()

        db = _make_db(execute)

        photo_b64 = base64.b64encode(b"\xff\xd8\xffJPEG_FAKE_BODY").decode()
        result = await svc.attach_file(
            tenant_id=TENANT_A,
            db=db,
            entity_type="DAMAGE",
            entity_id=damage_id,
            file_base64=f"data:image/jpeg;base64,{photo_b64}",
            file_name="damage_001.jpg",
            captured_at=datetime.now(timezone.utc),
            uploaded_by=USER_ID,
        )

        assert result["entity_type"] == "DAMAGE"
        assert result["entity_id"] == damage_id
        assert result["file_url"].startswith("s3://tunxiang-supply/")
        assert result["file_type"] == "image/jpeg"
        files = list(tmp_path.rglob("*.jpg"))
        assert len(files) == 1


# ──────────────────────────────────────────────────────────────────────
# 6. get_complete_proof 聚合签名 + 损坏 + 附件
# ──────────────────────────────────────────────────────────────────────


class TestGetCompleteProof:
    @pytest.mark.asyncio
    async def test_get_complete_proof_aggregates_signature_and_damages(self) -> None:
        receipt_id = uuid.uuid4()
        damage_id = uuid.uuid4()
        store_id = uuid.uuid4()
        signed_at = datetime.now(timezone.utc)

        # 模拟 receipt 行
        receipt_row = (
            receipt_id, uuid.UUID(DELIVERY_ID), store_id, "王店长", "STORE_MANAGER",
            "13800138000", signed_at, "s3://tunxiang-supply/x/y.png",
            None, None, {"model": "Sunmi T2"}, None, signed_at,
        )

        damage_row = (
            damage_id, uuid.UUID(DELIVERY_ID), None, uuid.UUID(INGREDIENT_ID),
            "B-1", "BROKEN", Decimal("2.5"), 8800, 22000, "破损",
            "MAJOR", uuid.UUID(USER_ID), signed_at,
            "PENDING", None, None, None, None,
        )

        attachment_row = (
            uuid.uuid4(), "DAMAGE", damage_id,
            "s3://tunxiang-supply/x/photo.jpg",
            "image/jpeg", 12345, "photo.jpg", None, signed_at,
            None, None, uuid.UUID(USER_ID), signed_at,
        )

        call_log: list[str] = []

        async def execute(stmt, params=None):
            sql = str(stmt)
            call_log.append(sql)
            if "set_config" in sql:
                return _result()
            if "FROM delivery_receipts" in sql and "WHERE tenant_id" in sql:
                return _result(rows=[receipt_row])
            if "FROM delivery_damage_records" in sql and "ORDER BY reported_at" in sql:
                return _result(rows=[damage_row])
            if "FROM delivery_attachments" in sql and "RECEIPT" in sql:
                return _result(rows=[])
            if "FROM delivery_attachments" in sql and "DAMAGE" in sql:
                return _result(rows=[attachment_row])
            if "information_schema.tables" in sql:
                # cold_chain_evidence 不存在
                return _result(rows=[])
            return _result()

        db = _make_db(execute)

        proof = await svc.get_complete_proof(
            delivery_id=DELIVERY_ID,
            tenant_id=TENANT_A,
            db=db,
        )

        assert proof["summary"]["has_signature"] is True
        assert proof["summary"]["damage_count"] == 1
        assert proof["summary"]["pending_damage_count"] == 1
        assert proof["summary"]["total_damage_amount_fen"] == 22000
        assert proof["summary"]["attachment_count"] == 1
        assert proof["receipt"]["signer_name"] == "王店长"
        assert proof["damages"][0]["damage_type"] == "BROKEN"
        assert proof["damage_attachments"][0]["file_url"].endswith("photo.jpg")
        # 温度凭证为空（TASK-3 表不存在）
        assert proof["temperature_evidence"] == []


# ──────────────────────────────────────────────────────────────────────
# 7. resolve_damage 触发事件（含 triggers_red_invoice 标志）
# ──────────────────────────────────────────────────────────────────────


class TestResolveDamage:
    @pytest.mark.asyncio
    async def test_resolve_damage_emits_event(self) -> None:
        damage_id = str(uuid.uuid4())
        delivery_uuid = uuid.UUID(DELIVERY_ID)

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql:
                return _result()
            if "SELECT delivery_id, resolution_status" in sql:
                # 当前状态 PENDING
                return _result(
                    rows=[(
                        delivery_uuid, "PENDING", "BROKEN", Decimal("2.5"),
                        8800, 22000, "MAJOR", uuid.UUID(INGREDIENT_ID), "B-1",
                    )]
                )
            if "UPDATE delivery_damage_records" in sql:
                return _result()
            return _result()

        db = _make_db(execute)

        captured: dict = {}

        async def fake_emit(**kwargs):
            captured.update(kwargs)
            return "evt-1"

        async def run_task(coro):
            await coro

        with patch(
            "services.tx_supply.src.services.delivery_proof_service.emit_event",
            new=fake_emit,
        ), patch(
            "asyncio.create_task",
            side_effect=lambda coro: asyncio.ensure_future(coro),
        ):
            result = await svc.resolve_damage(
                damage_id=damage_id,
                tenant_id=TENANT_A,
                db=db,
                action="RETURNED",
                comment="退回供应商，开红字凭证",
                resolved_by=USER_ID,
            )
            # 等事件协程跑完
            await asyncio.sleep(0)

        assert result["resolution_status"] == "RETURNED"
        assert result["triggers_red_invoice"] is True
        # 事件被发射
        assert captured.get("event_type").value == "delivery.damage_resolved"
        assert captured["payload"]["triggers_red_invoice"] is True
        assert captured["payload"]["action"] == "RETURNED"
        assert captured["metadata"]["triggers_red_invoice"] is True

    @pytest.mark.asyncio
    async def test_resolve_damage_rejects_pending(self) -> None:
        async def execute(stmt, params=None):
            return _result()

        db = _make_db(execute)
        with pytest.raises(DeliveryProofError, match="invalid action"):
            await svc.resolve_damage(
                damage_id=str(uuid.uuid4()),
                tenant_id=TENANT_A,
                db=db,
                action="PENDING",  # 不是终态
            )

    @pytest.mark.asyncio
    async def test_resolve_damage_rejects_double_resolve(self) -> None:
        damage_id = str(uuid.uuid4())

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql:
                return _result()
            if "SELECT delivery_id, resolution_status" in sql:
                # 已是终态
                return _result(
                    rows=[(
                        uuid.UUID(DELIVERY_ID), "RETURNED", "BROKEN", Decimal("1"),
                        100, 100, "MINOR", None, None,
                    )]
                )
            return _result()

        db = _make_db(execute)
        with pytest.raises(DeliveryProofError, match="already resolved"):
            await svc.resolve_damage(
                damage_id=damage_id,
                tenant_id=TENANT_A,
                db=db,
                action="ACCEPTED",
            )


# ──────────────────────────────────────────────────────────────────────
# 8. cross-tenant 隔离 — get_receipt 在错租户下应得 None
# ──────────────────────────────────────────────────────────────────────


class TestCrossTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_isolation(self) -> None:
        captured_tids: list = []

        async def execute(stmt, params=None):
            sql = str(stmt)
            if "set_config" in sql and params:
                captured_tids.append(params.get("tid"))
                return _result()
            if "FROM delivery_receipts" in sql and params:
                # RLS 会让另一租户读不到 → 模拟空结果
                if params.get("tid") == uuid.UUID(TENANT_B):
                    return _result(rows=[])
                return _result(rows=[])
            return _result()

        db = _make_db(execute)
        result = await svc.get_receipt(
            delivery_id=DELIVERY_ID,
            tenant_id=TENANT_B,
            db=db,
        )
        assert result is None
        # set_config 必须用 TENANT_B（验证 RLS 上下文确实切了）
        assert TENANT_B in captured_tids


# ──────────────────────────────────────────────────────────────────────
# 9. 签名图大小 > 200KB 应被拒
# ──────────────────────────────────────────────────────────────────────


class TestSignatureSizeLimit:
    @pytest.mark.asyncio
    async def test_signature_size_limit_enforced(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        _isolated_upload_dir(monkeypatch, tmp_path)

        async def execute(stmt, params=None):
            return _result()

        db = _make_db(execute)

        # 构造 > 200KB 的合法 PNG base64
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (svc.MAX_SIGNATURE_SIZE_BYTES + 100)
        big_b64 = base64.b64encode(oversized).decode()
        big_data_url = f"data:image/png;base64,{big_b64}"

        with pytest.raises(DeliveryProofError, match="exceeds limit"):
            await svc.submit_signature(
                delivery_id=DELIVERY_ID,
                tenant_id=TENANT_A,
                db=db,
                signer_name="测试",
                signature_base64=big_data_url,
            )

        # 落盘文件不应产生
        assert list(tmp_path.rglob("*")) == []


# ──────────────────────────────────────────────────────────────────────
# 额外：data_url 解析单元测试
# ──────────────────────────────────────────────────────────────────────


class TestParseDataUrl:
    def test_parse_valid_png(self) -> None:
        mime, body = svc._parse_data_url(TINY_PNG_DATA_URL)
        assert mime == "image/png"
        assert len(body) > 0

    def test_parse_missing_comma(self) -> None:
        with pytest.raises(DeliveryProofError, match="missing comma"):
            svc._parse_data_url("data:image/png;base64ABCD")

    def test_parse_missing_base64_marker(self) -> None:
        with pytest.raises(DeliveryProofError, match="missing ';base64'"):
            svc._parse_data_url("data:image/png,abc")

    def test_parse_empty_body(self) -> None:
        with pytest.raises(DeliveryProofError, match="empty"):
            svc._parse_data_url("data:image/png;base64,")
