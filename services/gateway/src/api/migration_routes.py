"""
天财商龙迁移 API

为天财商龙切换客户提供完整的数据迁移流程管理：

  POST /api/v1/migration/tiancai/start      — 启动迁移（含配置映射+菜品+会员）
  GET  /api/v1/migration/tiancai/status     — 查询迁移进度
  GET  /api/v1/migration/tiancai/prefilled  — 仅获取配置映射（不写数据库）
  GET  /api/v1/migration/pending-members    — 列出待审核的储值会员
  POST /api/v1/migration/pending-members/{id}/approve  — 审核通过，执行储值迁移
  POST /api/v1/migration/pending-members/{id}/reject   — 审核拒绝
  GET  /api/v1/migration/pending-members/summary — 待审核储值汇总（财务签字用）

30天迁移时间线：
  Week 1: POST /start (dry_run=True) 评估迁移量
  Week 1: POST /start (dry_run=False) 正式迁移菜品+零余额会员
  Week 2: 双轨运行期，每日拉取天财账单到 events（只读归档）
  Week 3: 财务逐一 approve pending-members（储值安全迁移）
  Week 4: 配置健康度达到 ≥90 后，切换商米POS到屯象收银
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from ..response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/migration", tags=["migration"])


# ── 请求/响应模型 ─────────────────────────────────────────────────────


class TiancaiMigrationStartRequest(BaseModel):
    tenant_id: str
    brand_id: str
    # 天财适配器配置（生产环境从 tenant_agent_configs 读取，此处允许覆写）
    tiancai_config: Optional[dict[str, Any]] = None
    dry_run: bool = False


class PendingMemberAction(BaseModel):
    review_notes: Optional[str] = None
    reviewed_by: str  # 操作员工号，用于审计留痕


# ── 路由 ──────────────────────────────────────────────────────────────


@router.post("/tiancai/start")
async def start_tiancai_migration(req: TiancaiMigrationStartRequest) -> dict:
    """
    启动天财商龙→屯象OS完整迁移流程。

    执行顺序（均为异步，失败不互相阻塞）：
      1. 配置映射 → 返回 prefilled_answers（供后续 onboarding 会话使用）
      2. 菜品迁移 → UPSERT dishes（成功率 ≥99.5% 为合格）
      3. 会员迁移 → 零余额自动迁移，有余额写 pending_review

    dry_run=True 时只拉取数据不写库，用于迁移前评估。
    """
    adapter = _build_adapter(req.tenant_id, req.tiancai_config)

    # 异步执行完整迁移（配置+菜品+会员）
    # 此处同步等待；生产环境可改为 background task + 进度查询
    from ..migration.tiancai_config_mapper import run_tiancai_migration

    summary = await run_tiancai_migration(
        adapter=adapter,
        tenant_id=req.tenant_id,
        brand_id=req.brand_id,
        dry_run=req.dry_run,
    )

    logger.info(
        "tiancai_migration_started",
        tenant_id=req.tenant_id,
        dry_run=req.dry_run,
        menu_fetched=summary.get("steps", {}).get("menu_migration", {}).get("total_fetched"),
        member_fetched=summary.get("steps", {}).get("member_migration", {}).get("total_fetched"),
    )

    return ok({
        "migration_summary": summary,
        "next_steps": _build_next_steps(summary, req.dry_run),
    })


@router.get("/tiancai/prefilled")
async def get_tiancai_prefilled(
    tenant_id: str = Query(..., description="租户 UUID"),
    tiancai_appid: Optional[str] = Query(None),
    tiancai_accessid: Optional[str] = Query(None),
    tiancai_center_id: Optional[str] = Query(None),
    tiancai_shop_id: Optional[str] = Query(None),
) -> dict:
    """
    仅执行配置映射，返回 prefilled_answers（不写数据库）。
    用于 onboarding 会话启动前的预览，让商户确认映射结果是否正确。
    """
    from ..migration.tiancai_config_mapper import TiancaiConfigMapper

    config = {}
    if tiancai_appid:
        config["appid"] = tiancai_appid
    if tiancai_accessid:
        config["accessid"] = tiancai_accessid
    if tiancai_center_id:
        config["center_id"] = tiancai_center_id
    if tiancai_shop_id:
        config["shop_id"] = tiancai_shop_id

    adapter = _build_adapter(tenant_id, config or None)
    mapper = TiancaiConfigMapper(adapter)
    prefilled = await mapper.extract_prefilled_answers()

    return ok({
        "tenant_id": tenant_id,
        "prefilled_answers": prefilled,
        "prefilled_count": len(prefilled),
        "remaining_questions": max(0, 20 - len(prefilled)),
        "note": "将 prefilled_answers 传入 POST /api/v1/onboarding/start 可跳过已知配置",
    })


@router.get("/pending-members/summary")
async def get_pending_members_summary(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    待审核储值会员汇总（财务签字确认用）。

    返回：总人数、总储值金额（元）、按金额段分布。
    此接口结果需财务负责人签字后才能执行 approve。
    """
    tenant_id = x_tenant_id
    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as db:
            await db.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})

            result = await db.execute(text("""
                SELECT
                    COUNT(*)                          AS total_count,
                    COALESCE(SUM(stored_value_fen), 0) AS total_balance_fen,
                    COUNT(*) FILTER (WHERE stored_value_fen BETWEEN 1 AND 10000)     AS tier_0_100,
                    COUNT(*) FILTER (WHERE stored_value_fen BETWEEN 10001 AND 100000) AS tier_100_1000,
                    COUNT(*) FILTER (WHERE stored_value_fen > 100000)                AS tier_1000_plus
                FROM member_migration_pending
                WHERE tenant_id = :tid
                  AND status = 'pending_review'
                  AND is_deleted = FALSE
            """), {"tid": tenant_id})

            row = result.fetchone()
            total_count = int(row[0] or 0)
            total_balance_fen = int(row[1] or 0)

            return ok({
                "tenant_id": tenant_id,
                "pending_count": total_count,
                "total_balance_yuan": round(total_balance_fen / 100, 2),
                "distribution": {
                    "0_100_yuan": int(row[2] or 0),
                    "100_1000_yuan": int(row[3] or 0),
                    "1000_plus_yuan": int(row[4] or 0),
                },
                "warning": (
                    "以上储值余额需财务负责人逐一核实后批准迁移。"
                    "请对照天财系统的储值余额台账确认无误后再执行 approve。"
                ),
            })

    except Exception as exc:
        logger.error("pending_members_summary_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/pending-members")
