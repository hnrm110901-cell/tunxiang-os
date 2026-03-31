"""巡店管理模块测试

覆盖场景：
1. 创建巡检模板（含检查项列表）
2. 开始巡检（生成巡检记录）
3. 提交巡检结果（含评分和图片URL）
4. 创建整改任务（问题分 < 60分时自动触发）
5. 查询门店排名（按最近30天平均分）

所有测试为纯函数/单元测试，不依赖真实数据库。
使用 AsyncMock 模拟 AsyncSession。
"""

from __future__ import annotations

import os
import sys

# 将 tx-org/src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# 将仓库根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ── 测试夹具 ──────────────────────────────────────────────────────────────────


def make_db_mock() -> AsyncMock:
    """构建模拟 AsyncSession，execute 返回可配置的结果集。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


def make_scalar_result(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one.return_value = value
    return result


def make_rows_result(rows: list[dict]) -> MagicMock:
    """模拟 db.execute 返回多行 mapping 结果。"""
    result = MagicMock()
    mappings_mock = MagicMock()
    mappings_mock.first.return_value = rows[0] if rows else None
    mappings_mock.fetchall.return_value = rows
    result.mappings.return_value = mappings_mock
    return result


def make_returning_result(row: dict) -> MagicMock:
    """模拟 INSERT ... RETURNING 返回单行。"""
    result = MagicMock()
    mappings_mock = MagicMock()
    mappings_mock.first.return_value = row
    result.mappings.return_value = mappings_mock
    return result


TENANT_ID = str(uuid4())
BRAND_ID = str(uuid4())
STORE_ID = str(uuid4())
PATROLLER_ID = str(uuid4())
TEMPLATE_ID = str(uuid4())
RECORD_ID = str(uuid4())
ITEM_ID_1 = str(uuid4())
ITEM_ID_2 = str(uuid4())


# ── 场景 1: 创建巡检模板 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_template_success():
    """创建巡检模板，含多个检查项，返回模板ID。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    template_row = {
        "id": TEMPLATE_ID,
        "tenant_id": TENANT_ID,
        "brand_id": BRAND_ID,
        "name": "门店卫生巡检标准模板",
        "description": "覆盖食品安全、环境卫生、设备维护",
        "category": "hygiene",
        "is_active": True,
        "created_at": "2026-03-31T00:00:00Z",
        "updated_at": "2026-03-31T00:00:00Z",
    }

    items_data = [
        {
            "item_name": "地面清洁度",
            "item_type": "score",
            "max_score": 10.0,
            "is_required": True,
            "sort_order": 1,
        },
        {
            "item_name": "食材存储规范（拍照）",
            "item_type": "photo",
            "max_score": 10.0,
            "is_required": True,
            "sort_order": 2,
        },
    ]

    # execute 第一次（INSERT template），第二次（INSERT items batch）
    db.execute.side_effect = [
        make_returning_result(template_row),
        MagicMock(),  # items insert，无返回值需要
    ]

    result = await PatrolService.create_template(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        name="门店卫生巡检标准模板",
        description="覆盖食品安全、环境卫生、设备维护",
        category="hygiene",
        items=items_data,
        db=db,
    )

    assert result["id"] == TEMPLATE_ID
    assert result["name"] == "门店卫生巡检标准模板"
    assert result["category"] == "hygiene"
    assert db.commit.called


