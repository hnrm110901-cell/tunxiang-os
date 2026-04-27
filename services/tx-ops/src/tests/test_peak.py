"""高峰值守单元测试 — 使用 mock AsyncSession

覆盖:
  - 高峰检测（高峰/非高峰）
  - 档口负载监控
  - 等位拥堵指标
  - 高峰事件处理
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DEPT_ID = str(uuid.uuid4())


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_mapping(data: dict):
    m = MagicMock()
    m.__getitem__ = lambda self, key: data[key]
    m.get = lambda key, default=None: data.get(key, default)
    return m


# ─── 高峰检测 — 是高峰 ───


@pytest.mark.asyncio
async def test_detect_peak_is_peak():
    """detect_peak: 上座率>=80% 应判定为高峰"""
    from services.peak_management import detect_peak

    session = _mock_session()

    set_config = MagicMock()

    # 上座率: 40/50 = 80%
    occ_result = MagicMock()
    occ_mappings = MagicMock()
    occ_mappings.first.return_value = _make_mapping(
        {
            "occupied_count": 40,
            "total_tables": 50,
        }
    )
    occ_result.mappings.return_value = occ_mappings

    # 等位: 15
    queue_result = MagicMock()
    queue_result.scalar.return_value = 15

    session.execute.side_effect = [set_config, occ_result, queue_result]

    result = await detect_peak(
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["is_peak"] is True
    assert result["peak_level"] == "peak"
    assert result["occupancy_rate"] == 0.8
    assert result["queue_count"] == 15


# ─── 高峰检测 — 非高峰 ───


@pytest.mark.asyncio
async def test_detect_peak_not_peak():
    """detect_peak: 上座率低+等位少应判定为非高峰"""
    from services.peak_management import detect_peak

    session = _mock_session()

    set_config = MagicMock()

    occ_result = MagicMock()
    occ_mappings = MagicMock()
    occ_mappings.first.return_value = _make_mapping(
        {
            "occupied_count": 10,
            "total_tables": 50,
        }
    )
    occ_result.mappings.return_value = occ_mappings

    queue_result = MagicMock()
    queue_result.scalar.return_value = 2

    session.execute.side_effect = [set_config, occ_result, queue_result]

    result = await detect_peak(
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["is_peak"] is False
    assert result["peak_level"] == "normal"
    assert result["occupancy_rate"] == 0.2


# ─── 档口负载监控 ───


@pytest.mark.asyncio
async def test_get_dept_load_monitor():
    """get_dept_load_monitor: 返回各档口负载率"""
    from services.peak_management import get_dept_load_monitor

    session = _mock_session()

    set_config = MagicMock()
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.all.return_value = [
        _make_mapping(
            {
                "dept_id": uuid.UUID(DEPT_ID),
                "dept_name": "热炒档",
                "capacity_per_hour": 30,
                "pending_count": 8,
                "avg_wait_seconds": 300.0,
            }
        ),
    ]
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config, query_result]

    result = await get_dept_load_monitor(
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert len(result["departments"]) == 1
    dept = result["departments"][0]
    assert dept["dept_name"] == "热炒档"
    assert dept["pending_count"] == 8
    # load_rate = 8 / (30/6) = 8/5 = 1.6
    assert dept["load_rate"] == 1.6
    assert dept["is_overloaded"] is True
    assert result["overloaded_count"] == 1


# ─── 等位拥堵指标 ───


@pytest.mark.asyncio
async def test_get_queue_pressure():
    """get_queue_pressure: 按桌型汇总等位"""
    from services.peak_management import get_queue_pressure

    session = _mock_session()

    set_config = MagicMock()

    # 等位队列
    queue_result = MagicMock()
    queue_mappings = MagicMock()
    queue_mappings.all.return_value = [
        _make_mapping(
            {
                "table_type": "4人桌",
                "queue_count": 8,
                "avg_wait_seconds": 1200.0,
                "max_wait_seconds": 2400.0,
                "earliest_ticket": datetime.now(timezone.utc),
            }
        ),
        _make_mapping(
            {
                "table_type": "包间",
                "queue_count": 3,
                "avg_wait_seconds": 600.0,
                "max_wait_seconds": 900.0,
                "earliest_ticket": datetime.now(timezone.utc),
            }
        ),
    ]
    queue_result.mappings.return_value = queue_mappings

    # 翻台速度
    turnover_result = MagicMock()
    turnover_mappings = MagicMock()
    turnover_mappings.all.return_value = [
        _make_mapping({"table_type": "4人桌", "avg_dining_seconds": 3600.0}),
        _make_mapping({"table_type": "包间", "avg_dining_seconds": 5400.0}),
    ]
    turnover_result.mappings.return_value = turnover_mappings

    session.execute.side_effect = [set_config, queue_result, turnover_result]

    result = await get_queue_pressure(
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["total_waiting"] == 11
    assert len(result["queues"]) == 2
    assert result["congestion_index"] > 0
    assert "measured_at" in result


# ─── 高峰事件处理 ───


@pytest.mark.asyncio
async def test_handle_peak_event_express_mode():
    """handle_peak_event: express_mode 应记录事件并开启快速出餐"""
    from services.peak_management import handle_peak_event

    session = _mock_session()
    session.execute.return_value = MagicMock()

    result = await handle_peak_event(
        store_id=STORE_ID,
        event_type="express_mode",
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["event_type"] == "express_mode"
    assert result["status"] == "active"
    assert result["action_result"]["express_mode"] is True
    assert "event_id" in result
    # set_config(1) + insert event(1) + update config(1) + flush
    assert session.execute.call_count >= 3