async def list_pending_members(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    status: str = Query("pending_review"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    order_by: str = Query("balance_desc", description="balance_desc | balance_asc | name"),
) -> dict:
    """列出待审核（或已处理）的储值迁移会员。"""
    tenant_id = x_tenant_id
    offset = (page - 1) * size

    order_sql = {
        "balance_desc": "stored_value_fen DESC",
        "balance_asc": "stored_value_fen ASC",
        "name": "display_name ASC",
    }.get(order_by, "stored_value_fen DESC")

    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as db:
            await db.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})

            rows = await db.execute(text(f"""
                SELECT id, phone, display_name, external_id_tiancai,
                       stored_value_fen, points, tier_name, status,
                       reviewed_by, reviewed_at, review_notes, created_at
                FROM member_migration_pending
                WHERE tenant_id = :tid
                  AND status = :status
                  AND is_deleted = FALSE
                ORDER BY {order_sql}
                LIMIT :size OFFSET :offset
            """), {"tid": tenant_id, "status": status, "size": size, "offset": offset})

            total_row = await db.execute(text("""
                SELECT COUNT(*) FROM member_migration_pending
                WHERE tenant_id = :tid AND status = :status AND is_deleted = FALSE
            """), {"tid": tenant_id, "status": status})
            total = int(total_row.scalar() or 0)

            items = [
                {
                    "id": r[0],
                    "phone": r[1],
                    "display_name": r[2],
                    "tiancai_card_no": r[3],
                    "stored_value_yuan": round(int(r[4] or 0) / 100, 2),
                    "points": r[5],
                    "tier_name": r[6],
                    "status": r[7],
                    "reviewed_by": r[8],
                    "reviewed_at": r[9].isoformat() if r[9] else None,
                    "review_notes": r[10],
                    "created_at": r[11].isoformat() if r[11] else None,
                }
                for r in rows.fetchall()
            ]

            return ok({
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            })

    except Exception as exc:
        logger.error("list_pending_members_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pending-members/{record_id}/approve")
