"""KDS 宴席同步出品 API — 徐记海鲜宴席核心

宴席出品与普通堂食出品的根本区别：
  普通堂食：订单→分单→各档口自主出品（时序宽松）
  宴席出品：多桌同步→按节统一触发→所有档口同步出品→倒计时协同

核心流程：
  1. 宴席场次开席（open）→ 系统为每桌创建宴席订单
  2. KDS收到宴席模式信号 → 进入倒计时等待状态（非立即出品）
  3. 厨师长在控菜大屏点击「推进到下一节」→ 触发该节所有档口同步开始制作
  4. KDS任务在「宴席节」维度协同，而非单个任务维度
"""
import uuid as _uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/kds", tags=["kds-banquet"])


# ─── 工具 ─────────────────────────────────────────────────────────────────────

def _tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _rls(db: AsyncSession, tid: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class BanquetOpenReq(BaseModel):
    """开席 — 为所有桌台创建宴席订单并分发KDS任务（第一节）"""
    session_id: str
    operator_id: Optional[str] = None
    first_section_delay_minutes: int = Field(0, ge=0,
        description="开席后多少分钟推送第一节（凉菜通常立即，热菜延迟10分钟）")


class PushSectionReq(BaseModel):
    """推进到指定节 — 所有桌台同步触发该节出品"""
    session_id: str
    section_id: str
    operator_id: Optional[str] = None
    notes: Optional[str] = None


class BanquetTaskStatusReq(BaseModel):
    """批量更新宴席任务状态（厨师长统一操作整桌）"""
    session_id: str
    section_id: str
    dept_id: Optional[str] = Field(None, description="仅操作指定档口，None=全部档口")
    action: str = Field(..., pattern="^(start|finish|hold|rush)$")
    operator_id: Optional[str] = None


# ─── 宴席KDS核心端点 ──────────────────────────────────────────────────────────

@router.get("/banquet-sessions/{store_id}", summary="查询门店今日宴席场次（KDS大屏用）")
async def list_today_banquet_sessions(
    store_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """KDS控菜大屏启动时拉取今日所有宴席场次及当前出品进度。"""
    tid = _tenant(request)
    await _rls(db, tid)

    result = await db.execute(text("""
        SELECT bs.id, bs.session_name, bs.scheduled_at, bs.actual_open_at,
               bs.status, bs.guest_count, bs.table_count,
               bs.current_section_id, bs.next_section_at,
               bm.menu_name, bm.per_person_fen,
               cs.section_name AS current_section_name,
               cs.serve_sequence AS current_serve_sequence
        FROM banquet_sessions bs
        LEFT JOIN banquet_menus bm ON bm.id = bs.banquet_menu_id
        LEFT JOIN banquet_menu_sections cs ON cs.id = bs.current_section_id
        WHERE bs.store_id = :sid AND bs.tenant_id = :tid
          AND DATE(bs.scheduled_at) = CURRENT_DATE
          AND bs.is_deleted = false
          AND bs.status NOT IN ('cancelled')
        ORDER BY bs.scheduled_at
    """), {"sid": _uuid.UUID(store_id), "tid": _uuid.UUID(tid)})

    rows = result.fetchall()
    sessions = []
    for r in rows:
        # 计算到开席倒计时秒数
        countdown_seconds = None
        if r[2] and r[4] == "scheduled":
            delta = r[2].replace(tzinfo=None) - datetime.utcnow()
            countdown_seconds = max(0, int(delta.total_seconds()))

        sessions.append({
            "id": str(r[0]),
            "session_name": r[1],
            "scheduled_at": r[2].isoformat() if r[2] else None,
            "actual_open_at": r[3].isoformat() if r[3] else None,
            "status": r[4],
            "guest_count": r[5],
            "table_count": r[6],
            "current_section_id": str(r[7]) if r[7] else None,
            "current_section_name": r[11],
            "current_serve_sequence": r[12],
            "next_section_at": r[8].isoformat() if r[8] else None,
            "menu_name": r[9],
            "per_person_fen": r[10],
            "countdown_seconds": countdown_seconds,
            "is_urgent": countdown_seconds is not None and countdown_seconds < 1800,  # 30分钟内
        })

    return _ok({"sessions": sessions, "total": len(sessions)})


@router.post("/banquet-sessions/open", summary="开席 — 同步下发第一节出品任务")
async def banquet_open(
    req: BanquetOpenReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    执行开席操作：
    1. 更新场次状态为 serving
    2. 为每桌每道菜创建 KDS 任务（status=pending，标记为宴席模式）
    3. 立即推送第一节（凉菜）的出品任务到对应档口KDS
    4. 后续节按 serve_delay_minutes 定时自动推送（或厨师长手动推进）
    """
    tid = _tenant(request)
    await _rls(db, tid)
    tiduid = _uuid.UUID(tid)

    # 查宴席场次
    session_result = await db.execute(text("""
        SELECT bs.id, bs.status, bs.table_ids, bs.order_ids,
               bs.banquet_menu_id, bs.table_count, bs.guest_count
        FROM banquet_sessions bs
        WHERE bs.id = :sid AND bs.tenant_id = :tid AND bs.is_deleted = false
    """), {"sid": _uuid.UUID(req.session_id), "tid": tiduid})
    session = session_result.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="宴席场次不存在")
    if session[1] not in ("scheduled", "preparing"):
        raise HTTPException(status_code=400, detail=f"场次状态为 {session[1]}，无法开席")

    # 获取宴席菜单第一节菜品
    first_section_result = await db.execute(text("""
        SELECT s.id AS section_id, s.section_name, s.serve_delay_minutes,
               mi.dish_id, mi.dish_name, mi.quantity_per_table, mi.note
        FROM banquet_menu_sections s
        JOIN banquet_menu_items mi ON mi.section_id = s.id
        WHERE s.menu_id = :mid AND s.tenant_id = :tid
          AND s.serve_sequence = (
            SELECT MIN(serve_sequence) FROM banquet_menu_sections
            WHERE menu_id = :mid AND tenant_id = :tid
          )
        ORDER BY mi.sort_order
    """), {"mid": session[4], "tid": tiduid})
    first_section_items = first_section_result.fetchall()

    if not first_section_items:
        raise HTTPException(status_code=422, detail="宴席菜单未配置菜品，无法开席")

    first_section_id = str(first_section_items[0][0])
    table_ids = session[2] or []
    table_count = session[5] or len(table_ids)

    # 为每桌第一节每道菜创建KDS任务
    tasks_created = 0
    for item in first_section_items:
        section_id, section_name, _, dish_id, dish_name, qty_per_table, note = item

        # 查找菜品对应档口
        dept_result = await db.execute(text("""
            SELECT dept_id FROM dish_dept_mappings
            WHERE dish_id = :did AND tenant_id = :tid
            LIMIT 1
        """), {"did": dish_id, "tid": tiduid})
        dept_row = dept_result.fetchone()
        dept_id = dept_row[0] if dept_row else None

        # 为每桌创建任务
        for table_idx in range(table_count):
            table_no = f"宴席-{table_idx + 1}桌"
            if table_ids and table_idx < len(table_ids):
                # 查实际桌号
                t_result = await db.execute(text(
                    "SELECT table_no FROM tables WHERE id = :tid_t AND tenant_id = :tid"
                ), {"tid_t": _uuid.UUID(str(table_ids[table_idx])), "tid": tiduid})
                t_row = t_result.fetchone()
                if t_row:
                    table_no = t_row[0]

            task_id = _uuid.uuid4()
            await db.execute(text("""
                INSERT INTO kds_tasks
                    (id, tenant_id, dept_id, dish_id, dish_name,
                     quantity, table_number, notes, status, priority,
                     banquet_session_id, banquet_section_id)
                VALUES
                    (:id, :tid, :dept, :did, :dname,
                     :qty, :tno, :notes, 'pending', 'normal',
                     :session_id, :section_id)
                ON CONFLICT DO NOTHING
            """), {
                "id": task_id, "tid": tiduid,
                "dept": dept_id, "did": dish_id, "dname": dish_name,
                "qty": qty_per_table, "tno": table_no,
                "notes": note or "",
                "session_id": _uuid.UUID(req.session_id),
                "section_id": section_id,
            })
            tasks_created += 1

    # 更新场次状态
    await db.execute(text("""
        UPDATE banquet_sessions SET
            status = 'serving',
            actual_open_at = now(),
            current_section_id = :section_id,
            updated_at = now()
        WHERE id = :sid AND tenant_id = :tid
    """), {"section_id": _uuid.UUID(first_section_id),
           "sid": _uuid.UUID(req.session_id), "tid": tiduid})

    await db.commit()

    log.info("banquet.opened",
             session_id=req.session_id,
             first_section=first_section_items[0][1],
             tasks_created=tasks_created)

    return _ok({
        "session_id": req.session_id,
        "status": "serving",
        "first_section_name": first_section_items[0][1],
        "tasks_created": tasks_created,
        "table_count": table_count,
        "message": f"宴席已开席，{first_section_items[0][1]}（{tasks_created}个出品任务）已下发到各档口KDS",
    })


@router.post("/banquet-sessions/push-section", summary="推进到下一节（所有档口同步出品）")
async def push_next_section(
    req: PushSectionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    厨师长操作：将指定节的所有菜品同步推送到各档口KDS。
    这是宴席同步出品的核心操作，所有桌同时出品同一节。
    """
    tid = _tenant(request)
    await _rls(db, tid)
    tiduid = _uuid.UUID(tid)

    # 查该节菜品
    items_result = await db.execute(text("""
        SELECT mi.dish_id, mi.dish_name, mi.quantity_per_table, mi.note,
               s.section_name, s.serve_sequence
        FROM banquet_menu_items mi
        JOIN banquet_menu_sections s ON s.id = mi.section_id
        WHERE mi.section_id = :sec_id AND mi.tenant_id = :tid
        ORDER BY mi.sort_order
    """), {"sec_id": _uuid.UUID(req.section_id), "tid": tiduid})
    items = items_result.fetchall()
    if not items:
        raise HTTPException(status_code=404, detail="该节无菜品配置")

    section_name = items[0][4]

    # 获取场次桌台信息
    session_result = await db.execute(text("""
        SELECT table_count, table_ids FROM banquet_sessions
        WHERE id = :sid AND tenant_id = :tid
    """), {"sid": _uuid.UUID(req.session_id), "tid": tiduid})
    session = session_result.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="宴席场次不存在")

    table_count = session[0]
    table_ids = session[1] or []
    tasks_created = 0

    for item in items:
        dish_id, dish_name, qty_per_table, note = item[0], item[1], item[2], item[3]

        # 查档口映射
        dept_result = await db.execute(text("""
            SELECT dept_id FROM dish_dept_mappings
            WHERE dish_id = :did AND tenant_id = :tid LIMIT 1
        """), {"did": dish_id, "tid": tiduid})
        dept_row = dept_result.fetchone()
        dept_id = dept_row[0] if dept_row else None

        for table_idx in range(table_count):
            table_no = f"宴席-{table_idx + 1}桌"
            if table_ids and table_idx < len(table_ids):
                t_result = await db.execute(text(
                    "SELECT table_no FROM tables WHERE id = :tid_t AND tenant_id = :tid"
                ), {"tid_t": _uuid.UUID(str(table_ids[table_idx])), "tid": tiduid})
                t_row = t_result.fetchone()
                if t_row:
                    table_no = t_row[0]

            task_id = _uuid.uuid4()
            await db.execute(text("""
                INSERT INTO kds_tasks
                    (id, tenant_id, dept_id, dish_id, dish_name,
                     quantity, table_number, notes, status, priority,
                     banquet_session_id, banquet_section_id)
                VALUES
                    (:id, :tid, :dept, :did, :dname,
                     :qty, :tno, :notes, 'pending', 'normal',
                     :session_id, :section_id)
            """), {
                "id": task_id, "tid": tiduid,
                "dept": dept_id, "did": dish_id, "dname": dish_name,
                "qty": qty_per_table, "tno": table_no,
                "notes": note or "",
                "session_id": _uuid.UUID(req.session_id),
                "section_id": _uuid.UUID(req.section_id),
            })
            tasks_created += 1

    # 更新场次当前节
    await db.execute(text("""
        UPDATE banquet_sessions SET
            current_section_id = :sec_id, updated_at = now()
        WHERE id = :sid AND tenant_id = :tid
    """), {"sec_id": _uuid.UUID(req.section_id),
           "sid": _uuid.UUID(req.session_id), "tid": tiduid})

    await db.commit()

    log.info("banquet.section_pushed",
             session_id=req.session_id, section_name=section_name,
             tasks_created=tasks_created)

    return _ok({
        "session_id": req.session_id,
        "section_id": req.section_id,
        "section_name": section_name,
        "tasks_created": tasks_created,
        "message": f"「{section_name}」已同步下发到所有档口KDS（{tasks_created}个任务）",
    })


@router.get("/banquet-sessions/{session_id}/progress", summary="宴席出品进度总览")
async def get_banquet_progress(
    session_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """KDS控菜大屏：显示宴席各节出品完成率（出品进度条）。"""
    tid = _tenant(request)
    await _rls(db, tid)

    result = await db.execute(text("""
        SELECT
            s.section_name,
            s.serve_sequence,
            COUNT(t.id) AS total_tasks,
            COUNT(CASE WHEN t.status = 'done' THEN 1 END) AS done_tasks,
            COUNT(CASE WHEN t.status = 'cooking' THEN 1 END) AS cooking_tasks,
            COUNT(CASE WHEN t.status = 'pending' THEN 1 END) AS pending_tasks
        FROM banquet_menu_sections s
        LEFT JOIN kds_tasks t ON t.banquet_section_id = s.id
            AND t.banquet_session_id = :sid
            AND t.tenant_id = :tid
        WHERE s.menu_id = (
            SELECT banquet_menu_id FROM banquet_sessions
            WHERE id = :sid AND tenant_id = :tid
        ) AND s.tenant_id = :tid
        GROUP BY s.id, s.section_name, s.serve_sequence
        ORDER BY s.serve_sequence
    """), {"sid": _uuid.UUID(session_id), "tid": _uuid.UUID(tid)})

    rows = result.fetchall()
    sections = []
    for r in rows:
        total = r[2] or 0
        done = r[3] or 0
        cooking = r[4] or 0
        pending = r[5] or 0
        sections.append({
            "section_name": r[0],
            "serve_sequence": r[1],
            "total_tasks": total,
            "done_tasks": done,
            "cooking_tasks": cooking,
            "pending_tasks": pending,
            "completion_pct": round(done / total * 100) if total > 0 else 0,
            "status": (
                "not_started" if total == 0
                else "completed" if done == total
                else "in_progress" if cooking + done > 0
                else "pending"
            ),
        })

    overall_total = sum(s["total_tasks"] for s in sections)
    overall_done = sum(s["done_tasks"] for s in sections)

    return _ok({
        "session_id": session_id,
        "sections": sections,
        "overall_completion_pct": round(overall_done / overall_total * 100) if overall_total > 0 else 0,
        "overall_total": overall_total,
        "overall_done": overall_done,
    })
