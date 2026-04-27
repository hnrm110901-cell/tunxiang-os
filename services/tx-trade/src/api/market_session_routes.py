"""营业市别 API — 早市/午市/晚市时段管理

端点：
  GET    /api/v1/market-sessions/current/{store_id}   — 当前进行中市别（按时间匹配）
  GET    /api/v1/market-sessions/store/{store_id}      — 门店市别配置列表
  POST   /api/v1/market-sessions/store/{store_id}      — 新建/更新门店市别
  DELETE /api/v1/market-sessions/{session_id}          — 删除市别配置
  GET    /api/v1/market-sessions/templates             — 集团市别模板列表
  POST   /api/v1/market-sessions/templates             — 新建市别模板
  PUT    /api/v1/market-sessions/templates/{template_id} — 更新市别模板

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/market-sessions", tags=["market-sessions"])

# ─── 默认市别模板（DB无数据时兜底，不崩溃）──────────────────────────────────────

_DEFAULT_TEMPLATES = [
    {
        "id": "default-breakfast",
        "name": "早市",
        "code": "breakfast",
        "display_order": 1,
        "start_time": "06:00",
        "end_time": "11:00",
        "is_active": True,
        "source": "default",
    },
    {
        "id": "default-lunch",
        "name": "午市",
        "code": "lunch",
        "display_order": 2,
        "start_time": "11:00",
        "end_time": "14:30",
        "is_active": True,
        "source": "default",
    },
    {
        "id": "default-dinner",
        "name": "晚市",
        "code": "dinner",
        "display_order": 3,
        "start_time": "17:00",
        "end_time": "21:00",
        "is_active": True,
        "source": "default",
    },
    {
        "id": "default-late-night",
        "name": "夜宵",
        "code": "late_night",
        "display_order": 4,
        "start_time": "21:00",
        "end_time": "02:00",
        "is_active": True,
        "source": "default",
    },
]


# ─── 通用工具 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> HTTPException:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"), {"tid": tenant_id})


def _is_time_in_session(current: time, start: time, end: time) -> bool:
    """判断 current 是否落在 [start, end) 区间内，支持跨夜市别（end < start）"""
    if start <= end:
        return start <= current < end
    # 跨夜：如夜宵 21:00 - 次日 02:00
    return current >= start or current < end


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class MarketSessionTemplateCreateReq(BaseModel):
    name: str = Field(max_length=50, description="市别名称，如早市")
    code: str = Field(max_length=20, description="代码，如 breakfast/lunch/dinner/late_night")
    display_order: int = Field(default=0, ge=0)
    start_time: str = Field(description="开始时间，格式 HH:MM，如 06:00")
    end_time: str = Field(description="结束时间，格式 HH:MM，如 11:00")
    brand_id: Optional[str] = Field(default=None, description="品牌ID，NULL=全集团通用")
    is_active: bool = Field(default=True)


class MarketSessionTemplateUpdateReq(BaseModel):
    name: Optional[str] = Field(default=None, max_length=50)
    code: Optional[str] = Field(default=None, max_length=20)
    display_order: Optional[int] = Field(default=None, ge=0)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    brand_id: Optional[str] = None
    is_active: Optional[bool] = None


class StoreMarketSessionCreateReq(BaseModel):
    name: str = Field(max_length=50)
    start_time: str = Field(description="格式 HH:MM")
    end_time: str = Field(description="格式 HH:MM")
    template_id: Optional[str] = Field(default=None, description="引用模板ID，NULL=自定义")
    menu_plan_id: Optional[str] = Field(default=None, description="绑定菜谱方案ID")
    is_active: bool = Field(default=True)


# ─── 辅助：当前市别查询 ────────────────────────────────────────────────────────


async def _get_current_market_session_id(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> Optional[str]:
    """查询当前时间所在的市别ID（优先门店配置，无则返回None）"""
    await _set_rls(db, tenant_id)
    now_time = datetime.now().time()

    result = await db.execute(
        text("""
            SELECT id, start_time, end_time
            FROM store_market_sessions
            WHERE tenant_id = :tid
              AND store_id = :sid
              AND is_active = TRUE
        """),
        {"tid": tenant_id, "sid": store_id},
    )
    rows = result.fetchall()

    for row in rows:
        start = (
            row.start_time
            if isinstance(row.start_time, time)
            else datetime.strptime(str(row.start_time), "%H:%M:%S").time()
        )
        end = (
            row.end_time if isinstance(row.end_time, time) else datetime.strptime(str(row.end_time), "%H:%M:%S").time()
        )
        if _is_time_in_session(now_time, start, end):
            return str(row.id)
    return None


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/current/{store_id}", summary="获取当前进行中市别")
async def get_current_session(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    根据当前服务器时间匹配门店正在进行的市别。

    - 优先查门店自定义配置（store_market_sessions）
    - 无门店配置时回落到集团模板（market_session_templates）
    - 两者都无匹配时返回 data: null（不报错）
    - 支持跨夜市别：end_time < start_time 视为跨夜
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)
    now_time = datetime.now().time()
    now_str = now_time.strftime("%H:%M:%S")

    log = logger.bind(store_id=str(store_id), current_time=now_str, tenant_id=tid)

    # 1. 先查门店自定义配置
    store_result = await db.execute(
        text("""
            SELECT id, name, start_time, end_time, template_id, menu_plan_id
            FROM store_market_sessions
            WHERE tenant_id = :tid
              AND store_id = :sid
              AND is_active = TRUE
            ORDER BY start_time
        """),
        {"tid": tid, "sid": str(store_id)},
    )
    store_rows = store_result.fetchall()

    for row in store_rows:
        start = (
            row.start_time
            if isinstance(row.start_time, time)
            else datetime.strptime(str(row.start_time), "%H:%M:%S").time()
        )
        end = (
            row.end_time if isinstance(row.end_time, time) else datetime.strptime(str(row.end_time), "%H:%M:%S").time()
        )
        if _is_time_in_session(now_time, start, end):
            log.info("market_session_matched", source="store", session_id=str(row.id))
            return _ok(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "start_time": str(row.start_time),
                    "end_time": str(row.end_time),
                    "template_id": str(row.template_id) if row.template_id else None,
                    "menu_plan_id": str(row.menu_plan_id) if row.menu_plan_id else None,
                    "source": "store",
                    "current_time": now_str,
                }
            )

    # 2. 回落到集团模板
    tmpl_result = await db.execute(
        text("""
            SELECT id, name, code, start_time, end_time
            FROM market_session_templates
            WHERE tenant_id = :tid
              AND is_active = TRUE
            ORDER BY display_order, start_time
        """),
        {"tid": tid},
    )
    tmpl_rows = tmpl_result.fetchall()

    for row in tmpl_rows:
        start = (
            row.start_time
            if isinstance(row.start_time, time)
            else datetime.strptime(str(row.start_time), "%H:%M:%S").time()
        )
        end = (
            row.end_time if isinstance(row.end_time, time) else datetime.strptime(str(row.end_time), "%H:%M:%S").time()
        )
        if _is_time_in_session(now_time, start, end):
            log.info("market_session_matched", source="template", session_id=str(row.id))
            return _ok(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "code": row.code,
                    "start_time": str(row.start_time),
                    "end_time": str(row.end_time),
                    "source": "template",
                    "current_time": now_str,
                }
            )

    log.info("market_session_no_match", reason="no_session_covers_current_time")
    return _ok(None)


@router.get("/store/{store_id}", summary="门店市别配置列表")
async def list_store_sessions(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取指定门店的所有市别配置（含禁用的），按 start_time 排序"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    result = await db.execute(
        text("""
            SELECT id, name, start_time, end_time, template_id, menu_plan_id,
                   is_active, created_at, updated_at
            FROM store_market_sessions
            WHERE tenant_id = :tid AND store_id = :sid
            ORDER BY start_time
        """),
        {"tid": tid, "sid": str(store_id)},
    )
    rows = result.fetchall()
    items = [
        {
            "id": str(r.id),
            "name": r.name,
            "start_time": str(r.start_time),
            "end_time": str(r.end_time),
            "template_id": str(r.template_id) if r.template_id else None,
            "menu_plan_id": str(r.menu_plan_id) if r.menu_plan_id else None,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return _ok({"items": items, "total": len(items)})


@router.post("/store/{store_id}", summary="新建门店市别配置")
async def create_store_session(
    store_id: uuid.UUID,
    body: StoreMarketSessionCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """为指定门店新增一个市别配置（可引用模板或自定义）"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    new_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO store_market_sessions
                (id, tenant_id, store_id, template_id, name, start_time, end_time,
                 menu_plan_id, is_active)
            VALUES
                (:id, :tid, :sid, :template_id, :name, :start_time, :end_time,
                 :menu_plan_id, :is_active)
        """),
        {
            "id": new_id,
            "tid": tid,
            "sid": str(store_id),
            "template_id": body.template_id,
            "name": body.name,
            "start_time": body.start_time,
            "end_time": body.end_time,
            "menu_plan_id": body.menu_plan_id,
            "is_active": body.is_active,
        },
    )
    await db.commit()
    logger.info("store_market_session_created", id=new_id, store_id=str(store_id))
    return _ok({"id": new_id})


@router.delete("/{session_id}", summary="删除门店市别配置")
async def delete_store_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除（is_active=FALSE）门店市别配置"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    result = await db.execute(
        text("""
            UPDATE store_market_sessions
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = :sid AND tenant_id = :tid
        """),
        {"sid": str(session_id), "tid": tid},
    )
    await db.commit()
    if result.rowcount == 0:
        _err("市别配置不存在", code=404)
    logger.info("store_market_session_disabled", id=str(session_id))
    return _ok({"id": str(session_id), "is_active": False})


@router.get("/templates", summary="集团市别模板列表")
async def list_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    获取集团所有市别模板。

    如果 DB 中无数据，返回内置默认4个模板（早市/午市/晚市/夜宵），不崩溃。
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    try:
        result = await db.execute(
            text("""
                SELECT id, name, code, display_order, start_time, end_time,
                       brand_id, is_active, created_at
                FROM market_session_templates
                WHERE tenant_id = :tid
                ORDER BY display_order, start_time
            """),
            {"tid": tid},
        )
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001 - 表不存在等初始化期间异常，降级到默认值
        logger.warning("market_session_templates_query_failed", error=str(exc))
        return _ok({"items": _DEFAULT_TEMPLATES, "total": len(_DEFAULT_TEMPLATES), "source": "default"})

    if not rows:
        return _ok({"items": _DEFAULT_TEMPLATES, "total": len(_DEFAULT_TEMPLATES), "source": "default"})

    items = [
        {
            "id": str(r.id),
            "name": r.name,
            "code": r.code,
            "display_order": r.display_order,
            "start_time": str(r.start_time),
            "end_time": str(r.end_time),
            "brand_id": str(r.brand_id) if r.brand_id else None,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "source": "db",
        }
        for r in rows
    ]
    return _ok({"items": items, "total": len(items), "source": "db"})


@router.post("/templates", summary="新建市别模板")
async def create_template(
    body: MarketSessionTemplateCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """在集团级别新建市别模板（可指定 brand_id 限定品牌）"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    new_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO market_session_templates
                (id, tenant_id, brand_id, name, code, display_order,
                 start_time, end_time, is_active)
            VALUES
                (:id, :tid, :brand_id, :name, :code, :display_order,
                 :start_time, :end_time, :is_active)
        """),
        {
            "id": new_id,
            "tid": tid,
            "brand_id": body.brand_id,
            "name": body.name,
            "code": body.code,
            "display_order": body.display_order,
            "start_time": body.start_time,
            "end_time": body.end_time,
            "is_active": body.is_active,
        },
    )
    await db.commit()
    logger.info("market_session_template_created", id=new_id, code=body.code)
    return _ok({"id": new_id})


@router.put("/templates/{template_id}", summary="更新市别模板")
async def update_template(
    template_id: uuid.UUID,
    body: MarketSessionTemplateUpdateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """部分更新集团市别模板字段"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    # 动态构建 SET 子句，只更新非 None 字段
    set_parts = ["updated_at = NOW()"]
    params: dict = {"id": str(template_id), "tid": tid}
    for field, col in [
        ("name", "name"),
        ("code", "code"),
        ("display_order", "display_order"),
        ("start_time", "start_time"),
        ("end_time", "end_time"),
        ("brand_id", "brand_id"),
        ("is_active", "is_active"),
    ]:
        val = getattr(body, field)
        if val is not None:
            set_parts.append(f"{col} = :{col}")
            params[col] = val

    result = await db.execute(
        text(f"UPDATE market_session_templates SET {', '.join(set_parts)} WHERE id = :id AND tenant_id = :tid"),
        params,
    )
    await db.commit()
    if result.rowcount == 0:
        _err("市别模板不存在", code=404)
    logger.info("market_session_template_updated", id=str(template_id))
    return _ok({"id": str(template_id)})


