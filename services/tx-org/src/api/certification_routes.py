"""
岗位认证与通关路由 — DB持久化版
OR-xx: position_certifications 表
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/certifications", tags=["certifications"])

# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ── 默认考核项模板 ────────────────────────────────────────────────────────────

EXAM_TEMPLATES: dict[str, list[dict]] = {
    "chef": [
        {"item": "食品安全知识", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "菜品出品标准", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "成本控制意识", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "实操出品考核（3道招牌菜）", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "卫生与设备操作", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
    ],
    "waiter": [
        {"item": "服务礼仪与话术", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "菜品知识考核", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "点单系统操作", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "客诉处理模拟", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "酒水饮品知识", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
    ],
    "manager": [
        {"item": "门店经营指标分析", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "团队管理与排班", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "成本与毛利管控", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "食品安全与合规", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "客户服务与危机处理", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "营销活动策划", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
    ],
    "cashier": [
        {"item": "收银系统操作", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "支付方式与对账流程", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "发票开具与税务基础", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "假币识别与现金管理", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
    ],
    "cleaner": [
        {"item": "清洁标准与流程", "type": "theory", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "消毒剂使用规范", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
        {"item": "垃圾分类与处理", "type": "practice", "score": None, "passed": False, "examiner_id": None, "exam_date": None},
    ],
}

VALID_POSITIONS = set(EXAM_TEMPLATES.keys())

# ── Pydantic 模型 ─────────────────────────────────────────────────────────────


class CertificationCreate(BaseModel):
    employee_id: str
    store_id: str
    position: str
    notes: Optional[str] = None
    certifier_id: Optional[str] = None


class CertificationUpdate(BaseModel):
    notes: Optional[str] = None
    expires_at: Optional[str] = None


class ExamItemScore(BaseModel):
    score: float = Field(..., ge=0, le=100)
    passed: bool
    examiner_id: str
    exam_date: Optional[str] = None  # ISO date, defaults to now


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_certifications(
    request: Request,
    store_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    position: Optional[str] = Query(None),
    passed: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """认证记录列表（分页+筛选）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = false"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if employee_id:
        conditions.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    if position:
        conditions.append("position = :position")
        params["position"] = position
    if passed is not None:
        conditions.append("passed = :passed")
        params["passed"] = passed

    where = " AND ".join(conditions)

    count_sql = f"SELECT count(*) FROM position_certifications WHERE {where}"
    row = await db.execute(text(count_sql), params)
    total = row.scalar() or 0

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    data_sql = f"""
        SELECT id, tenant_id, employee_id, store_id, position,
               exam_items, total_score, passed, certified_at, expires_at,
               certifier_id, retake_count, notes, created_at, updated_at
        FROM position_certifications
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = await db.execute(text(data_sql), params)
    items = [dict(r._mapping) for r in rows]
    for item in items:
        if isinstance(item.get("exam_items"), str):
            item["exam_items"] = json.loads(item["exam_items"])

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("")
async def create_certification(
    request: Request,
    body: CertificationCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建认证记录（根据岗位自动填充考核项）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if body.position not in VALID_POSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid position '{body.position}', must be one of: {', '.join(sorted(VALID_POSITIONS))}",
        )

    cert_id = str(uuid4())
    exam_items = json.dumps(EXAM_TEMPLATES[body.position], ensure_ascii=False)
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO position_certifications
            (id, tenant_id, employee_id, store_id, position,
             exam_items, total_score, passed, certified_at, expires_at,
             certifier_id, retake_count, notes, is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :employee_id, :store_id, :position,
             :exam_items::jsonb, NULL, false, NULL, NULL,
             :certifier_id, 0, :notes, false, :now, :now)
        RETURNING id, tenant_id, employee_id, store_id, position,
                  exam_items, total_score, passed, certified_at, expires_at,
                  certifier_id, retake_count, notes, created_at, updated_at
    """)
    row = await db.execute(sql, {
        "id": cert_id,
        "tid": tenant_id,
        "employee_id": body.employee_id,
        "store_id": body.store_id,
        "position": body.position,
        "exam_items": exam_items,
        "certifier_id": body.certifier_id,
        "notes": body.notes,
        "now": now,
    })
    await db.commit()
    result = dict(row.fetchone()._mapping)
    if isinstance(result.get("exam_items"), str):
        result["exam_items"] = json.loads(result["exam_items"])

    log.info("certification.created", cert_id=cert_id, position=body.position, employee_id=body.employee_id)
    return _ok(result)


