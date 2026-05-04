"""
快速开店 API — 门店配置克隆端点

端点列表：
  GET  /api/v1/stores/clone/available-items     可克隆配置项清单（供前端勾选）
  GET  /api/v1/stores/{store_id}/clone-preview  预览源门店数据量
  POST /api/v1/stores/clone                     执行克隆（source → target）
  GET  /api/v1/stores/clone/{task_id}           查询克隆任务状态
  POST /api/v1/stores/setup                     新建门店 + 可选克隆（一体化）

安全约束：
  - X-Tenant-ID header 必传（否则使用默认值，生产环境应改为强制校验）
  - source_store 与 target_store 必须同属一个 tenant
  - 跨 tenant 克隆请求返回 403
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from services.store_clone import (
    CLONE_ITEMS,
    NON_CLONE_ITEMS,
    StoreCloneTask,
    clone_store_config,
    get_clone_preview,
    setup_new_store,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/stores", tags=["store-clone"])

# 内存任务仓库（生产环境替换为 DB 查询）
_TASK_STORE: dict[str, dict] = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求 / 响应模型（Pydantic V2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CloneRequest(BaseModel):
    source_store_id: str = Field(..., description="源门店 ID（配置来源）")
    target_store_id: str = Field(..., description="目标门店 ID（必须已存在）")
    selected_items: List[str] = Field(
        ...,
        description=f"要克隆的配置项，有效值：{CLONE_ITEMS}",
        min_length=1,
    )
    created_by: Optional[str] = Field(None, description="操作人员工 ID（审计用）")


class StoreSetupRequest(BaseModel):
    store_name: str = Field(..., description='新门店名称，如 "尝在一起·芙蓉店"')
    brand_id: str = Field(..., description="品牌 ID")
    address: str = Field(default="", description="门店地址")
    clone_from_store_id: Optional[str] = Field(None, description="源门店 ID（不填则创建空白门店）")
    clone_items: Optional[List[str]] = Field(
        None,
        description="克隆配置项（None = 全量克隆，空列表 = 不克隆）",
    )
    created_by: Optional[str] = Field(None, description="操作人员工 ID")


class CloneItemInfo(BaseModel):
    item_type: str
    display_name: str
    description: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ITEM_META: dict[str, dict[str, str]] = {
    "tables": {"display_name": "桌台布局", "description": "桌号/区域/座位数/最低消费"},
    "production_depts": {"display_name": "出品部门", "description": "档口名称/编码/排序"},
    "receipt_templates": {"display_name": "小票模板", "description": "收银小票和厨房单模板"},
    "attendance_rules": {"display_name": "考勤规则", "description": "迟到扣款/全勤奖/打卡方式"},
    "shift_configs": {"display_name": "班次配置", "description": "早班/晚班/全天班时间设置"},
    "dispatch_rules": {"display_name": "档口路由规则", "description": "菜品→档口路由匹配规则"},
    "store_push_configs": {"display_name": "出单模式", "description": "即时出单/付款后出单"},
}


def _get_tenant(x_tenant_id: Optional[str]) -> str:
    return x_tenant_id or "default_tenant"


def _task_to_dict(task: StoreCloneTask) -> dict:
    return {
        "task_id": task.id,
        "tenant_id": task.tenant_id,
        "source_store_id": task.source_store_id,
        "target_store_id": task.target_store_id,
        "selected_items": task.selected_items,
        "status": task.status,
        "progress": task.progress,
        "result_summary": task.result_summary,
        "error_message": task.error_message,
        "created_by": task.created_by,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get(
    "/clone/available-items",
    summary="可克隆配置项清单",
    description="返回所有支持克隆的配置项及其说明，供前端渲染勾选列表。",
)
async def list_available_items() -> dict:
    items = [
        {
            "item_type": item_type,
            "display_name": _ITEM_META[item_type]["display_name"],
            "description": _ITEM_META[item_type]["description"],
        }
        for item_type in CLONE_ITEMS
    ]
    return {
        "ok": True,
        "data": {
            "cloneable": items,
            "non_cloneable": NON_CLONE_ITEMS,
        },
    }


@router.get(
    "/{store_id}/clone-preview",
    summary="克隆预览",
    description="查看源门店各配置项的数据量和样例，帮助用户决定克隆哪些配置。",
)
async def clone_preview(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> dict:
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = get_clone_preview(store_id, tenant_id)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/clone",
    summary="执行门店配置克隆",
    description=(
        "将 source_store 的选定配置项克隆到已存在的 target_store。\n\n"
        "- target_store 必须已通过其他接口创建（含基础信息）\n"
        "- source 与 target 必须属于同一 tenant\n"
        "- 每条配置记录生成新 UUID，不与源门店共享"
    ),
    status_code=201,
)
async def clone_store_api(
    req: CloneRequest,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant(x_tenant_id)
    try:
        task = await clone_store_config(
            source_store_id=req.source_store_id,
            target_store_id=req.target_store_id,
            selected_items=req.selected_items,
            tenant_id=tenant_id,
            created_by=req.created_by,
            db=db,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_dict = _task_to_dict(task)
    _TASK_STORE[task.id] = task_dict

    return {"ok": True, "data": task_dict}


@router.get(
    "/clone/{task_id}",
    summary="查询克隆任务状态",
    description="轮询克隆进度和结果。status: pending/running/completed/failed",
)
async def get_clone_task(
    task_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> dict:
    task_dict = _TASK_STORE.get(task_id)
    if task_dict is None:
        raise HTTPException(status_code=404, detail=f"克隆任务 {task_id} 不存在")

    tenant_id = _get_tenant(x_tenant_id)
    if task_dict["tenant_id"] != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问此克隆任务")

    return {"ok": True, "data": task_dict}


@router.post(
    "/setup",
    summary="新门店一体化创建",
    description=(
        "一步完成：\n"
        "1. 创建新门店基础信息（store_name/brand_id/address）\n"
        "2. 如提供 clone_from_store_id，执行配置克隆\n\n"
        "clone_items 为 null 时克隆全部配置；传空列表则不克隆。\n"
        "返回新门店 ID 和克隆任务 ID。"
    ),
    status_code=201,
)
async def setup_store(
    req: StoreSetupRequest,
    x_tenant_id: Optional[str] = Header(None),
) -> dict:
    tenant_id = _get_tenant(x_tenant_id)
    try:
        result = setup_new_store(
            store_name=req.store_name,
            brand_id=req.brand_id,
            address=req.address,
            tenant_id=tenant_id,
            clone_from_store_id=req.clone_from_store_id,
            clone_items=req.clone_items,
            created_by=req.created_by,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task = result.get("clone_task")
    task_id: Optional[str] = None
    if task is not None:
        task_dict = _task_to_dict(task)
        _TASK_STORE[task.id] = task_dict
        task_id = task.id

    return {
        "ok": True,
        "data": {
            "store_id": result["store_id"],
            "store_name": result["store_name"],
            "store_code": result["store_code"],
            "clone_task_id": task_id,
            "clone_status": task.status if task else None,
        },
    }
