"""试营业数据清除 API

端点：
  POST /api/v1/ops/trial-data/request   — 申请清除（创建审批申请）
  GET  /api/v1/ops/trial-data/status    — 查询申请状态
  POST /api/v1/ops/trial-data/execute   — 执行清除（审批通过后）
  GET  /api/v1/ops/trial-data/scope     — 查询清除范围说明

安全约束：
  - 只有 role=super_admin 可执行
  - 同一门店30天内只允许清除一次
  - 使用软删除（is_deleted=True + deleted_at），保证可追溯
  - confirm_store_name 必须与实际门店名一致
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/ops/trial-data", tags=["试营业数据清除"])


# ─── 请求 / 响应模型 ─────────────────────────────────────────────────────────

class ClearRequestBody(BaseModel):
    store_id: str = Field(..., description="目标门店ID")
    reason: str = Field(..., min_length=5, description="清除原因（不少于5字）")


class ExecuteBody(BaseModel):
    store_id: str = Field(..., description="目标门店ID")
    confirm_store_name: str = Field(..., description="输入门店名称以确认（必须与实际一致）")
    approved_request_id: str = Field(..., description="已审批通过的申请ID")


class StatusQuery(BaseModel):
    store_id: str


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

async def _verify_clear_permission(
    db: AsyncSession,
    tenant_id: str,
    operator_id: str,
) -> bool:
    """只有集团超级管理员可执行试营业数据清除。"""
    try:
        row = await db.execute(
            text(
                "SELECT role FROM employees "
                "WHERE tenant_id = :tid AND id = :oid AND is_deleted = FALSE LIMIT 1"
            ),
            {"tid": tenant_id, "oid": operator_id},
        )
        result = row.fetchone()
        if result is None:
            return False
        return result[0] == "super_admin"
    except Exception as exc:
        logger.warning("permission_check_db_error", exc=str(exc))
        # 降级：DB不可用时拒绝（安全默认值）
        return False


async def _check_cooldown(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> bool:
    """30天内只允许清除一次。返回 True 表示冷却期未满，应拒绝。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        row = await db.execute(
            text(
                "SELECT id FROM trial_data_clear_logs "
                "WHERE tenant_id = :tid AND store_id = :sid "
                "  AND executed_at >= :cutoff "
                "LIMIT 1"
            ),
            {"tid": tenant_id, "sid": store_id, "cutoff": cutoff},
        )
        return row.fetchone() is not None
    except Exception as exc:
        logger.warning("cooldown_check_db_error", exc=str(exc))
        # 降级：DB不可用时放行（不阻止申请流程）
        return False


