"""宴席菜单 API — 徐记海鲜宴席核心

涵盖：
  - 宴席菜单档次管理（标准/精品/豪华/定制）
  - 菜单分节配置（凉菜/热菜/海鲜/汤/主食）
  - 菜单明细管理（每节菜品、替换选项）
  - 宴席场次创建与状态管理
  - 一键生成全桌订单（按宴席菜单展开）
  - 宴席通知单打印
"""

import uuid as _uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/menu", tags=["banquet-menu"])

TIER_NAMES = {
    "standard": "标准宴",
    "premium": "精品宴",
    "luxury": "豪华宴",
    "custom": "定制宴",
}


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


class CreateBanquetMenuReq(BaseModel):
    store_id: Optional[str] = Field(None, description="NULL=集团通用，有值=门店专属")
    menu_code: str = Field(..., max_length=50, description="如：BQ-288")
    menu_name: str = Field(..., max_length=100, description="如：精品宴288元/位")
    tier: str = Field(..., pattern="^(standard|premium|luxury|custom)$")
    per_person_fen: int = Field(..., ge=0, description="人均价格（分）")
    min_persons: int = Field(20, ge=1)
    min_tables: int = Field(2, ge=1)
    description: Optional[str] = None
    highlights: Optional[list[str]] = Field(None, description="亮点列表，如：[时令活鲜,私厨服务]")
    valid_from: Optional[str] = Field(None, description="有效期开始 YYYY-MM-DD")
    valid_until: Optional[str] = Field(None, description="有效期截止 YYYY-MM-DD")


class CreateSectionReq(BaseModel):
    section_name: str = Field(..., max_length=50, description="凉菜/热菜/海鲜/汤/主食/甜品/水果")
    serve_sequence: int = Field(..., ge=1, description="出品顺序（小=先上）")
    serve_delay_minutes: int = Field(0, ge=0, description="相对开席的延迟分钟")
    sort_order: int = 0
    notes: Optional[str] = None


class BanquetMenuItemReq(BaseModel):
    dish_id: str
    quantity_per_table: int = Field(1, ge=1)
    is_mandatory: bool = True
    alternative_dish_ids: Optional[list[str]] = None
    extra_price_fen: int = 0
    note: Optional[str] = None
    sort_order: int = 0


class CreateSessionReq(BaseModel):
    """创建宴席场次——对应一次实际开席执行"""

    store_id: str
    banquet_menu_id: str
    contract_id: Optional[str] = None
    session_name: Optional[str] = Field(None, description="如：刘先生婚宴2026-04-05")
    scheduled_at: str = Field(..., description="计划开席时间 ISO8601")
    guest_count: int = Field(..., ge=1)
    table_count: int = Field(..., ge=1)
    table_ids: Optional[list[str]] = Field(None, description="已确定的桌台UUID列表")
    notes: Optional[str] = None


class SessionActionReq(BaseModel):
    """宴席场次状态操作"""

    action: str = Field(
        ...,
        pattern="^(prepare|open|complete|cancel|next_section)$",
        description="prepare=开始备餐/open=开席/complete=结束/cancel=取消/next_section=推进到下一节",
    )
    operator_id: Optional[str] = None
    notes: Optional[str] = None


# ─── 宴席菜单档次管理 ──────────────────────────────────────────────────────────


