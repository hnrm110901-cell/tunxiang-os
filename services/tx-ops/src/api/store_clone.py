"""快速开店 — 配置克隆 API"""
from typing import List, Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ops", tags=["ops-clone"])

CloneItemType = Literal["dishes", "payments", "tables", "marketing", "kds", "roles"]


class StoreCloneRequest(BaseModel):
    source_store_id: str
    target_store_id: str
    clone_items: List[CloneItemType]


class CloneItemResult(BaseModel):
    item: str
    success: bool
    message: str
    count: int = 0


class StoreCloneResponse(BaseModel):
    source_store_id: str
    target_store_id: str
    results: List[CloneItemResult]
    total: int
    succeeded: int
    failed: int


# ---- 纯函数：模拟克隆逻辑（不依赖 DB） ----

_MOCK_COUNTS = {
    "dishes": 56,
    "payments": 4,
    "tables": 30,
    "marketing": 12,
    "kds": 3,
    "roles": 8,
}


def execute_clone(source_store_id: str, target_store_id: str, clone_items: List[str]) -> StoreCloneResponse:
    """纯函数版本：返回模拟克隆结果，不依赖数据库。"""
    if source_store_id == target_store_id:
        results = [
            CloneItemResult(item=item, success=False, message="源门店与目标门店不能相同", count=0)
            for item in clone_items
        ]
    else:
        results = [
            CloneItemResult(
                item=item,
                success=True,
                message=f"成功克隆 {_MOCK_COUNTS.get(item, 0)} 条{item}配置",
                count=_MOCK_COUNTS.get(item, 0),
            )
            for item in clone_items
        ]

    succeeded = sum(1 for r in results if r.success)
    return StoreCloneResponse(
        source_store_id=source_store_id,
        target_store_id=target_store_id,
        results=results,
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
    )


# ---- API 端点 ----

@router.post("/stores/clone")
async def clone_store_config(req: StoreCloneRequest):
    """快速开店：从源门店克隆配置到目标门店"""
    result = execute_clone(req.source_store_id, req.target_store_id, req.clone_items)
    return {"ok": True, "data": result.model_dump()}
