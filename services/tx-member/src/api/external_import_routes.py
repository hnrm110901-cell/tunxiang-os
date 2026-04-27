"""外部订单导入 API — 5端点

/api/v1/member/external
- POST /import/meituan   导入美团订单（JSON数组）
- POST /import/eleme     导入饿了么订单
- GET  /imports          列出近期导入（分页，可按source过滤）
- GET  /coverage         各来源的身份匹配率
- POST /resolve          触发批量身份解析
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from services.identity_resolver import IdentityResolver

router = APIRouter(prefix="/api/v1/member/external", tags=["external-import"])

_resolver = IdentityResolver()


# ── Request / Response Models ─────────────────────────────────────────────────


class OrderItem(BaseModel):
    name: str
    quantity: int = 1
    price_fen: int = 0


class ExternalOrderReq(BaseModel):
    external_order_id: str = Field(..., max_length=100)
    store_id: str
    customer_phone: Optional[str] = None
    order_total_fen: int = 0
    items: list[OrderItem] = Field(default_factory=list)
    rating: Optional[float] = Field(None, ge=0, le=5)
    review_text: Optional[str] = None
    ordered_at: str = Field(..., description="ISO datetime")


class ResolveReq(BaseModel):
    source: Optional[str] = Field(None, description="wifi|external")


# ── 内存存储（对齐项目现有模式，生产走DB） ──────────────────────────────────


_imports_store: list[dict] = []


def _hash_phone(phone: str) -> str:
    """SHA-256 哈希手机号"""
    return hashlib.sha256(phone.strip().encode()).hexdigest()


def _import_orders(
    tenant_id: str,
    source: str,
    orders: list[ExternalOrderReq],
) -> dict:
    """通用导入逻辑：去重 + 写入"""
    imported = 0
    skipped = 0
    for o in orders:
        # 去重：同 tenant + source + external_order_id
        exists = any(
            r["tenant_id"] == tenant_id and r["source"] == source and r["external_order_id"] == o.external_order_id
            for r in _imports_store
        )
        if exists:
            skipped += 1
            continue

        phone_hash = _hash_phone(o.customer_phone) if o.customer_phone else None
        record = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "source": source,
            "external_order_id": o.external_order_id,
            "store_id": o.store_id,
            "customer_phone_hash": phone_hash,
            "matched_customer_id": None,
            "match_confidence": 0,
            "order_total_fen": o.order_total_fen,
            "items": json.dumps([i.model_dump() for i in o.items]),
            "item_count": len(o.items),
            "rating": o.rating,
            "review_text": o.review_text,
            "ordered_at": o.ordered_at,
        }
        _imports_store.append(record)
        imported += 1

    return {"imported": imported, "skipped_duplicates": skipped, "source": source}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/import/meituan")
async def import_meituan(
    orders: list[ExternalOrderReq],
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """导入美团订单"""
    result = _import_orders(x_tenant_id, "meituan", orders)
    return {"ok": True, "data": result}


@router.post("/import/eleme")
async def import_eleme(
    orders: list[ExternalOrderReq],
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """导入饿了么订单"""
    result = _import_orders(x_tenant_id, "eleme", orders)
    return {"ok": True, "data": result}


@router.get("/imports")
async def list_imports(
    source: Optional[str] = Query(None, description="meituan|eleme|dianping|douyin|xiaohongshu"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """列出近期导入记录（分页，可按来源过滤）"""
    filtered = [r for r in _imports_store if r["tenant_id"] == x_tenant_id]
    if source:
        filtered = [r for r in filtered if r["source"] == source]

    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    items = filtered[start:end]

    # 脱敏：不返回 phone_hash 全文
    safe_items = []
    for item in items:
        safe = {k: v for k, v in item.items() if k != "customer_phone_hash"}
        safe["has_phone"] = item.get("customer_phone_hash") is not None
        safe_items.append(safe)

    return {
        "ok": True,
        "data": {"items": safe_items, "total": total, "page": page, "size": size},
    }


@router.get("/coverage")
async def get_coverage(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """各来源的身份匹配率"""
    tenant_imports = [r for r in _imports_store if r["tenant_id"] == x_tenant_id]
    sources: dict[str, dict] = {}
    for r in tenant_imports:
        src = r["source"]
        if src not in sources:
            sources[src] = {"total": 0, "matched": 0}
        sources[src]["total"] += 1
        if r.get("matched_customer_id"):
            sources[src]["matched"] += 1

    result = {}
    for src, stats in sources.items():
        result[src] = {
            "total": stats["total"],
            "matched": stats["matched"],
            "match_rate": round(stats["matched"] / max(stats["total"], 1) * 100, 1),
        }
    return {"ok": True, "data": result}


@router.post("/resolve")
async def trigger_resolve(
    body: ResolveReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """触发批量身份解析"""
    source = body.source or "external"
    # 内存模式：模拟解析
    tenant_imports = [
        r for r in _imports_store if r["tenant_id"] == x_tenant_id and r.get("matched_customer_id") is None
    ]
    return {
        "ok": True,
        "data": {
            "source": source,
            "total": len(tenant_imports),
            "resolved": 0,
            "unmatched": len(tenant_imports),
        },
    }