# ── 场景 2: 开始巡检 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_patrol_success():
    """给定模板和门店，创建巡检记录，状态为 in_progress。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    # 模板查询结果
    template_row = {
        "id": TEMPLATE_ID,
        "tenant_id": TENANT_ID,
        "name": "门店卫生巡检标准模板",
        "is_active": True,
    }
    # 模板检查项
    items_rows = [
        {
            "id": ITEM_ID_1,
            "template_id": TEMPLATE_ID,
            "item_name": "地面清洁度",
            "item_type": "score",
            "max_score": 10.0,
            "is_required": True,
            "sort_order": 1,
        },
        {
            "id": ITEM_ID_2,
            "template_id": TEMPLATE_ID,
            "item_name": "食材存储规范",
            "item_type": "photo",
            "max_score": 10.0,
            "is_required": True,
            "sort_order": 2,
        },
    ]
    # 新巡检记录
    record_row = {
        "id": RECORD_ID,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "template_id": TEMPLATE_ID,
        "patrol_date": "2026-03-31",
        "patroller_id": PATROLLER_ID,
        "status": "in_progress",
        "total_score": None,
        "created_at": "2026-03-31T08:00:00Z",
    }

    db.execute.side_effect = [
        make_rows_result([template_row]),   # 查询模板
        make_rows_result(items_rows),       # 查询检查项
        make_returning_result(record_row),  # INSERT record
        MagicMock(),                        # INSERT record_items batch
    ]

    result = await PatrolService.start_patrol(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        template_id=TEMPLATE_ID,
        patroller_id=PATROLLER_ID,
        db=db,
    )

    assert result["id"] == RECORD_ID
    assert result["status"] == "in_progress"
    assert result["store_id"] == STORE_ID
    assert db.commit.called


@pytest.mark.asyncio
async def test_start_patrol_template_not_found():
    """模板不存在时，抛出 ValueError。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()
    db.execute.return_value = make_rows_result([])  # 空结果

    with pytest.raises(ValueError, match="模板不存在"):
        await PatrolService.start_patrol(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            template_id=str(uuid4()),
            patroller_id=PATROLLER_ID,
            db=db,
        )


# ── 场景 3: 提交巡检结果 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_patrol_calculates_total_score():
    """提交巡检结果，服务自动计算百分制总分。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    record_row = {
        "id": RECORD_ID,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "template_id": TEMPLATE_ID,
        "status": "in_progress",
        "total_score": None,
    }
    # 模拟两个检查项，总满分 20，实际得 14 → 百分制 70
    item_results = [
        {
            "id": ITEM_ID_1,
            "record_id": RECORD_ID,
            "template_item_id": ITEM_ID_1,
            "item_name": "地面清洁度",
            "actual_score": None,
            "max_score": 10.0,
            "is_passed": None,
        },
        {
            "id": ITEM_ID_2,
            "record_id": RECORD_ID,
            "template_item_id": ITEM_ID_2,
            "item_name": "食材存储规范",
            "actual_score": None,
            "max_score": 10.0,
            "is_passed": None,
        },
    ]

    updated_record = {**record_row, "status": "submitted", "total_score": 70.0}

    db.execute.side_effect = [
        make_rows_result([record_row]),     # 查询 record
        make_rows_result(item_results),     # 查询 record_items
        MagicMock(),                        # UPDATE record_items（item 1）
        MagicMock(),                        # UPDATE record_items（item 2）
        MagicMock(),                        # UPDATE record status + total_score
        make_rows_result([updated_record]), # 查询更新后的 record（用于自动整改）
    ]

    submit_items = [
        {
            "template_item_id": ITEM_ID_1,
            "actual_score": 8.0,
            "photo_urls": [],
            "notes": "基本干净，角落有灰尘",
        },
        {
            "template_item_id": ITEM_ID_2,
            "actual_score": 6.0,
            "photo_urls": ["https://cdn.example.com/photo1.jpg"],
            "notes": "冷链温度略高",
        },
    ]

    result = await PatrolService.submit_patrol(
        tenant_id=TENANT_ID,
        record_id=RECORD_ID,
        items=submit_items,
        db=db,
    )

    # 8 + 6 = 14，满分 20，百分制 = 14/20*100 = 70
    assert result["total_score"] == pytest.approx(70.0)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_submit_patrol_wrong_status():
    """已提交的巡检记录不能重复提交。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    record_row = {
        "id": RECORD_ID,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "template_id": TEMPLATE_ID,
        "status": "submitted",  # 已提交
        "total_score": 85.0,
    }
    db.execute.return_value = make_rows_result([record_row])

    with pytest.raises(ValueError, match="只有 in_progress 状态的巡检才能提交"):
        await PatrolService.submit_patrol(
            tenant_id=TENANT_ID,
            record_id=RECORD_ID,
            items=[],
            db=db,
        )