@router.get("/banquet-menus", summary="查询宴席菜单列表")
async def list_banquet_menus(
    store_id: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    is_active: bool = Query(True),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)
    conditions = ["tenant_id = :tid", "is_deleted = false", "is_active = :active"]
    params: dict = {"tid": _uuid.UUID(tid), "active": is_active}
    if store_id:
        conditions.append("(store_id = :sid OR store_id IS NULL)")
        params["sid"] = _uuid.UUID(store_id)
    if tier:
        conditions.append("tier = :tier")
        params["tier"] = tier
    result = await db.execute(
        text(f"""
        SELECT id, menu_code, menu_name, tier, per_person_fen,
               min_persons, min_tables, description, highlights,
               is_active, valid_from, valid_until, sort_order
        FROM banquet_menus
        WHERE {" AND ".join(conditions)}
        ORDER BY per_person_fen
    """),
        params,
    )
    rows = result.fetchall()
    return _ok(
        {
            "items": [
                {
                    "id": str(r[0]),
                    "menu_code": r[1],
                    "menu_name": r[2],
                    "tier": r[3],
                    "tier_display": TIER_NAMES.get(r[3], r[3]),
                    "per_person_fen": r[4],
                    "per_person_display": f"¥{r[4] // 100}/位",
                    "min_persons": r[5],
                    "min_tables": r[6],
                    "description": r[7],
                    "highlights": r[8] or [],
                    "is_active": r[9],
                    "valid_from": str(r[10]) if r[10] else None,
                    "valid_until": str(r[11]) if r[11] else None,
                }
                for r in rows
            ],
            "total": len(rows),
        }
    )


@router.post("/banquet-menus", summary="创建宴席菜单档次", status_code=201)
async def create_banquet_menu(
    req: CreateBanquetMenuReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)
    menu_id = _uuid.uuid4()
    await db.execute(
        text("""
        INSERT INTO banquet_menus
            (id, tenant_id, store_id, menu_code, menu_name, tier,
             per_person_fen, min_persons, min_tables,
             description, highlights, valid_from, valid_until)
        VALUES
            (:id, :tid, :sid, :code, :name, :tier,
             :price, :min_p, :min_t,
             :desc, :hl::jsonb, :vf::date, :vu::date)
    """),
        {
            "id": menu_id,
            "tid": _uuid.UUID(tid),
            "sid": _uuid.UUID(req.store_id) if req.store_id else None,
            "code": req.menu_code,
            "name": req.menu_name,
            "tier": req.tier,
            "price": req.per_person_fen,
            "min_p": req.min_persons,
            "min_t": req.min_tables,
            "desc": req.description,
            "hl": str(req.highlights).replace("'", '"') if req.highlights else None,
            "vf": req.valid_from,
            "vu": req.valid_until,
        },
    )
    await db.commit()
    log.info("banquet_menu.created", menu_id=str(menu_id), name=req.menu_name)
    return _ok({"menu_id": str(menu_id), "menu_name": req.menu_name, "tier": req.tier})