async def _get_store_name(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> Optional[str]:
    """查询门店名称（用于 confirm_store_name 校验）。"""
    try:
        row = await db.execute(
            text(
                "SELECT name FROM stores "
                "WHERE tenant_id = :tid AND id = :sid AND is_deleted = FALSE LIMIT 1"
            ),
            {"tid": tenant_id, "sid": store_id},
        )
        result = row.fetchone()
        return result[0] if result else None
    except Exception as exc:
        logger.warning("get_store_name_db_error", exc=str(exc))
        return None


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.get("/scope")
async def get_clear_scope():
    """查询试营业数据清除范围说明（无需权限，供前端展示）。"""
    return {
        "ok": True,
        "data": {
            "will_clear": [
                "订单记录（orders / order_items）",
                "支付记录（payments）",
                "日清日结报告（daily_settlements / shift_reports）",
                "押金记录（biz_deposits）",
                "存酒记录（wine_storage_records）",
                "盘点记录（stocktake_records）",
            ],
            "will_keep": [
                "菜品档案（菜单/分类/BOM）",
                "员工档案（员工信息/角色/排班模板）",
                "桌位配置",
                "会员基础信息（手机号/姓名/会员等级）",
                "门店配置",
            ],
            "note": "所有清除均使用软删除（is_deleted=True），数据可审计追溯，不可在系统内直接恢复。",
        },
    }


@router.post("/request")
async def request_clear(
    body: ClearRequestBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
):
    """申请试营业数据清除（创建审批申请）。"""
    # 权限检查：只有超级管理员可提交申请
    if not await _verify_clear_permission(db, x_tenant_id, x_operator_id):
        raise HTTPException(status_code=403, detail="仅集团超级管理员可申请试营业数据清除")

    # 冷却期检查
    if await _check_cooldown(db, x_tenant_id, body.store_id):
        raise HTTPException(status_code=429, detail="该门店30天内已执行过清除，冷却期未满")

    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text(
                "INSERT INTO trial_data_clear_requests "
                "(id, tenant_id, store_id, operator_id, reason, status, created_at, updated_at, is_deleted) "
                "VALUES (:id, :tid, :sid, :oid, :reason, 'pending', :now, :now, FALSE)"
            ),
            {
                "id": request_id,
                "tid": x_tenant_id,
                "sid": body.store_id,
                "oid": x_operator_id,
                "reason": body.reason,
                "now": now,
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("trial_clear_request_db_error", exc=str(exc))
        raise HTTPException(status_code=500, detail="申请提交失败，请稍后重试") from exc

    logger.info(
        "trial_clear_requested",
        tenant_id=x_tenant_id,
        store_id=body.store_id,
        request_id=request_id,
        operator_id=x_operator_id,
    )
    return {
        "ok": True,
        "data": {
            "request_id": request_id,
            "status": "pending",
            "message": "申请已提交，等待集团审批",
        },
    }


@router.get("/status")
async def get_clear_status(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
):
    """查询最新一条清除申请状态。"""
    if not await _verify_clear_permission(db, x_tenant_id, x_operator_id):
        raise HTTPException(status_code=403, detail="仅集团超级管理员可查询")

    try:
        row = await db.execute(
            text(
                "SELECT id, status, reason, created_at, updated_at "
                "FROM trial_data_clear_requests "
                "WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = FALSE "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tid": x_tenant_id, "sid": store_id},
        )
        result = row.fetchone()
    except Exception as exc:
        logger.error("trial_clear_status_db_error", exc=str(exc))
        raise HTTPException(status_code=500, detail="查询失败") from exc

    if result is None:
        return {"ok": True, "data": None}

    return {
        "ok": True,
        "data": {
            "request_id": str(result[0]),
            "status": result[1],
            "reason": result[2],
            "created_at": result[3].isoformat() if result[3] else None,
            "updated_at": result[4].isoformat() if result[4] else None,
        },
    }


@router.post("/execute")
async def execute_clear(
    body: ExecuteBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
):
    """执行试营业数据清除（审批通过后）。

    安全校验：
    1. 操作者必须是 super_admin
    2. confirm_store_name 必须与实际门店名一致
    3. approved_request_id 必须处于 approved 状态
    4. 冷却期检查（30天内只允许一次）
    """
    # 1. 权限校验
    if not await _verify_clear_permission(db, x_tenant_id, x_operator_id):
        raise HTTPException(status_code=403, detail="仅集团超级管理员可执行")

    # 2. 门店名称校验
    actual_store_name = await _get_store_name(db, x_tenant_id, body.store_id)
    if actual_store_name is None:
        raise HTTPException(status_code=404, detail="门店不存在")
    if body.confirm_store_name.strip() != actual_store_name.strip():
        raise HTTPException(
            status_code=422,
            detail=f"门店名称不匹配（请输入：{actual_store_name}）",
        )

    # 3. 审批状态校验
    try:
        row = await db.execute(
            text(
                "SELECT status, store_id FROM trial_data_clear_requests "
                "WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE LIMIT 1"
            ),
            {"rid": body.approved_request_id, "tid": x_tenant_id},
        )
        req = row.fetchone()
    except Exception as exc:
        logger.error("trial_clear_approve_check_error", exc=str(exc))
        raise HTTPException(status_code=500, detail="审批状态查询失败") from exc

    if req is None:
        raise HTTPException(status_code=404, detail="申请记录不存在")
    if req[0] != "approved":
        raise HTTPException(
            status_code=422,
            detail=f"申请尚未审批通过（当前状态：{req[0]}）",
        )
    if req[1] != body.store_id:
        raise HTTPException(status_code=422, detail="申请与目标门店不一致")

    # 4. 冷却期检查
    if await _check_cooldown(db, x_tenant_id, body.store_id):
        raise HTTPException(status_code=429, detail="该门店30天内已执行过清除，冷却期未满")

    now = datetime.now(timezone.utc)
    sid = body.store_id
    tid = x_tenant_id

    # ── 执行软删除 ────────────────────────────────────────────────────────────
    # 所有清除均用 is_deleted=TRUE + deleted_at，保证可追溯
    tables_to_clear = [
        # (表名, where条件参数key)
        ("orders",               "store_id"),
        ("order_items",          "store_id"),
        ("payments",             "store_id"),
        ("daily_settlements",    "store_id"),
        ("shift_reports",        "store_id"),
        ("biz_deposits",         "store_id"),
        ("wine_storage_records", "store_id"),
        ("stocktake_records",    "store_id"),
    ]

    cleared: dict[str, int] = {}
    try:
        for table, col in tables_to_clear:
            result = await db.execute(
                text(
                    f"UPDATE {table} "
                    f"SET is_deleted = TRUE, deleted_at = :now "
                    f"WHERE tenant_id = :tid AND {col} = :sid "
                    f"  AND is_deleted = FALSE"
                ),
                {"now": now, "tid": tid, "sid": sid},
            )
            cleared[table] = result.rowcount  # type: ignore[attr-defined]

        # 写入清除日志
        log_id = str(uuid.uuid4())
        await db.execute(
            text(
                "INSERT INTO trial_data_clear_logs "
                "(id, tenant_id, store_id, operator_id, request_id, executed_at, cleared_summary, is_deleted) "
                "VALUES (:id, :tid, :sid, :oid, :rid, :now, :summary::jsonb, FALSE)"
            ),
            {
                "id": log_id,
                "tid": tid,
                "sid": sid,
                "oid": x_operator_id,
                "rid": body.approved_request_id,
                "now": now,
                "summary": str(cleared).replace("'", '"'),
            },
        )

        # 将申请标为已执行
        await db.execute(
            text(
                "UPDATE trial_data_clear_requests "
                "SET status = 'executed', updated_at = :now "
                "WHERE id = :rid AND tenant_id = :tid"
            ),
            {"rid": body.approved_request_id, "tid": tid, "now": now},
        )

        await db.commit()

    except Exception as exc:
        await db.rollback()
        logger.error(
            "trial_clear_execute_error",
            exc=str(exc),
            tenant_id=tid,
            store_id=sid,
        )
        raise HTTPException(status_code=500, detail="清除执行失败，已回滚") from exc

    logger.info(
        "trial_data_cleared",
        tenant_id=tid,
        store_id=sid,
        operator_id=x_operator_id,
        cleared=cleared,
    )

    # TODO: 发企微通知（接入 notification_routes 后补充）

    return {
        "ok": True,
        "data": {
            "message": "试营业数据清除完成",
            "store_id": sid,
            "executed_at": now.isoformat(),
            "cleared_summary": cleared,
        },
    }