# ── 场景 4: 自动整改触发（分数 < 60）─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_issue_on_low_score():
    """问题项评分低于满分60%时，自动创建整改任务。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    issue_row = {
        "id": str(uuid4()),
        "tenant_id": TENANT_ID,
        "record_id": RECORD_ID,
        "store_id": STORE_ID,
        "item_name": "食材存储规范",
        "severity": "major",
        "description": "冷链温度超标，存在食安风险",
        "photo_urls": ["https://cdn.example.com/photo1.jpg"],
        "status": "open",
        "assignee_id": None,
        "due_date": None,
        "created_at": "2026-03-31T08:00:00Z",
    }

    db.execute.side_effect = [
        make_returning_result(issue_row),  # INSERT issue
    ]

    result = await PatrolService.create_issue(
        tenant_id=TENANT_ID,
        record_id=RECORD_ID,
        store_id=STORE_ID,
        item_name="食材存储规范",
        severity="major",
        description="冷链温度超标，存在食安风险",
        photo_urls=["https://cdn.example.com/photo1.jpg"],
        db=db,
    )

    assert result["status"] == "open"
    assert result["severity"] == "major"
    assert result["item_name"] == "食材存储规范"
    assert db.commit.called


@pytest.mark.asyncio
async def test_create_critical_issue_triggers_approval():
    """severity=critical 时，自动创建紧急审批。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    issue_row = {
        "id": str(uuid4()),
        "tenant_id": TENANT_ID,
        "record_id": RECORD_ID,
        "store_id": STORE_ID,
        "item_name": "燃气泄漏检测",
        "severity": "critical",
        "description": "燃气泄漏，立即停业整改",
        "photo_urls": [],
        "status": "open",
        "assignee_id": None,
        "due_date": None,
        "created_at": "2026-03-31T08:00:00Z",
    }

    db.execute.side_effect = [
        make_returning_result(issue_row),  # INSERT issue
    ]

    # mock ApprovalEngine.create_instance
    with patch(
        "services.patrol_service.ApprovalEngine.create_instance",
        new=AsyncMock(return_value={"id": str(uuid4()), "status": "pending"}),
    ) as mock_approval:
        result = await PatrolService.create_issue(
            tenant_id=TENANT_ID,
            record_id=RECORD_ID,
            store_id=STORE_ID,
            item_name="燃气泄漏检测",
            severity="critical",
            description="燃气泄漏，立即停业整改",
            photo_urls=[],
            db=db,
        )

        # critical 级别应触发审批
        mock_approval.assert_called_once()
        call_kwargs = mock_approval.call_args.kwargs
        assert call_kwargs["business_type"] == "patrol_issue"
        assert call_kwargs["tenant_id"] == TENANT_ID

    assert result["severity"] == "critical"