@router.get("/dashboard")
async def certification_dashboard(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """认证总览看板"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {"tid": tenant_id}
    if store_id:
        params["store_id"] = store_id

    now = datetime.now(timezone.utc)
    params["now"] = now
    params["now_plus_30"] = now + timedelta(days=30)

    sql = text(f"""
        SELECT
            count(*) AS total,
            count(*) FILTER (WHERE passed = true) AS passed_count,
            count(*) FILTER (WHERE passed = false AND total_score IS NOT NULL) AS failed_count,
            count(*) FILTER (WHERE passed = true AND expires_at BETWEEN :now AND :now_plus_30) AS expiring_soon,
            ROUND(AVG(total_score)::numeric, 2) AS avg_score,
            ROUND(AVG(retake_count)::numeric, 2) AS avg_retake
        FROM position_certifications
        WHERE tenant_id = :tid AND is_deleted = false {store_filter}
    """)
    row = await db.execute(sql, params)
    summary = dict(row.fetchone()._mapping)

    # 按岗位分布
    sql2 = text(f"""
        SELECT position,
               count(*) AS total,
               count(*) FILTER (WHERE passed = true) AS passed_count,
               ROUND(AVG(total_score)::numeric, 2) AS avg_score
        FROM position_certifications
        WHERE tenant_id = :tid AND is_deleted = false {store_filter}
        GROUP BY position ORDER BY position
    """)
    rows2 = await db.execute(sql2, params)
    by_position = [dict(r._mapping) for r in rows2]

    # 补考统计
    sql3 = text(f"""
        SELECT
            count(*) FILTER (WHERE retake_count >= 1) AS retake_once,
            count(*) FILTER (WHERE retake_count >= 2) AS retake_twice_plus,
            MAX(retake_count) AS max_retake
        FROM position_certifications
        WHERE tenant_id = :tid AND is_deleted = false {store_filter}
    """)
    row3 = await db.execute(sql3, params)
    retake_stats = dict(row3.fetchone()._mapping)

    return _ok({
        "summary": summary,
        "by_position": by_position,
        "retake_stats": retake_stats,
    })


@router.get("/expiring")
async def expiring_certifications(
    request: Request,
    store_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """即将过期认证（默认30天内到期）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND store_id = :store_id" if store_id else ""
    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "tid": tenant_id,
        "now": now,
        "deadline": now + timedelta(days=days),
    }
    if store_id:
        params["store_id"] = store_id

    sql = text(f"""
        SELECT id, employee_id, store_id, position, total_score,
               certified_at, expires_at, retake_count
        FROM position_certifications
        WHERE tenant_id = :tid AND is_deleted = false
          AND passed = true
          AND expires_at BETWEEN :now AND :deadline
          {store_filter}
        ORDER BY expires_at ASC
    """)
    rows = await db.execute(sql, params)
    items = [dict(r._mapping) for r in rows]

    return _ok({"items": items, "total": len(items)})


@router.get("/{cert_id}")
async def get_certification(
    cert_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """认证详情（含考核项展开）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT id, tenant_id, employee_id, store_id, position,
               exam_items, total_score, passed, certified_at, expires_at,
               certifier_id, retake_count, notes, created_at, updated_at
        FROM position_certifications
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
    """)
    row = await db.execute(sql, {"id": cert_id, "tid": tenant_id})
    record = row.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Certification not found")

    result = dict(record._mapping)
    if isinstance(result.get("exam_items"), str):
        result["exam_items"] = json.loads(result["exam_items"])

    return _ok(result)


@router.put("/{cert_id}")
async def update_certification(
    cert_id: str,
    request: Request,
    body: CertificationUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新认证（notes/expires_at）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sets: list[str] = ["updated_at = :now"]
    params: dict[str, Any] = {"id": cert_id, "tid": tenant_id, "now": datetime.now(timezone.utc)}

    if body.notes is not None:
        sets.append("notes = :notes")
        params["notes"] = body.notes
    if body.expires_at is not None:
        sets.append("expires_at = :expires_at")
        params["expires_at"] = body.expires_at

    if len(sets) == 1:
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = text(f"""
        UPDATE position_certifications
        SET {', '.join(sets)}
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        RETURNING id, notes, expires_at, updated_at
    """)
    row = await db.execute(sql, params)
    updated = row.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail="Certification not found")

    await db.commit()
    return _ok(dict(updated._mapping))


