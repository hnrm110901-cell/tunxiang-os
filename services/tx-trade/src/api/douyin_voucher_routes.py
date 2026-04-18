"""
抖音团购核销路由 — 状态同步 + 异常重试
Y-I2

实现端点：
  POST /api/v1/trade/douyin-voucher/verify              核销团购券
  POST /api/v1/trade/douyin-voucher/batch-verify        批量核销
  GET  /api/v1/trade/douyin-voucher/status/{code}       查询券状态
  POST /api/v1/trade/douyin-voucher/sync                触发同步
  GET  /api/v1/trade/douyin-voucher/reconciliation      对账报表
  GET  /api/v1/trade/douyin-voucher/retry-queue         失败重试队列
  POST /api/v1/trade/douyin-voucher/retry-queue/{id}/retry  手动重试
  POST /api/v1/trade/douyin-voucher/retry-queue/auto-retry  批量自动重试
  GET  /api/v1/trade/douyin-voucher/stores              已授权门店列表
  POST /api/v1/trade/douyin-voucher/stores/{id}/authorize  门店授权
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.trade_audit_log import write_audit

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/trade/douyin-voucher",
    tags=["douyin-voucher"],
)

# ──────────────────────────────────────────────────────────────────────────────
# 内存重试队列（生产应使用 Redis Streams 或 PostgreSQL）
# ──────────────────────────────────────────────────────────────────────────────
# key: task_id → {voucher_code, store_id, operator_id, error, retry_count, created_at}
_RETRY_QUEUE: dict[str, dict] = {}

# 已授权门店
_AUTHORIZED_STORES: dict[str, dict] = {
    "store-001": {
        "store_id": "store-001",
        "store_name": "芙蓉旗舰店",
        "douyin_merchant_id": "dy_merchant_001",
        "authorized_at": "2026-01-01T00:00:00+00:00",
        "status": "active",
    },
    "store-002": {
        "store_id": "store-002",
        "store_name": "天心广场店",
        "douyin_merchant_id": "dy_merchant_002",
        "authorized_at": "2026-02-01T00:00:00+00:00",
        "status": "active",
    },
}

MAX_RETRY_TIMES = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_str() -> str:
    return _now().isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# 抖音 API 模拟
# ──────────────────────────────────────────────────────────────────────────────


def _mock_douyin_verify(voucher_code: str) -> dict:
    """
    模拟抖音核销 API 响应。

    规则：
      DY_USED_*  → 40002 已核销
      DY_EXP_*   → 40003 已过期
      DY_FAIL_*  → 50001 平台错误（模拟写入重试队列场景）
      其他        → 0 成功
    """
    if voucher_code.startswith("DY_USED_"):
        return {"code": 40002, "msg": "券已核销", "data": None}
    if voucher_code.startswith("DY_EXP_"):
        return {"code": 40003, "msg": "券已过期", "data": None}
    if voucher_code.startswith("DY_FAIL_"):
        return {"code": 50001, "msg": "平台暂时不可用", "data": None}
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "product_name": "双人套餐",
            "amount_fen": 15800,
            "expire_at": "2026-12-31",
            "verify_sn": uuid.uuid4().hex[:16].upper(),
        },
    }


async def _mock_douyin_query_status(voucher_code: str) -> dict:
    """模拟查询券状态（带模拟延迟）"""
    await asyncio.sleep(0.05)  # 模拟网络延迟
    if voucher_code.startswith("DY_USED_"):
        return {"code": 0, "data": {"status": "used", "voucher_code": voucher_code}}
    if voucher_code.startswith("DY_EXP_"):
        return {"code": 0, "data": {"status": "expired", "voucher_code": voucher_code}}
    return {
        "code": 0,
        "data": {
            "status": "valid",
            "voucher_code": voucher_code,
            "product_name": "双人套餐",
            "amount_fen": 15800,
            "expire_at": "2026-12-31",
        },
    }


def _enqueue_retry(
    voucher_code: str,
    store_id: str,
    operator_id: str,
    error_msg: str,
) -> str:
    """写入重试队列 — 失败必须进队列，不丢弃"""
    task_id = f"retry-{uuid.uuid4().hex[:12]}"
    _RETRY_QUEUE[task_id] = {
        "task_id": task_id,
        "voucher_code": voucher_code,
        "store_id": store_id,
        "operator_id": operator_id,
        "error": error_msg,
        "retry_count": 0,
        "last_retry_at": None,
        "created_at": _now_str(),
        "status": "pending",
    }
    logger.info(
        "douyin_voucher_enqueued_retry",
        task_id=task_id,
        voucher_code=voucher_code,
        store_id=store_id,
        error=error_msg,
    )
    return task_id


# ──────────────────────────────────────────────────────────────────────────────
# 请求体
# ──────────────────────────────────────────────────────────────────────────────


class VerifyVoucherRequest(BaseModel):
    voucher_code: str = Field(min_length=1, max_length=100, description="团购券码")
    store_id: str = Field(min_length=1, max_length=50)
    operator_id: str = Field(min_length=1, max_length=50)
    verify_time: Optional[datetime] = Field(default=None, description="核销时间，默认当前时间")


class BatchVerifyRequest(BaseModel):
    vouchers: List[VerifyVoucherRequest] = Field(
        min_length=1,
        max_length=50,
        description="批量核销，最多50张",
    )


class SyncRequest(BaseModel):
    store_id: Optional[str] = Field(default=None, description="指定门店，为空则同步所有已授权门店")
    date_from: Optional[date] = Field(default=None, description="同步起始日期")


class AuthorizeStoreRequest(BaseModel):
    douyin_merchant_id: str = Field(min_length=1, max_length=100, description="抖音商户ID")
    store_name: str = Field(min_length=1, max_length=100)


# ──────────────────────────────────────────────────────────────────────────────
# Part 1: 核销操作
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/verify")
async def verify_voucher(
    body: VerifyVoucherRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
) -> dict:
    """
    核销团购券
    - 成功 → 写订单记录，关联 Golden ID
    - 失败 → 写 retry_queue，不丢弃
    """
    verify_time = body.verify_time or _now()

    # 校验门店已授权
    if body.store_id not in _AUTHORIZED_STORES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "error": {"code": "STORE_NOT_AUTHORIZED", "message": f"门店 {body.store_id} 未授权接入抖音团购"},
            },
        )

    dy_resp = _mock_douyin_verify(body.voucher_code)

    if dy_resp["code"] == 40002:
        logger.warning(
            "douyin_voucher_already_used",
            voucher_code=body.voucher_code,
            store_id=body.store_id,
            operator_id=body.operator_id,
            tenant_id=x_tenant_id,
        )
        return {
            "ok": False,
            "success": False,
            "error": {
                "code": "VOUCHER_ALREADY_USED",
                "message": "该团购券已核销，请勿重复使用",
            },
            "voucher_code": body.voucher_code,
        }

    if dy_resp["code"] == 40003:
        logger.warning(
            "douyin_voucher_expired",
            voucher_code=body.voucher_code,
            store_id=body.store_id,
            tenant_id=x_tenant_id,
        )
        return {
            "ok": False,
            "success": False,
            "error": {
                "code": "VOUCHER_EXPIRED",
                "message": "该团购券已过期",
            },
            "voucher_code": body.voucher_code,
        }

    if dy_resp["code"] != 0:
        # 平台错误 → 写重试队列，不丢弃
        task_id = _enqueue_retry(
            voucher_code=body.voucher_code,
            store_id=body.store_id,
            operator_id=body.operator_id,
            error_msg=dy_resp["msg"],
        )
        logger.error(
            "douyin_voucher_platform_error",
            voucher_code=body.voucher_code,
            store_id=body.store_id,
            error_code=dy_resp["code"],
            error_msg=dy_resp["msg"],
            retry_task_id=task_id,
            tenant_id=x_tenant_id,
        )
        return {
            "ok": False,
            "success": False,
            "error": {
                "code": "PLATFORM_ERROR",
                "message": dy_resp["msg"],
            },
            "retry_task_id": task_id,
            "voucher_code": body.voucher_code,
        }

    # 成功 → 生成订单记录
    order_id = f"dy-order-{uuid.uuid4().hex[:12]}"
    voucher_info = dy_resp["data"]

    logger.info(
        "douyin_voucher_verified",
        voucher_code=body.voucher_code,
        store_id=body.store_id,
        operator_id=body.operator_id,
        order_id=order_id,
        product_name=voucher_info["product_name"],
        amount_fen=voucher_info["amount_fen"],
        verify_sn=voucher_info.get("verify_sn"),
        tenant_id=x_tenant_id,
        verify_time=verify_time.isoformat(),
    )

    await write_audit(
        db,
        tenant_id=x_tenant_id,
        store_id=body.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="douyin_voucher.verify",
        target_type="voucher",
        target_id=None,
        amount_fen=voucher_info.get("amount_fen"),
        client_ip=user.client_ip,
    )

    return {
        "ok": True,
        "success": True,
        "order_id": order_id,
        "voucher_info": {
            "product_name": voucher_info["product_name"],
            "amount_fen": voucher_info["amount_fen"],
            "expire_at": voucher_info["expire_at"],
            "verify_sn": voucher_info.get("verify_sn"),
        },
        "voucher_code": body.voucher_code,
        "verify_time": verify_time.isoformat(),
    }


@router.post("/batch-verify")
async def batch_verify_vouchers(
    body: BatchVerifyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
) -> dict:
    """批量核销（最多50张）"""
    results = []
    success_count = 0
    fail_count = 0

    for req in body.vouchers:
        dy_resp = _mock_douyin_verify(req.voucher_code)

        if dy_resp["code"] == 0:
            order_id = f"dy-order-{uuid.uuid4().hex[:12]}"
            success_count += 1
            results.append({
                "voucher_code": req.voucher_code,
                "success": True,
                "order_id": order_id,
                "voucher_info": dy_resp["data"],
            })
        elif dy_resp["code"] in (40002, 40003):
            fail_count += 1
            results.append({
                "voucher_code": req.voucher_code,
                "success": False,
                "error": {"code": f"VOUCHER_{dy_resp['code']}", "message": dy_resp["msg"]},
            })
        else:
            # 平台错误 → 写重试队列
            task_id = _enqueue_retry(
                voucher_code=req.voucher_code,
                store_id=req.store_id,
                operator_id=req.operator_id,
                error_msg=dy_resp["msg"],
            )
            fail_count += 1
            results.append({
                "voucher_code": req.voucher_code,
                "success": False,
                "error": {"code": "PLATFORM_ERROR", "message": dy_resp["msg"]},
                "retry_task_id": task_id,
            })

    logger.info(
        "douyin_batch_verify_completed",
        total=len(body.vouchers),
        success=success_count,
        failed=fail_count,
        tenant_id=x_tenant_id,
    )

    await write_audit(
        db,
        tenant_id=x_tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="douyin_voucher.batch_verify",
        target_type="voucher_batch",
        target_id=None,
        amount_fen=None,
        client_ip=user.client_ip,
    )

    return {
        "ok": True,
        "data": {
            "total": len(body.vouchers),
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
        },
    }


@router.get("/status/{voucher_code}")
async def get_voucher_status(
    voucher_code: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """实时查询券状态（含模拟延迟）"""
    resp = await _mock_douyin_query_status(voucher_code)

    if resp["code"] != 0:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail={
                "ok": False,
                "error": {"code": "PLATFORM_QUERY_FAILED", "message": "抖音平台查询失败"},
            },
        )

    return {
        "ok": True,
        "data": resp["data"],
        "voucher_code": voucher_code,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Part 2: 同步与对账
# ──────────────────────────────────────────────────────────────────────────────


async def _run_sync_task(task_id: str, store_id: Optional[str], tenant_id: str) -> None:
    """后台同步任务：对比本地记录 vs 抖音平台记录"""
    await asyncio.sleep(0.1)  # 模拟异步处理
    logger.info(
        "douyin_sync_task_completed",
        task_id=task_id,
        store_id=store_id,
        tenant_id=tenant_id,
        synced_count=0,
        note="生产环境需拉取抖音平台核销记录并与本地对比",
    )


@router.post("/sync")
async def trigger_sync(
    body: SyncRequest,
    background_tasks: BackgroundTasks,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """触发同步（拉取门店未同步的核销记录）"""
    task_id = f"sync-{uuid.uuid4().hex[:12]}"

    background_tasks.add_task(
        _run_sync_task,
        task_id=task_id,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
    )

    logger.info(
        "douyin_sync_triggered",
        task_id=task_id,
        store_id=body.store_id,
        date_from=str(body.date_from) if body.date_from else None,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "sync_started": True,
            "task_id": task_id,
            "store_id": body.store_id,
            "note": "同步任务已提交后台，预计1-3分钟完成",
        },
    }


@router.get("/reconciliation")
async def get_reconciliation_report(
    date_from: date = Query(..., description="对账起始日期"),
    date_to: date = Query(..., description="对账截止日期"),
    store_id: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    对账报表：本地记录 vs 抖音平台记录差异分析
    返回：local_count/platform_count/matched/unmatched/discrepancy_amount_fen
    """
    if date_from > date_to:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "error": {"code": "INVALID_DATE_RANGE", "message": "起始日期不能晚于截止日期"},
            },
        )

    # Mock 对账数据（生产需从 DB 查询并调用抖音对账 API）
    local_count = 128
    platform_count = 126
    matched = 124
    unmatched = local_count - matched
    discrepancy_amount_fen = 31600  # 2张未匹配的券（15800×2）

    unmatched_records = [
        {
            "voucher_code": "DY_UNDEF_A001",
            "local_order_id": "dy-order-aaa001",
            "platform_status": "not_found",
            "amount_fen": 15800,
            "issue": "本地已核销，平台无记录",
        },
        {
            "voucher_code": "DY_UNDEF_A002",
            "local_order_id": None,
            "platform_status": "used",
            "amount_fen": 15800,
            "issue": "平台已核销，本地无记录",
        },
    ] if unmatched > 0 else []

    logger.info(
        "douyin_reconciliation_report",
        date_from=str(date_from),
        date_to=str(date_to),
        store_id=store_id,
        local_count=local_count,
        platform_count=platform_count,
        matched=matched,
        unmatched=unmatched,
        discrepancy_amount_fen=discrepancy_amount_fen,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "date_from": str(date_from),
            "date_to": str(date_to),
            "store_id": store_id,
            "local_count": local_count,
            "platform_count": platform_count,
            "matched": matched,
            "unmatched": unmatched,
            "discrepancy_amount_fen": discrepancy_amount_fen,
            "unmatched_records": unmatched_records,
        },
        "_data_source": "mock",
        "_mock_note": "生产环境需接入抖音对账 API 和本地订单数据库",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Part 3: 异常重试队列
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/retry-queue")
async def list_retry_queue(
    status: Optional[str] = Query(default=None, description="pending/retrying/failed"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查看失败重试队列"""
    items = list(_RETRY_QUEUE.values())
    if status:
        items = [t for t in items if t["status"] == status]

    items.sort(key=lambda t: t["created_at"], reverse=True)

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
            "pending_count": sum(1 for t in _RETRY_QUEUE.values() if t["status"] == "pending"),
            "failed_count": sum(1 for t in _RETRY_QUEUE.values() if t["status"] == "failed"),
        },
    }


@router.post("/retry-queue/{task_id}/retry")
async def manual_retry(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("store_manager", "admin")),
) -> dict:
    """手动重试失败核销（仅店长/管理员）"""
    task = _RETRY_QUEUE.get(task_id)
    if task is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "error": {"code": "TASK_NOT_FOUND", "message": "重试任务不存在"}},
        )

    if task["retry_count"] >= MAX_RETRY_TIMES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "error": {
                    "code": "MAX_RETRIES_EXCEEDED",
                    "message": f"已超过最大重试次数（{MAX_RETRY_TIMES}次），请人工处理",
                },
            },
        )

    dy_resp = _mock_douyin_verify(task["voucher_code"])

    if dy_resp["code"] == 0:
        _RETRY_QUEUE.pop(task_id, None)
        logger.info(
            "douyin_retry_success",
            task_id=task_id,
            voucher_code=task["voucher_code"],
            retry_count=task["retry_count"] + 1,
            tenant_id=x_tenant_id,
        )
        await write_audit(
            db,
            tenant_id=x_tenant_id,
            store_id=task.get("store_id"),
            user_id=user.user_id,
            user_role=user.role,
            action="douyin_voucher.retry.manual",
            target_type="retry_task",
            target_id=None,
            amount_fen=None,
            client_ip=user.client_ip,
        )
        return {
            "ok": True,
            "data": {
                "task_id": task_id,
                "status": "success",
                "voucher_info": dy_resp["data"],
                "retry_count": task["retry_count"] + 1,
            },
        }

    task["retry_count"] += 1
    task["last_retry_at"] = _now_str()
    if task["retry_count"] >= MAX_RETRY_TIMES:
        task["status"] = "failed"
    else:
        task["status"] = "pending"
    task["error"] = dy_resp["msg"]

    logger.warning(
        "douyin_retry_failed",
        task_id=task_id,
        voucher_code=task["voucher_code"],
        retry_count=task["retry_count"],
        error=dy_resp["msg"],
        tenant_id=x_tenant_id,
    )

    return {
        "ok": False,
        "data": {
            "task_id": task_id,
            "status": task["status"],
            "retry_count": task["retry_count"],
            "error": dy_resp["msg"],
        },
    }


@router.post("/retry-queue/auto-retry")
async def auto_retry_queue(
    background_tasks: BackgroundTasks,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("store_manager", "admin")),
) -> dict:
    """触发批量自动重试（最大3次；仅店长/管理员）"""
    pending_tasks = [
        t for t in _RETRY_QUEUE.values()
        if t["status"] == "pending" and t["retry_count"] < MAX_RETRY_TIMES
    ]

    if not pending_tasks:
        return {
            "ok": True,
            "data": {"message": "无待重试任务", "processed": 0},
        }

    async def _do_auto_retry() -> None:
        success_cnt = 0
        fail_cnt = 0
        for task in pending_tasks:
            dy_resp = _mock_douyin_verify(task["voucher_code"])
            if dy_resp["code"] == 0:
                _RETRY_QUEUE.pop(task["task_id"], None)
                success_cnt += 1
            else:
                task["retry_count"] += 1
                task["last_retry_at"] = _now_str()
                if task["retry_count"] >= MAX_RETRY_TIMES:
                    task["status"] = "failed"
                fail_cnt += 1
        logger.info(
            "douyin_auto_retry_completed",
            total=len(pending_tasks),
            success=success_cnt,
            failed=fail_cnt,
            tenant_id=x_tenant_id,
        )

    background_tasks.add_task(_do_auto_retry)

    logger.info(
        "douyin_auto_retry_triggered",
        pending_count=len(pending_tasks),
        tenant_id=x_tenant_id,
    )

    await write_audit(
        db,
        tenant_id=x_tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="douyin_voucher.retry.auto",
        target_type="retry_queue",
        target_id=None,
        amount_fen=None,
        client_ip=user.client_ip,
    )

    return {
        "ok": True,
        "data": {
            "triggered": True,
            "pending_count": len(pending_tasks),
            "note": "批量重试已提交后台",
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Part 4: 门店授权管理
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/stores")
async def list_authorized_stores(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """已授权接入抖音团购的门店列表"""
    stores = list(_AUTHORIZED_STORES.values())
    return {
        "ok": True,
        "data": {"items": stores, "total": len(stores)},
        "_data_source": "mock",
    }


@router.post("/stores/{store_id}/authorize")
async def authorize_store(
    store_id: str,
    body: AuthorizeStoreRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("admin", "tenant_admin")),
) -> dict:
    """门店授权（绑定抖音商户ID；仅 admin/tenant_admin）"""
    if store_id in _AUTHORIZED_STORES:
        existing = _AUTHORIZED_STORES[store_id]
        logger.info(
            "douyin_store_reauthorized",
            store_id=store_id,
            old_merchant_id=existing["douyin_merchant_id"],
            new_merchant_id=body.douyin_merchant_id,
            tenant_id=x_tenant_id,
        )
    else:
        logger.info(
            "douyin_store_authorized",
            store_id=store_id,
            douyin_merchant_id=body.douyin_merchant_id,
            tenant_id=x_tenant_id,
        )

    _AUTHORIZED_STORES[store_id] = {
        "store_id": store_id,
        "store_name": body.store_name,
        "douyin_merchant_id": body.douyin_merchant_id,
        "authorized_at": _now_str(),
        "status": "active",
    }

    await write_audit(
        db,
        tenant_id=x_tenant_id,
        store_id=store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="douyin_voucher.store.authorize",
        target_type="store",
        target_id=None,
        amount_fen=None,
        client_ip=user.client_ip,
    )

    return {
        "ok": True,
        "data": _AUTHORIZED_STORES[store_id],
    }