# ─── 市别切换 + 拼桌自动触发 (v284) ───────────────────────────────────────────


class SwitchMarketSessionReq(BaseModel):
    new_session_id: str = Field(description="目标市别ID（store_market_sessions.id）")


@router.post("/switch/{store_id}", summary="手动切换市别（触发拼桌预设）")
async def switch_market_session(
    store_id: uuid.UUID,
    body: SwitchMarketSessionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动切换市别，并自动触发关联的拼桌预设。

    流程：
    1. 验证目标市别存在
    2. 调用 TableMergePresetService.on_market_session_switch()
       - 回滚上一个市别的拼桌方案
       - 执行新市别的 auto_trigger=TRUE 拼桌方案
    3. 返回切换结果和拼桌执行摘要

    注意：自动市别切换（按时间）由前端/定时任务调用此端点。
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    # 验证目标市别存在
    session_result = await db.execute(
        text("""
            SELECT id, name, start_time, end_time
            FROM store_market_sessions
            WHERE id = :sid AND store_id = :store_id AND tenant_id = :tid AND is_active = TRUE
        """),
        {"sid": body.new_session_id, "store_id": str(store_id), "tid": tid},
    )
    session_row = session_result.mappings().one_or_none()
    if not session_row:
        _err("目标市别不存在或未激活", code=404)

    # 触发拼桌预设
    merge_result: dict = {"triggered": False, "detail": "无拼桌预设关联此市别"}
    try:
        from ..services.table_merge_preset_service import TableMergePresetService

        merge_svc = TableMergePresetService(db, tid)
        merge_result = await merge_svc.on_market_session_switch(
            store_id=store_id,
            new_session_id=uuid.UUID(body.new_session_id),
        )
    except ImportError:
        logger.warning("table_merge_preset_service_not_available")
    except ValueError as exc:
        logger.warning("merge_preset_switch_error", error=str(exc))
        merge_result = {"triggered": False, "error": str(exc)}

    await db.commit()

    logger.info(
        "market_session_switched",
        store_id=str(store_id),
        new_session_id=body.new_session_id,
        new_session_name=session_row["name"],
        merge_triggered=merge_result.get("triggered", False),
    )

    return _ok(
        {
            "store_id": str(store_id),
            "new_session": {
                "id": str(session_row["id"]),
                "name": session_row["name"],
                "start_time": str(session_row["start_time"]),
                "end_time": str(session_row["end_time"]),
            },
            "merge_preset_result": merge_result,
        }
    )