@pytest.mark.asyncio
async def test_submit_patrol_auto_creates_issues_below_threshold():
    """提交结果后，得分低于满分60%的项目自动生成整改任务。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    record_row = {
        "id": RECORD_ID,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "template_id": TEMPLATE_ID,
        "status": "in_progress",
        "total_score": None,
    }
    item_results = [
        {
            "id": ITEM_ID_1,
            "record_id": RECORD_ID,
            "template_item_id": ITEM_ID_1,
            "item_name": "地面清洁度",
            "actual_score": None,
            "max_score": 10.0,
            "is_passed": None,
        },
        {
            "id": ITEM_ID_2,
            "record_id": RECORD_ID,
            "template_item_id": ITEM_ID_2,
            "item_name": "燃气安全检测",
            "actual_score": None,
            "max_score": 10.0,
            "is_passed": None,
        },
    ]
    updated_record = {**record_row, "status": "submitted", "total_score": 45.0}

    db.execute.side_effect = [
        make_rows_result([record_row]),
        make_rows_result(item_results),
        MagicMock(),  # UPDATE item 1
        MagicMock(),  # UPDATE item 2
        MagicMock(),  # UPDATE record
        make_rows_result([updated_record]),
    ]

    # 两个item：item1=8/10（80%，pass），item2=4/10（40%，需整改）
    submit_items = [
        {"template_item_id": ITEM_ID_1, "actual_score": 8.0, "photo_urls": [], "notes": ""},
        {"template_item_id": ITEM_ID_2, "actual_score": 4.0, "photo_urls": [], "notes": "安全隐患"},
    ]

    # mock create_issue 验证被调用
    with patch.object(PatrolService, "create_issue", new=AsyncMock(return_value={"id": str(uuid4())})) as mock_issue:
        await PatrolService.submit_patrol(
            tenant_id=TENANT_ID,
            record_id=RECORD_ID,
            items=submit_items,
            db=db,
        )
        # 只有 item2 分数低于60%阈值，应创建1个整改任务
        assert mock_issue.call_count == 1
        call_kwargs = mock_issue.call_args.kwargs
        assert call_kwargs["item_name"] == "燃气安全检测"


# ── 场景 5: 门店排名 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_store_patrol_ranking():
    """查询最近30天门店平均分排名，结果按分数降序。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    ranking_rows = [
        {"store_id": str(uuid4()), "avg_score": 92.5, "patrol_count": 8, "rank": 1},
        {"store_id": str(uuid4()), "avg_score": 85.0, "patrol_count": 6, "rank": 2},
        {"store_id": STORE_ID,     "avg_score": 70.0, "patrol_count": 4, "rank": 3},
    ]

    db.execute.return_value = make_rows_result(ranking_rows)

    result = await PatrolService.get_store_patrol_ranking(
        tenant_id=TENANT_ID,
        days=30,
        db=db,
    )

    assert len(result) == 3
    # 按分数降序
    assert result[0]["avg_score"] == pytest.approx(92.5)
    assert result[1]["avg_score"] == pytest.approx(85.0)
    assert result[2]["avg_score"] == pytest.approx(70.0)
    # 验证排名字段
    assert result[0]["rank"] == 1


@pytest.mark.asyncio
async def test_get_store_patrol_ranking_custom_days():
    """支持自定义时间窗口（如7天、90天）。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()
    db.execute.return_value = make_rows_result([])

    result = await PatrolService.get_store_patrol_ranking(
        tenant_id=TENANT_ID,
        days=7,
        db=db,
    )

    assert result == []
    # 验证查询参数中包含 days=7
    call_args = db.execute.call_args
    # 查询 SQL 应传入 days 参数
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args.args[1]
    assert params.get("days") == 7


# ── 场景 6: 整改任务状态更新 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_issue_status_to_resolved():
    """将整改任务状态更新为 resolved，记录解决时间和说明。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    issue_id = str(uuid4())
    resolved_row = {
        "id": issue_id,
        "tenant_id": TENANT_ID,
        "status": "resolved",
        "resolution_notes": "已更换制冷压缩机，温度恢复正常",
        "resolved_at": "2026-04-01T10:00:00Z",
    }

    db.execute.side_effect = [
        MagicMock(),                        # UPDATE
        make_rows_result([resolved_row]),   # SELECT 更新后
    ]

    result = await PatrolService.update_issue_status(
        tenant_id=TENANT_ID,
        issue_id=issue_id,
        new_status="resolved",
        resolution_notes="已更换制冷压缩机，温度恢复正常",
        db=db,
    )

    assert result["status"] == "resolved"
    assert result["resolution_notes"] == "已更换制冷压缩机，温度恢复正常"
    assert db.commit.called


@pytest.mark.asyncio
async def test_update_issue_invalid_status():
    """不允许的状态流转应抛出 ValueError。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    with pytest.raises(ValueError, match="不支持的整改状态"):
        await PatrolService.update_issue_status(
            tenant_id=TENANT_ID,
            issue_id=str(uuid4()),
            new_status="invalid_status",
            resolution_notes=None,
            db=db,
        )


# ── 场景 7: 业务规则 — 分类校验 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_template_invalid_category():
    """不合法的 category 值应被拒绝。"""
    from services.patrol_service import PatrolService

    db = make_db_mock()

    with pytest.raises(ValueError, match="不支持的检查类别"):
        await PatrolService.create_template(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            name="测试",
            description="",
            category="invalid_category",
            items=[],
            db=db,
        )
