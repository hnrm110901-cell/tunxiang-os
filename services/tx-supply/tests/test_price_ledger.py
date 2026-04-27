"""价格台账服务测试（v366）

覆盖：
1. test_record_price_writes_to_db                 — 调 record_price 后写入 supplier_price_history
2. test_record_price_is_idempotent_by_source_doc  — 同 source_doc_id 第二次调用返回已存在
3. test_query_ledger_returns_filtered_by_ingredient_and_window — 过滤参数正确传递
4. test_compute_trend_aggregates_by_week          — 趋势聚合调用正确
5. test_alert_rule_triggers_on_percent_rise       — PERCENT_RISE 规则触发预警
6. test_alert_rule_acknowledge_changes_status     — ack 把 ACTIVE → ACKED
7. test_cross_tenant_isolation                    — 不同 tenant 不会互看（service 设置 RLS）
8. test_invalid_unit_price_rejected               — 负数/浮点价格被拒
9. test_record_price_emits_event                  — emit_event(PRICE.RECORDED) 被调
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.tx_supply.src.services.price_ledger_service as svc

# ──────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
SUPPLIER_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


def _build_db_with_call_log(
    *,
    duplicate_lookup_returns: dict | None = None,
    rules_rows: list[dict] | None = None,
    baseline_avg: float | None = None,
    alert_lookup_row: dict | None = None,
) -> tuple[MagicMock, list[tuple[str, dict]]]:
    """构造 mock AsyncSession：
    - 记录每次 execute(query, params)
    - 按调用次序返回不同结果（按 SQL 关键字识别）
    """
    db = MagicMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    call_log: list[tuple[str, dict]] = []

    def _make_result(*, mappings_rows: list[dict] | None = None,
                     scalar_value: Any = None,
                     one: dict | None = None) -> MagicMock:
        result = MagicMock()
        mp = MagicMock()
        mp.all = MagicMock(return_value=mappings_rows or [])
        mp.one_or_none = MagicMock(return_value=one)
        result.mappings = MagicMock(return_value=mp)
        result.scalar = MagicMock(return_value=scalar_value)
        return result

    async def fake_execute(query, params=None):
        sql = str(query)
        call_log.append((sql, params or {}))
        sql_lower = sql.lower()

        # 1) set_config — return empty
        if "set_config" in sql_lower:
            return _make_result()

        # 2) 幂等查重 SELECT supplier_price_history with source_doc_id filter
        if (
            "from supplier_price_history" in sql_lower
            and "source_doc_id" in sql_lower
            and "select id" in sql_lower
        ):
            return _make_result(one=duplicate_lookup_returns)

        # 3) INSERT supplier_price_history
        if "insert into supplier_price_history" in sql_lower:
            return _make_result()

        # 4) SELECT rules — list_alert_rules
        if "from price_alert_rules" in sql_lower and "select" in sql_lower:
            return _make_result(mappings_rows=rules_rows or [])

        # 5) INSERT price_alerts
        if "insert into price_alerts" in sql_lower:
            return _make_result()

        # 6) baseline avg
        if "avg(unit_price_fen)" in sql_lower and "as avg_p" in sql_lower:
            return _make_result(scalar_value=baseline_avg)

        # 7) 预警 ack 查询
        if (
            "from price_alerts" in sql_lower
            and "select id, status" in sql_lower
        ):
            return _make_result(one=alert_lookup_row)

        # 8) UPDATE price_alerts
        if "update price_alerts" in sql_lower:
            return _make_result()

        # 9) COUNT for query_ledger
        if "count(*)" in sql_lower and "supplier_price_history" in sql_lower:
            return _make_result(scalar_value=0)

        # 10) SELECT items list (no source_doc filter)
        if "from supplier_price_history" in sql_lower and "select" in sql_lower:
            return _make_result(mappings_rows=[])

        # 11) Trend / compare aggregations
        if "date_trunc" in sql_lower or "with agg" in sql_lower:
            return _make_result(mappings_rows=[])

        return _make_result()

    db.execute = AsyncMock(side_effect=fake_execute)
    return db, call_log


# ──────────────────────────────────────────────────────────────────
# 1. test_record_price_writes_to_db
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_price_writes_to_db():
    db, calls = _build_db_with_call_log()
    with patch.object(svc, "emit_event", new_callable=AsyncMock):
        result = await svc.record_price(
            tenant_id=TENANT_A,
            ingredient_id=INGREDIENT_ID,
            supplier_id=SUPPLIER_ID,
            unit_price_fen=4500,
            db=db,
            source_doc_type="receiving",
            source_doc_id=str(uuid.uuid4()),
            source_doc_no="RV-001",
            store_id=STORE_ID,
            evaluate_alerts_after=False,
        )

    assert result["ok"] is True
    assert result["duplicated"] is False
    assert result["data"]["unit_price_fen"] == 4500
    # 必须发生过 INSERT
    sqls = " ".join(c[0].lower() for c in calls)
    assert "insert into supplier_price_history" in sqls
    # 必须先 set_config
    assert "set_config" in calls[0][0].lower()


# ──────────────────────────────────────────────────────────────────
# 2. test_record_price_is_idempotent_by_source_doc
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_price_is_idempotent_by_source_doc():
    src_id = str(uuid.uuid4())
    existing_row = {
        "id": uuid.uuid4(),
        "ingredient_id": uuid.UUID(INGREDIENT_ID),
        "supplier_id": uuid.UUID(SUPPLIER_ID),
        "unit_price_fen": 4500,
        "quantity_unit": "kg",
        "captured_at": datetime.now(timezone.utc),
        "source_doc_type": "receiving",
        "source_doc_id": uuid.UUID(src_id),
        "source_doc_no": "RV-001",
        "store_id": uuid.UUID(STORE_ID),
        "notes": None,
    }
    db, calls = _build_db_with_call_log(duplicate_lookup_returns=existing_row)
    with patch.object(svc, "emit_event", new_callable=AsyncMock):
        result = await svc.record_price(
            tenant_id=TENANT_A,
            ingredient_id=INGREDIENT_ID,
            supplier_id=SUPPLIER_ID,
            unit_price_fen=9999,  # 不同价格，但相同 source_doc_id
            db=db,
            source_doc_type="receiving",
            source_doc_id=src_id,
            evaluate_alerts_after=False,
        )

    assert result["ok"] is True
    assert result["duplicated"] is True
    # 返回的是已存在的价格 4500，不是新传入的 9999
    assert result["data"]["unit_price_fen"] == 4500
    sqls = " ".join(c[0].lower() for c in calls)
    assert "insert into supplier_price_history" not in sqls


# ──────────────────────────────────────────────────────────────────
# 3. test_query_ledger_returns_filtered_by_ingredient_and_window
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_ledger_returns_filtered_by_ingredient_and_window():
    db, calls = _build_db_with_call_log()
    df = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dt = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result = await svc.query_ledger(
        tenant_id=TENANT_A,
        db=db,
        ingredient_id=INGREDIENT_ID,
        date_from=df,
        date_to=dt,
        page=2,
        size=20,
    )
    assert result["ok"] is True
    assert result["page"] == 2
    assert result["size"] == 20

    # 找到 SELECT items 的那次调用
    select_calls = [c for c in calls if "from supplier_price_history" in c[0].lower()
                    and "limit" in c[0].lower()]
    assert select_calls, "expected a SELECT items call"
    _, params = select_calls[-1]
    # 过滤参数正确传递
    assert params["tid"] == TENANT_A
    assert params["ing"] == INGREDIENT_ID
    assert params["df"] == df
    assert params["dt"] == dt
    # 分页 offset = (page-1)*size = 20
    assert params["offset"] == 20
    assert params["limit"] == 20


# ──────────────────────────────────────────────────────────────────
# 4. test_compute_trend_aggregates_by_week
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_trend_aggregates_by_week():
    db, calls = _build_db_with_call_log()
    result = await svc.compute_trend(
        tenant_id=TENANT_A,
        ingredient_id=INGREDIENT_ID,
        db=db,
        bucket="week",
    )
    assert result["ok"] is True
    assert result["bucket"] == "week"
    # 应该出现 date_trunc(:bucket, ...)
    sqls = " ".join(c[0].lower() for c in calls)
    assert "date_trunc(:bucket" in sqls

    # bucket 必须传 'week'
    trend_call = [c for c in calls if "date_trunc(:bucket" in c[0].lower()]
    assert trend_call
    _, params = trend_call[-1]
    assert params["bucket"] == "week"


@pytest.mark.asyncio
async def test_compute_trend_rejects_invalid_bucket():
    db, _ = _build_db_with_call_log()
    result = await svc.compute_trend(
        tenant_id=TENANT_A, ingredient_id=INGREDIENT_ID, db=db, bucket="day"
    )
    assert result["ok"] is False
    assert "week" in result["error"]


# ──────────────────────────────────────────────────────────────────
# 5. test_alert_rule_triggers_on_percent_rise
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_rule_triggers_on_percent_rise():
    """规则：PERCENT_RISE 阈值 20%，基线均价 100 分，当前价 130 分 → 涨幅 30% 命中。"""
    rule_row = {
        "id": uuid.uuid4(),
        "rule_type": "PERCENT_RISE",
        "threshold_value": Decimal("20"),
        "baseline_window_days": 30,
        "ingredient_id": uuid.UUID(INGREDIENT_ID),
    }
    db, calls = _build_db_with_call_log(
        rules_rows=[rule_row],
        baseline_avg=100.0,
    )
    with patch.object(svc, "emit_event", new_callable=AsyncMock) as mock_emit:
        triggered = await svc.evaluate_alerts(
            tenant_id=TENANT_A,
            ingredient_id=INGREDIENT_ID,
            supplier_id=SUPPLIER_ID,
            current_price_fen=130,
            db=db,
        )

    assert len(triggered) == 1
    alert = triggered[0]
    assert alert["severity"] == "CRITICAL"  # 30% >= 30 阈值
    assert alert["status"] == "ACTIVE"
    assert alert["current_price_fen"] == 130
    assert alert["baseline_price_fen"] == 100

    # ALERT_TRIGGERED 事件被发射（asyncio.create_task 包装）
    # 让事件循环跑一下
    await asyncio.sleep(0)
    assert mock_emit.called
    call_kwargs = mock_emit.call_args.kwargs
    assert call_kwargs["event_type"].value == "price.alert_triggered"

    # 必须 INSERT 了一条 price_alerts
    sqls = " ".join(c[0].lower() for c in calls)
    assert "insert into price_alerts" in sqls


@pytest.mark.asyncio
async def test_alert_rule_no_trigger_when_below_threshold():
    """涨幅未达阈值时不触发。"""
    rule_row = {
        "id": uuid.uuid4(),
        "rule_type": "PERCENT_RISE",
        "threshold_value": Decimal("50"),
        "baseline_window_days": 30,
        "ingredient_id": None,
    }
    db, _ = _build_db_with_call_log(
        rules_rows=[rule_row],
        baseline_avg=100.0,
    )
    with patch.object(svc, "emit_event", new_callable=AsyncMock):
        triggered = await svc.evaluate_alerts(
            tenant_id=TENANT_A,
            ingredient_id=INGREDIENT_ID,
            supplier_id=SUPPLIER_ID,
            current_price_fen=110,  # 涨幅 10% < 50%
            db=db,
        )
    assert triggered == []


# ──────────────────────────────────────────────────────────────────
# 6. test_alert_rule_acknowledge_changes_status
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_rule_acknowledge_changes_status():
    alert_id = str(uuid.uuid4())
    db, calls = _build_db_with_call_log(
        alert_lookup_row={"id": uuid.UUID(alert_id), "status": "ACTIVE"},
    )
    result = await svc.acknowledge_alert(
        tenant_id=TENANT_A,
        alert_id=alert_id,
        acked_by=USER_ID,
        db=db,
        ack_comment="确认采购价异常，已联系供应商",
    )
    assert result["ok"] is True
    assert result["data"]["status"] == "ACKED"
    sqls = " ".join(c[0].lower() for c in calls)
    assert "update price_alerts" in sqls


@pytest.mark.asyncio
async def test_alert_acknowledge_rejects_already_acked():
    alert_id = str(uuid.uuid4())
    db, _ = _build_db_with_call_log(
        alert_lookup_row={"id": uuid.UUID(alert_id), "status": "ACKED"},
    )
    result = await svc.acknowledge_alert(
        tenant_id=TENANT_A,
        alert_id=alert_id,
        acked_by=USER_ID,
        db=db,
    )
    assert result["ok"] is False
    assert "ACKED" in result["error"]


@pytest.mark.asyncio
async def test_alert_acknowledge_rejects_not_found():
    db, _ = _build_db_with_call_log(alert_lookup_row=None)
    result = await svc.acknowledge_alert(
        tenant_id=TENANT_A,
        alert_id=str(uuid.uuid4()),
        acked_by=USER_ID,
        db=db,
    )
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


# ──────────────────────────────────────────────────────────────────
# 7. test_cross_tenant_isolation — service 层 set_config 必须用调用方 tenant
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_isolation():
    """两个 tenant 分别调用 query_ledger，每次的 set_config 必须用各自 tenant_id。

    这是 RLS 隔离的 service 层保障：DB 层由迁移的 RLS 策略确保数据不互看，
    但 service 层必须先正确设置 app.tenant_id 才能让 RLS 起作用。
    """
    db_a, calls_a = _build_db_with_call_log()
    db_b, calls_b = _build_db_with_call_log()

    await svc.query_ledger(tenant_id=TENANT_A, db=db_a)
    await svc.query_ledger(tenant_id=TENANT_B, db=db_b)

    # tenant A 的 set_config 必须用 TENANT_A
    set_a = [c for c in calls_a if "set_config" in c[0].lower()]
    assert set_a
    assert set_a[0][1]["tid"] == TENANT_A

    set_b = [c for c in calls_b if "set_config" in c[0].lower()]
    assert set_b
    assert set_b[0][1]["tid"] == TENANT_B
    # 双向检查：A 的调用绝不会带 B 的 tenant
    for sql, params in calls_a:
        if isinstance(params, dict) and "tid" in params:
            assert params["tid"] != TENANT_B, f"tenant A 调用泄漏到 tenant B: {sql}"


# ──────────────────────────────────────────────────────────────────
# 8. 校验：负价 / 非整数价被拒
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_unit_price_rejected():
    db, _ = _build_db_with_call_log()
    result_neg = await svc.record_price(
        tenant_id=TENANT_A,
        ingredient_id=INGREDIENT_ID,
        supplier_id=SUPPLIER_ID,
        unit_price_fen=-1,
        db=db,
    )
    assert result_neg["ok"] is False

    result_float = await svc.record_price(
        tenant_id=TENANT_A,
        ingredient_id=INGREDIENT_ID,
        supplier_id=SUPPLIER_ID,
        unit_price_fen=12.34,  # type: ignore[arg-type]
        db=db,
    )
    assert result_float["ok"] is False


# ──────────────────────────────────────────────────────────────────
# 9. test_record_price_emits_event
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_price_emits_event():
    db, _ = _build_db_with_call_log()
    with patch.object(svc, "emit_event", new_callable=AsyncMock) as mock_emit:
        await svc.record_price(
            tenant_id=TENANT_A,
            ingredient_id=INGREDIENT_ID,
            supplier_id=SUPPLIER_ID,
            unit_price_fen=4500,
            db=db,
            source_doc_type="receiving",
            source_doc_id=str(uuid.uuid4()),
            evaluate_alerts_after=False,
        )
        # asyncio.create_task 需要 event loop 跑一下
        await asyncio.sleep(0)

    assert mock_emit.called
    call_kwargs = mock_emit.call_args.kwargs
    assert call_kwargs["event_type"].value == "price.recorded"
    assert call_kwargs["tenant_id"] == TENANT_A
    assert call_kwargs["payload"]["unit_price_fen"] == 4500
    assert call_kwargs["source_service"] == "tx-supply"


# ──────────────────────────────────────────────────────────────────
# 10. 创建规则 + 列举规则
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_alert_rule_validates_rule_type():
    db, _ = _build_db_with_call_log()
    bad = await svc.create_alert_rule(
        tenant_id=TENANT_A,
        rule_type="UNKNOWN_TYPE",
        threshold_value=Decimal("10"),
        db=db,
    )
    assert bad["ok"] is False
    assert "rule_type" in bad["error"]


@pytest.mark.asyncio
async def test_create_alert_rule_inserts():
    db, calls = _build_db_with_call_log()
    result = await svc.create_alert_rule(
        tenant_id=TENANT_A,
        rule_type="PERCENT_RISE",
        threshold_value=Decimal("15"),
        db=db,
        baseline_window_days=14,
    )
    assert result["ok"] is True
    assert result["data"]["rule_type"] == "PERCENT_RISE"
    sqls = " ".join(c[0].lower() for c in calls)
    assert "insert into price_alert_rules" in sqls