@router.get("/banquet-menus/{menu_id}", summary="查询宴席菜单详情（含分节和菜品）")
async def get_banquet_menu_detail(
    menu_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回完整宴席菜单：菜单信息 + 所有分节 + 每节菜品列表"""
    tid = _tenant(request)
    await _rls(db, tid)
    mid = _uuid.UUID(menu_id)
    tiduid = _uuid.UUID(tid)

    # 菜单基本信息
    menu_result = await db.execute(
        text("""
        SELECT id, menu_code, menu_name, tier, per_person_fen,
               min_persons, min_tables, description, highlights
        FROM banquet_menus
        WHERE id = :mid AND tenant_id = :tid AND is_deleted = false
    """),
        {"mid": mid, "tid": tiduid},
    )
    menu = menu_result.fetchone()
    if not menu:
        raise HTTPException(status_code=404, detail="宴席菜单不存在")

    # 分节列表
    sections_result = await db.execute(
        text("""
        SELECT id, section_name, serve_sequence, serve_delay_minutes, sort_order, notes
        FROM banquet_menu_sections
        WHERE menu_id = :mid AND tenant_id = :tid
        ORDER BY serve_sequence, sort_order
    """),
        {"mid": mid, "tid": tiduid},
    )
    sections_raw = sections_result.fetchall()

    # 每节菜品
    items_result = await db.execute(
        text("""
        SELECT bmi.id, bmi.section_id, bmi.dish_id, bmi.dish_name,
               bmi.quantity_per_table, bmi.is_mandatory,
               bmi.alternative_dish_ids, bmi.extra_price_fen,
               bmi.note, bmi.sort_order,
               d.price_fen, d.image_url, d.pricing_method
        FROM banquet_menu_items bmi
        LEFT JOIN dishes d ON d.id = bmi.dish_id
        WHERE bmi.menu_id = :mid AND bmi.tenant_id = :tid
        ORDER BY bmi.sort_order
    """),
        {"mid": mid, "tid": tiduid},
    )
    items_raw = items_result.fetchall()

    # 组装分节→菜品
    items_by_section: dict = {}
    for item in items_raw:
        sid = str(item[1])
        if sid not in items_by_section:
            items_by_section[sid] = []
        items_by_section[sid].append(
            {
                "id": str(item[0]),
                "dish_id": str(item[2]),
                "dish_name": item[3],
                "quantity_per_table": item[4],
                "is_mandatory": item[5],
                "alternative_dish_ids": item[6] or [],
                "extra_price_fen": item[7],
                "note": item[8],
                "sort_order": item[9],
                "base_price_fen": item[10],
                "image_url": item[11],
                "is_live_seafood": item[12] in ("weight", "count"),
            }
        )

    sections = [
        {
            "id": str(s[0]),
            "section_name": s[1],
            "serve_sequence": s[2],
            "serve_delay_minutes": s[3],
            "sort_order": s[4],
            "notes": s[5],
            "items": items_by_section.get(str(s[0]), []),
        }
        for s in sections_raw
    ]

    return _ok(
        {
            "id": str(menu[0]),
            "menu_code": menu[1],
            "menu_name": menu[2],
            "tier": menu[3],
            "tier_display": TIER_NAMES.get(menu[3], menu[3]),
            "per_person_fen": menu[4],
            "per_person_display": f"¥{menu[4] // 100}/位",
            "min_persons": menu[5],
            "min_tables": menu[6],
            "description": menu[7],
            "highlights": menu[8] or [],
            "sections": sections,
            "total_sections": len(sections),
            "total_dishes": sum(len(v) for v in items_by_section.values()),
        }
    )


# ─── 分节管理 ─────────────────────────────────────────────────────────────────


@router.post("/banquet-menus/{menu_id}/sections", summary="添加菜单分节", status_code=201)
async def add_section(
    menu_id: str,
    req: CreateSectionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)
    section_id = _uuid.uuid4()
    await db.execute(
        text("""
        INSERT INTO banquet_menu_sections
            (id, tenant_id, menu_id, section_name, serve_sequence,
             serve_delay_minutes, sort_order, notes)
        VALUES (:id, :tid, :mid, :name, :seq, :delay, :sort, :notes)
    """),
        {
            "id": section_id,
            "tid": _uuid.UUID(tid),
            "mid": _uuid.UUID(menu_id),
            "name": req.section_name,
            "seq": req.serve_sequence,
            "delay": req.serve_delay_minutes,
            "sort": req.sort_order,
            "notes": req.notes,
        },
    )
    await db.commit()
    return _ok({"section_id": str(section_id), "section_name": req.section_name})


@router.post("/banquet-menus/{menu_id}/sections/{section_id}/items", summary="添加菜品到分节", status_code=201)
async def add_menu_item(
    menu_id: str,
    section_id: str,
    req: BanquetMenuItemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)

    # 获取菜品名称快照
    dish_row = await db.execute(
        text("SELECT dish_name FROM dishes WHERE id = :did AND tenant_id = :tid"),
        {"did": _uuid.UUID(req.dish_id), "tid": _uuid.UUID(tid)},
    )
    dish = dish_row.fetchone()
    dish_name = dish[0] if dish else req.dish_id

    item_id = _uuid.uuid4()
    alts_json = str(req.alternative_dish_ids).replace("'", '"') if req.alternative_dish_ids else "[]"
    await db.execute(
        text("""
        INSERT INTO banquet_menu_items
            (id, tenant_id, menu_id, section_id, dish_id, dish_name,
             quantity_per_table, is_mandatory, alternative_dish_ids,
             extra_price_fen, note, sort_order)
        VALUES
            (:id, :tid, :mid, :sid, :did, :name,
             :qty, :mandatory, :alts::jsonb,
             :extra, :note, :sort)
    """),
        {
            "id": item_id,
            "tid": _uuid.UUID(tid),
            "mid": _uuid.UUID(menu_id),
            "sid": _uuid.UUID(section_id),
            "did": _uuid.UUID(req.dish_id),
            "name": dish_name,
            "qty": req.quantity_per_table,
            "mandatory": req.is_mandatory,
            "alts": alts_json,
            "extra": req.extra_price_fen,
            "note": req.note,
            "sort": req.sort_order,
        },
    )
    await db.commit()
    return _ok(
        {
            "item_id": str(item_id),
            "dish_id": req.dish_id,
            "dish_name": dish_name,
            "section_id": section_id,
        }
    )


# ─── 宴席场次管理 ──────────────────────────────────────────────────────────────


@router.post("/banquet-sessions", summary="创建宴席场次", status_code=201)
async def create_banquet_session(
    req: CreateSessionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建宴席场次。场次关联菜单、合同、桌台，是宴席执行的主体对象。"""
    tid = _tenant(request)
    await _rls(db, tid)
    session_id = _uuid.uuid4()
    table_ids_json = str(req.table_ids).replace("'", '"') if req.table_ids else "[]"
    await db.execute(
        text("""
        INSERT INTO banquet_sessions
            (id, tenant_id, store_id, contract_id, banquet_menu_id,
             session_name, scheduled_at, guest_count, table_count,
             table_ids, status, notes)
        VALUES
            (:id, :tid, :sid, :cid, :mid,
             :name, :scheduled_at, :guests, :tables,
             :table_ids::jsonb, 'scheduled', :notes)
    """),
        {
            "id": session_id,
            "tid": _uuid.UUID(tid),
            "sid": _uuid.UUID(req.store_id),
            "cid": _uuid.UUID(req.contract_id) if req.contract_id else None,
            "mid": _uuid.UUID(req.banquet_menu_id),
            "name": req.session_name,
            "scheduled_at": req.scheduled_at,
            "guests": req.guest_count,
            "tables": req.table_count,
            "table_ids": table_ids_json,
            "notes": req.notes,
        },
    )
    await db.commit()
    log.info(
        "banquet_session.created", session_id=str(session_id), name=req.session_name, scheduled_at=req.scheduled_at
    )
    return _ok(
        {
            "session_id": str(session_id),
            "session_name": req.session_name,
            "scheduled_at": req.scheduled_at,
            "status": "scheduled",
        }
    )


@router.get("/banquet-sessions", summary="查询门店宴席场次列表")
async def list_banquet_sessions(
    store_id: str = Query(...),
    status: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="按日期筛选 YYYY-MM-DD"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)
    conditions = ["bs.store_id = :sid", "bs.tenant_id = :tid", "bs.is_deleted = false"]
    params: dict = {"sid": _uuid.UUID(store_id), "tid": _uuid.UUID(tid)}
    if status:
        conditions.append("bs.status = :status")
        params["status"] = status
    if date:
        conditions.append("DATE(bs.scheduled_at) = :date::date")
        params["date"] = date
    result = await db.execute(
        text(f"""
        SELECT bs.id, bs.session_name, bs.scheduled_at, bs.status,
               bs.guest_count, bs.table_count, bs.notes,
               bm.menu_name, bm.tier, bm.per_person_fen
        FROM banquet_sessions bs
        LEFT JOIN banquet_menus bm ON bm.id = bs.banquet_menu_id
        WHERE {" AND ".join(conditions)}
        ORDER BY bs.scheduled_at
    """),
        params,
    )
    rows = result.fetchall()
    return _ok(
        {
            "items": [
                {
                    "id": str(r[0]),
                    "session_name": r[1],
                    "scheduled_at": r[2].isoformat() if r[2] else None,
                    "status": r[3],
                    "guest_count": r[4],
                    "table_count": r[5],
                    "notes": r[6],
                    "menu_name": r[7],
                    "tier": r[8],
                    "per_person_fen": r[9],
                    "estimated_total_fen": (r[9] or 0) * (r[4] or 0),
                }
                for r in rows
            ],
            "total": len(rows),
        }
    )


@router.post("/banquet-sessions/{session_id}/action", summary="宴席场次状态操作")
async def banquet_session_action(
    session_id: str,
    req: SessionActionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    宴席场次状态机：
      scheduled → prepare（备餐）
      preparing → open（开席）
      serving → next_section（推进到下一节出品）
      serving → complete（宴席结束）
      任意 → cancel（取消）
    """
    tid = _tenant(request)
    await _rls(db, tid)

    # 查当前状态
    cur = await db.execute(
        text("""
        SELECT status, banquet_menu_id, table_ids, scheduled_at, current_section_id
        FROM banquet_sessions
        WHERE id = :sid AND tenant_id = :tid AND is_deleted = false
    """),
        {"sid": _uuid.UUID(session_id), "tid": _uuid.UUID(tid)},
    )
    session = cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="宴席场次不存在")

    current_status, menu_id, table_ids, scheduled_at, current_section_id = session

    # 状态转换逻辑
    update_fields: dict = {}
    action = req.action

    if action == "prepare":
        if current_status != "scheduled":
            raise HTTPException(status_code=400, detail=f"当前状态 {current_status}，无法开始备餐")
        update_fields["status"] = "preparing"

    elif action == "open":
        if current_status not in ("scheduled", "preparing"):
            raise HTTPException(status_code=400, detail=f"当前状态 {current_status}，无法开席")
        update_fields["status"] = "serving"
        update_fields["actual_open_at"] = "now()"

        # 获取第一节分节，设置下一节触发时间
        first_section = await db.execute(
            text("""
            SELECT id, serve_delay_minutes FROM banquet_menu_sections
            WHERE menu_id = :mid AND tenant_id = :tid
            ORDER BY serve_sequence LIMIT 1
        """),
            {"mid": _uuid.UUID(str(menu_id)), "tid": _uuid.UUID(tid)},
        )
        first = first_section.fetchone()
        if first:
            update_fields["current_section_id"] = str(first[0])

    elif action == "next_section":
        if current_status != "serving":
            raise HTTPException(status_code=400, detail="宴席未在进行中")
        # 查找下一节
        if current_section_id:
            next_sec = await db.execute(
                text("""
                SELECT id, section_name, serve_delay_minutes FROM banquet_menu_sections
                WHERE menu_id = :mid AND tenant_id = :tid
                  AND serve_sequence > (
                    SELECT serve_sequence FROM banquet_menu_sections
                    WHERE id = :cur_sid
                  )
                ORDER BY serve_sequence LIMIT 1
            """),
                {"mid": _uuid.UUID(str(menu_id)), "tid": _uuid.UUID(tid), "cur_sid": current_section_id},
            )
            next_row = next_sec.fetchone()
            if next_row:
                update_fields["current_section_id"] = str(next_row[0])
                section_name = next_row[1]
            else:
                section_name = "全部菜品已出品"
        else:
            section_name = "未知"

    elif action == "complete":
        if current_status != "serving":
            raise HTTPException(status_code=400, detail=f"当前状态 {current_status}，无法结束")
        update_fields["status"] = "completed"
        update_fields["completed_at"] = "now()"

    elif action == "cancel":
        if current_status in ("completed",):
            raise HTTPException(status_code=400, detail="已结束的场次无法取消")
        update_fields["status"] = "cancelled"

    # 构建 UPDATE SQL
    set_parts = []
    set_params: dict = {"sid": _uuid.UUID(session_id), "tid": _uuid.UUID(tid)}
    for k, v in update_fields.items():
        if v == "now()":
            set_parts.append(f"{k} = now()")
        else:
            set_parts.append(f"{k} = :{k}")
            set_params[k] = v

    if set_parts:
        await db.execute(
            text(f"""
            UPDATE banquet_sessions
            SET {", ".join(set_parts)}, updated_at = now()
            WHERE id = :sid AND tenant_id = :tid
        """),
            set_params,
        )

    await db.commit()

    log.info(
        "banquet_session.action",
        session_id=session_id,
        action=action,
        new_status=update_fields.get("status", current_status),
    )

    return _ok(
        {
            "session_id": session_id,
            "action": action,
            "previous_status": current_status,
            "current_status": update_fields.get("status", current_status),
            "current_section_id": update_fields.get("current_section_id"),
        }
    )


@router.get("/banquet-sessions/{session_id}/print-notice", summary="获取宴席通知单打印数据")
async def get_banquet_notice_print_data(
    session_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回宴席通知单所需的完整打印数据。
    格式化好后可直接传给 printer_service 生成 ESC/POS 指令。
    """
    tid = _tenant(request)
    await _rls(db, tid)
    tiduid = _uuid.UUID(tid)

    session_result = await db.execute(
        text("""
        SELECT bs.id, bs.session_name, bs.scheduled_at, bs.guest_count, bs.table_count,
               bs.notes, bs.status,
               bm.menu_name, bm.per_person_fen, bm.tier
        FROM banquet_sessions bs
        LEFT JOIN banquet_menus bm ON bm.id = bs.banquet_menu_id
        WHERE bs.id = :sid AND bs.tenant_id = :tid
    """),
        {"sid": _uuid.UUID(session_id), "tid": tiduid},
    )
    session = session_result.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="宴席场次不存在")

    # 获取菜单详情（各节菜品）
    menu_result = await db.execute(
        text("""
        SELECT s.section_name, s.serve_sequence, s.serve_delay_minutes,
               mi.dish_name, mi.quantity_per_table, mi.is_mandatory, mi.note
        FROM banquet_menu_sections s
        JOIN banquet_menu_items mi ON mi.section_id = s.id
        WHERE s.menu_id = (
            SELECT banquet_menu_id FROM banquet_sessions
            WHERE id = :sid AND tenant_id = :tid
        ) AND s.tenant_id = :tid
        ORDER BY s.serve_sequence, mi.sort_order
    """),
        {"sid": _uuid.UUID(session_id), "tid": tiduid},
    )
    menu_rows = menu_result.fetchall()

    # 按分节组装
    sections_map: dict = {}
    for r in menu_rows:
        sec_name = r[0]
        if sec_name not in sections_map:
            sections_map[sec_name] = {
                "section_name": sec_name,
                "serve_sequence": r[1],
                "serve_delay_minutes": r[2],
                "items": [],
            }
        sections_map[sec_name]["items"].append(
            {
                "dish_name": r[3],
                "quantity_per_table": r[4],
                "is_mandatory": r[5],
                "note": r[6] or "",
            }
        )
    sections = sorted(sections_map.values(), key=lambda x: x["serve_sequence"])

    scheduled_dt = session[2]
    scheduled_str = scheduled_dt.strftime("%Y-%m-%d %H:%M") if scheduled_dt else "待定"

    return _ok(
        {
            "print_type": "banquet_notice",
            "session_id": session_id,
            "header": {
                "title": "宴席开席通知",
                "session_name": session[1] or "宴席",
                "menu_name": session[7],
                "tier_display": TIER_NAMES.get(session[9], session[9]),
                "per_person_display": f"¥{session[8] // 100}/位" if session[8] else "",
            },
            "event_info": {
                "scheduled_at_display": scheduled_str,
                "guest_count": session[3],
                "table_count": session[4],
            },
            "menu_sections": sections,
            "special_notes": session[5] or "",
            "footer": "请各档口按出品顺序准时出品",
        }
    )