@router.put("/{cert_id}/exam/{item_idx}")
async def submit_exam_item(
    cert_id: str,
    item_idx: int,
    request: Request,
    body: ExamItemScore,
    db: AsyncSession = Depends(get_db),
):
    """提交单项考核成绩"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 先取出当前 exam_items 以校验索引
    fetch_sql = text("""
        SELECT exam_items FROM position_certifications
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
    """)
    row = await db.execute(fetch_sql, {"id": cert_id, "tid": tenant_id})
    record = row.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Certification not found")

    exam_items = record.exam_items if isinstance(record.exam_items, list) else json.loads(record.exam_items)
    if item_idx < 0 or item_idx >= len(exam_items):
        raise HTTPException(status_code=400, detail=f"Invalid item_idx {item_idx}, must be 0-{len(exam_items)-1}")

    exam_date = body.exam_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 使用 jsonb_set 逐字段更新
    sql = text("""
        UPDATE position_certifications
        SET exam_items = jsonb_set(
                jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            exam_items,
                            :path_score, :score::jsonb
                        ),
                        :path_passed, :passed::jsonb
                    ),
                    :path_examiner, :examiner::jsonb
                ),
                :path_date, :exam_date::jsonb
            ),
            updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        RETURNING exam_items
    """)
    idx_str = str(item_idx)
    result = await db.execute(sql, {
        "id": cert_id,
        "tid": tenant_id,
        "now": datetime.now(timezone.utc),
        "path_score": f"{{{idx_str},score}}",
        "path_passed": f"{{{idx_str},passed}}",
        "path_examiner": f"{{{idx_str},examiner_id}}",
        "path_date": f"{{{idx_str},exam_date}}",
        "score": json.dumps(body.score),
        "passed": json.dumps(body.passed),
        "examiner": json.dumps(body.examiner_id),
        "exam_date": json.dumps(exam_date),
    })
    updated = result.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail="Certification not found")

    await db.commit()
    items = updated.exam_items if isinstance(updated.exam_items, list) else json.loads(updated.exam_items)

    log.info("certification.exam_item_scored", cert_id=cert_id, item_idx=item_idx, score=body.score)
    return _ok({"exam_items": items})


@router.put("/{cert_id}/finalize")
async def finalize_certification(
    cert_id: str,
    request: Request,
    certifier_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """完成认证评定（汇总分数，判定通过/不通过）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    fetch_sql = text("""
        SELECT exam_items, retake_count FROM position_certifications
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
    """)
    row = await db.execute(fetch_sql, {"id": cert_id, "tid": tenant_id})
    record = row.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Certification not found")

    exam_items = record.exam_items if isinstance(record.exam_items, list) else json.loads(record.exam_items)

    # 校验所有考核项都已打分
    for i, item in enumerate(exam_items):
        if item.get("score") is None:
            raise HTTPException(
                status_code=400,
                detail=f"Exam item [{i}] '{item['item']}' has not been scored yet",
            )

    scores = [item["score"] for item in exam_items]
    total_score = round(sum(scores) / len(scores), 2)
    all_passed = all(item.get("passed", False) for item in exam_items)
    passed = all_passed and total_score >= 60

    now = datetime.now(timezone.utc)
    sets = [
        "total_score = :total_score",
        "passed = :passed",
        "updated_at = :now",
    ]
    params: dict[str, Any] = {
        "id": cert_id,
        "tid": tenant_id,
        "total_score": total_score,
        "passed": passed,
        "now": now,
    }

    if passed:
        sets.append("certified_at = :certified_at")
        sets.append("expires_at = :expires_at")
        params["certified_at"] = now
        params["expires_at"] = now + timedelta(days=365)

    if certifier_id:
        sets.append("certifier_id = :certifier_id")
        params["certifier_id"] = certifier_id

    sql = text(f"""
        UPDATE position_certifications
        SET {', '.join(sets)}
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        RETURNING id, total_score, passed, certified_at, expires_at, certifier_id, updated_at
    """)
    result = await db.execute(sql, params)
    updated = result.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail="Certification not found")

    await db.commit()
    log.info("certification.finalized", cert_id=cert_id, passed=passed, total_score=total_score)
    return _ok(dict(updated._mapping))


@router.put("/{cert_id}/retake")
async def retake_certification(
    cert_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """发起补考（retake_count += 1，重置所有考核项分数）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 先取出当前 exam_items
    fetch_sql = text("""
        SELECT exam_items FROM position_certifications
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
    """)
    row = await db.execute(fetch_sql, {"id": cert_id, "tid": tenant_id})
    record = row.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Certification not found")

    exam_items = record.exam_items if isinstance(record.exam_items, list) else json.loads(record.exam_items)

    # 重置所有考核项
    for item in exam_items:
        item["score"] = None
        item["passed"] = False
        item["examiner_id"] = None
        item["exam_date"] = None

    sql = text("""
        UPDATE position_certifications
        SET retake_count = retake_count + 1,
            exam_items = :exam_items::jsonb,
            total_score = NULL,
            passed = false,
            certified_at = NULL,
            expires_at = NULL,
            updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        RETURNING id, retake_count, exam_items, updated_at
    """)
    result = await db.execute(sql, {
        "id": cert_id,
        "tid": tenant_id,
        "exam_items": json.dumps(exam_items, ensure_ascii=False),
        "now": datetime.now(timezone.utc),
    })
    updated = result.fetchone()
    if not updated:
        raise HTTPException(status_code=404, detail="Certification not found")

    await db.commit()
    res = dict(updated._mapping)
    if isinstance(res.get("exam_items"), str):
        res["exam_items"] = json.loads(res["exam_items"])

    log.info("certification.retake", cert_id=cert_id, retake_count=res["retake_count"])
    return _ok(res)


@router.delete("/{cert_id}")
async def delete_certification(
    cert_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除认证记录"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        UPDATE position_certifications
        SET is_deleted = true, updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        RETURNING id
    """)
    row = await db.execute(sql, {"id": cert_id, "tid": tenant_id, "now": datetime.now(timezone.utc)})
    deleted = row.fetchone()
    if not deleted:
        raise HTTPException(status_code=404, detail="Certification not found")

    await db.commit()
    log.info("certification.deleted", cert_id=cert_id)
    return _ok({"id": cert_id, "deleted": True})
