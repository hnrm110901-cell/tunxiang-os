"""TASK-3 ↔ TASK-4 集成接缝测试（hotfix v371 配套）

验证 get_complete_proof 调用 delivery_temperature_service.get_temperature_proof
而非旧的 information_schema + cold_chain_evidence 探测路径。

覆盖：
  1. test_complete_proof_includes_temperature_data    — 正常路径，温度数据被聚合到凭证里
  2. test_complete_proof_degrades_on_temperature_failure — 温度服务异常时凭证仍可返回
  3. test_complete_proof_no_longer_queries_cold_chain  — 不再访问 cold_chain_evidence
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.tx_supply.src.services import delivery_proof_service as svc
from sqlalchemy.exc import ProgrammingError

TENANT_A = str(uuid.uuid4())
DELIVERY_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


def _result(rows=None, scalar=None):
    """构造一个 SQLAlchemy Result 替身（与 test_delivery_proof.py 对齐）。"""
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


def _build_complete_proof_db():
    """构造一个能跑通 get_complete_proof 主路径的 mock DB。"""
    receipt_id = uuid.uuid4()
    damage_id = uuid.uuid4()
    store_id = uuid.uuid4()
    signed_at = datetime.now(timezone.utc)

    receipt_row = (
        receipt_id, uuid.UUID(DELIVERY_ID), store_id, "王店长", "STORE_MANAGER",
        "13800138000", signed_at, "s3://tunxiang-supply/x/y.png",
        None, None, {"model": "Sunmi T2"}, None, signed_at,
    )

    damage_row = (
        damage_id, uuid.UUID(DELIVERY_ID), None, uuid.UUID(INGREDIENT_ID),
        "B-1", "BROKEN", 2.5, 8800, 22000, "破损",
        "MAJOR", uuid.UUID(USER_ID), signed_at,
        "PENDING", None, None, None, None,
    )

    sql_log: list[str] = []

    async def execute(stmt, params=None):
        sql = str(stmt)
        sql_log.append(sql)
        if "set_config" in sql:
            return _result()
        if "FROM delivery_receipts" in sql and "WHERE tenant_id" in sql:
            return _result(rows=[receipt_row])
        if "FROM delivery_damage_records" in sql and "ORDER BY reported_at" in sql:
            return _result(rows=[damage_row])
        if "FROM delivery_attachments" in sql:
            return _result(rows=[])
        # 兜底：所有兜其它 SELECT 都返回空
        return _result()

    return _make_db(execute), sql_log


# ─────────────────────────────────────────────────────────────────────
# 1. 正常路径：温度数据被聚合
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_proof_includes_temperature_data() -> None:
    """get_complete_proof 应该把 TASK-3 的 timeline_sampled / summary / alerts 都打平进来。"""
    db, _sql_log = _build_complete_proof_db()

    fake_proof = {
        "delivery_id": DELIVERY_ID,
        "summary": {
            "delivery_id": DELIVERY_ID,
            "sample_count": 120,
            "min_celsius": -2.5,
            "max_celsius": 4.8,
            "avg_celsius": 1.2,
            "alert_count": 1,
            "total_breach_seconds": 180,
        },
        "alerts": [
            {
                "id": str(uuid.uuid4()),
                "severity": "WARNING",
                "breach_type": "HIGH",
                "duration_seconds": 180,
            }
        ],
        "timeline_sampled": [
            {"recorded_at": "2026-04-27T10:00:00+00:00", "temperature_celsius": 0.5},
            {"recorded_at": "2026-04-27T10:01:00+00:00", "temperature_celsius": 1.0},
        ],
        "timeline_full_count": 120,
        "sample_step_seconds": 60,
        "gps_trail_summary": {"point_count": 0, "start": None, "end": None},
        "generated_at": "2026-04-27T10:30:00+00:00",
    }

    with patch.object(
        svc._temperature_service,
        "get_temperature_proof",
        new=AsyncMock(return_value=fake_proof),
    ) as mock_proof:
        proof = await svc.get_complete_proof(
            delivery_id=DELIVERY_ID,
            tenant_id=TENANT_A,
            db=db,
        )

    # service 被调用一次，且参数是 kw（tenant_id/delivery_id/db）
    assert mock_proof.await_count == 1
    call_kwargs = mock_proof.await_args.kwargs
    assert call_kwargs["tenant_id"] == TENANT_A
    assert call_kwargs["delivery_id"] == DELIVERY_ID

    # temperature_evidence 是抽样时序（向后兼容字段名）
    assert len(proof["temperature_evidence"]) == 2
    assert proof["temperature_evidence"][0]["temperature_celsius"] == 0.5

    # 新增字段：summary + alerts 都被打平
    assert proof["temperature_summary"]["min_celsius"] == -2.5
    assert proof["temperature_summary"]["max_celsius"] == 4.8
    assert proof["temperature_summary"]["alert_count"] == 1
    assert len(proof["temperature_alerts"]) == 1
    assert proof["temperature_alerts"][0]["severity"] == "WARNING"

    # summary 字段：record_count 用全量样本数（不是抽样后的 2）
    assert proof["summary"]["temperature_record_count"] == 120
    assert proof["summary"]["temperature_alert_count"] == 1


# ─────────────────────────────────────────────────────────────────────
# 2. 降级路径：温度服务异常时凭证仍能返回
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_proof_degrades_on_temperature_failure() -> None:
    """TASK-3 表/服务异常时应静默降级，不影响签收凭证整体返回。"""
    db, _sql_log = _build_complete_proof_db()

    with patch.object(
        svc._temperature_service,
        "get_temperature_proof",
        new=AsyncMock(side_effect=ProgrammingError("stmt", {}, Exception("table missing"))),
    ):
        proof = await svc.get_complete_proof(
            delivery_id=DELIVERY_ID,
            tenant_id=TENANT_A,
            db=db,
        )

    # 签收主体不受影响
    assert proof["summary"]["has_signature"] is True
    assert proof["summary"]["damage_count"] == 1

    # 温度部分降级为空
    assert proof["temperature_evidence"] == []
    assert proof["temperature_summary"] == {}
    assert proof["temperature_alerts"] == []
    assert proof["summary"]["temperature_record_count"] == 0
    assert proof["summary"]["temperature_alert_count"] == 0


# ─────────────────────────────────────────────────────────────────────
# 3. 不再走旧 cold_chain_evidence / information_schema 路径
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_proof_no_longer_queries_cold_chain() -> None:
    """旧实现会查 information_schema 探测 cold_chain_evidence — 这条 SQL 应彻底消失。"""
    db, sql_log = _build_complete_proof_db()

    with patch.object(
        svc._temperature_service,
        "get_temperature_proof",
        new=AsyncMock(return_value={
            "summary": {"sample_count": 0},
            "alerts": [],
            "timeline_sampled": [],
        }),
    ):
        await svc.get_complete_proof(
            delivery_id=DELIVERY_ID,
            tenant_id=TENANT_A,
            db=db,
        )

    joined_sql = "\n".join(sql_log).lower()
    assert "cold_chain_evidence" not in joined_sql, (
        "旧路径残留：get_complete_proof 不应再查 cold_chain_evidence 表"
    )
    assert "information_schema.tables" not in joined_sql, (
        "旧路径残留：get_complete_proof 不应再用 information_schema 探测温度表"
    )