async def approve_pending_member(
    record_id: int,
    action: PendingMemberAction,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    审核通过：将 pending 会员的储值余额正式迁移到 customers 表。

    ⚠️  资金安全：此操作不可逆。执行前必须确认：
      1. 天财系统中该会员储值已被冻结
      2. 双方余额已人工对账一致
    """
    from datetime import datetime, timezone

    tenant_id = x_tenant_id
    now = datetime.now(tz=timezone.utc)

    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as db:
            await db.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})

            # 读取 pending 记录
            row = await db.execute(text("""
                SELECT id, phone, display_name, stored_value_fen, points, status
                FROM member_migration_pending
                WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
            """), {"rid": record_id, "tid": tenant_id})
            record = row.fetchone()

            if not record:
                raise HTTPException(status_code=404, detail="迁移记录不存在")
            if record[5] != "pending_review":
                raise HTTPException(
                    status_code=409,
                    detail=f"记录状态为 {record[5]}，只有 pending_review 状态可审核",
                )

            phone = record[1]
            stored_value_fen = int(record[3] or 0)
            points = int(record[4] or 0)

            # 将储值余额写入 customers 表（仅更新储值字段）
            await db.execute(text("""
                UPDATE customers
                SET stored_value_fen = stored_value_fen + :balance,
                    points           = points + :pts,
                    updated_at       = NOW()
                WHERE tenant_id = :tid AND phone = :phone AND is_deleted = FALSE
            """), {
                "tid": tenant_id,
                "phone": phone,
                "balance": stored_value_fen,
                "pts": points,
            })

            # 更新 pending 状态
            await db.execute(text("""
                UPDATE member_migration_pending
                SET status       = 'migrated',
                    reviewed_by  = :reviewer,
                    reviewed_at  = :now,
                    review_notes = :notes,
                    migrated_at  = :now,
                    updated_at   = :now
                WHERE id = :rid AND tenant_id = :tid
            """), {
                "rid": record_id,
                "tid": tenant_id,
                "reviewer": action.reviewed_by,
                "now": now,
                "notes": action.review_notes or "审核通过",
            })

            await db.commit()

        logger.info(
            "pending_member_approved",
            tenant_id=tenant_id,
            record_id=record_id,
            phone=phone,
            stored_value_fen=stored_value_fen,
            reviewed_by=action.reviewed_by,
        )

        return ok({
            "record_id": record_id,
            "phone": phone,
            "migrated_balance_yuan": round(stored_value_fen / 100, 2),
            "status": "migrated",
            "message": f"储值 ¥{stored_value_fen/100:.2f} 已迁移到会员账户",
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("approve_pending_member_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pending-members/{record_id}/reject")
async def reject_pending_member(
    record_id: int,
    action: PendingMemberAction,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    审核拒绝：记录拒绝原因，储值余额不迁移（保留在天财系统中）。
    """
    from datetime import datetime, timezone

    tenant_id = x_tenant_id
    now = datetime.now(tz=timezone.utc)

    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as db:
            await db.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})

            result = await db.execute(text("""
                UPDATE member_migration_pending
                SET status       = 'rejected',
                    reviewed_by  = :reviewer,
                    reviewed_at  = :now,
                    review_notes = :notes,
                    updated_at   = :now
                WHERE id = :rid AND tenant_id = :tid
                  AND status = 'pending_review'
                  AND is_deleted = FALSE
                RETURNING id, phone
            """), {
                "rid": record_id,
                "tid": tenant_id,
                "reviewer": action.reviewed_by,
                "now": now,
                "notes": action.review_notes or "审核拒绝",
            })
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="记录不存在或状态不符")
            await db.commit()

        return ok({
            "record_id": record_id,
            "phone": row[1],
            "status": "rejected",
            "message": "已拒绝迁移，该会员储值保留在天财系统中",
        })

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── 内部辅助 ──────────────────────────────────────────────────────────


def _build_adapter(tenant_id: str, config: Optional[dict] = None):
    """
    构建天财商龙适配器实例。
    生产环境从 tenant_agent_configs 或环境变量中读取凭证；
    config 参数可覆写（用于多商户切换场景）。
    """
    import importlib
    import os

    _mod = importlib.import_module("shared.adapters.tiancai-shanglong.src.adapter")
    TiancaiShanglongAdapter = _mod.TiancaiShanglongAdapter

    final_config = {
        "appid": os.getenv("TIANCAI_APPID", ""),
        "accessid": os.getenv("TIANCAI_ACCESSID", ""),
        "center_id": os.getenv("TIANCAI_CENTER_ID", ""),
        "shop_id": os.getenv("TIANCAI_SHOP_ID", ""),
    }
    if config:
        final_config.update({k: v for k, v in config.items() if v})

    return TiancaiShanglongAdapter(final_config)


def _build_next_steps(summary: dict, dry_run: bool) -> list[str]:
    """根据迁移摘要生成下一步指引。"""
    steps = []
    if dry_run:
        steps.append("dry_run 完成。确认数据量正确后，使用 dry_run=false 正式迁移")
        return steps

    menu = summary.get("steps", {}).get("menu_migration", {})
    member = summary.get("steps", {}).get("member_migration", {})
    config = summary.get("steps", {}).get("config_mapping", {})

    if menu.get("success_rate", 0) < 99.5:
        steps.append(
            f"⚠️  菜品迁移成功率 {menu.get('success_rate')}% 未达标（≥99.5%），"
            "请检查错误日志后重新执行"
        )

    if member.get("pending_review", 0) > 0:
        balance = member.get("pending_balance_yuan", 0)
        steps.append(
            f"💰 {member['pending_review']} 位会员共 ¥{balance:.2f} 储值待审核。"
            "请财务负责人查看 GET /api/v1/migration/pending-members/summary 后逐一审批"
        )

    if prefilled := summary.get("prefilled_answers"):
        remaining = config.get("remaining_questions", 20)
        steps.append(
            f"✅ 已自动读取 {config.get('prefilled_count', 0)} 项天财配置。"
            f"仅需回答 {remaining} 个关键问题 → "
            f"POST /api/v1/onboarding/start "
            f'(migration_source=tiancai, prefilled_answers=<见 summary>)'
        )

    steps.append("最后：运行 GET /api/v1/config/health/{tenant_id}，score ≥ 90 后正式上线")
    return steps
