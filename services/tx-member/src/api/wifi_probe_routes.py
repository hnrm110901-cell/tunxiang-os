"""WiFi探针 API — 4端点

/api/v1/member/wifi
- POST /probe          接收门店WiFi AP的探针数据（批量MAC地址）
- GET  /visits/{sid}   按小时的访问热力图
- POST /match          触发未匹配访问的身份解析
- GET  /coverage       各门店的身份识别覆盖率
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from services.identity_resolver import IdentityResolver
from services.wifi_probe_service import WiFiProbeService

router = APIRouter(prefix="/api/v1/member/wifi", tags=["wifi-probe"])

_probe_svc = WiFiProbeService()
_resolver = IdentityResolver()


# ── Request / Response Models ─────────────────────────────────────────────────


class ProbeItem(BaseModel):
    mac_address: str = Field(..., max_length=64)
    signal_strength: Optional[int] = None


class ProbeReq(BaseModel):
    store_id: str
    probes: list[ProbeItem] = Field(..., min_length=1, max_length=500)


class MatchReq(BaseModel):
    store_id: Optional[str] = None


# ── 内存存储（对齐项目现有模式，生产走DB） ──────────────────────────────────


_visits_store: list[dict] = []


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/probe")
async def receive_probe(
    body: ProbeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """接收门店WiFi AP上报的探针数据（批量）"""
    results = []
    for p in body.probes:
        # 内存模式：记录到内存，生产环境替换为DB
        from services.wifi_probe_service import _detect_vendor, _hash_mac

        mac_hash = _hash_mac(p.mac_address)
        vendor = _detect_vendor(p.mac_address)
        record = {
            "tenant_id": x_tenant_id,
            "store_id": body.store_id,
            "mac_hash": mac_hash,
            "device_vendor": vendor,
            "signal_strength": p.signal_strength,
            "is_new_visitor": not any(
                v["mac_hash"] == mac_hash and v["store_id"] == body.store_id for v in _visits_store
            ),
        }
        _visits_store.append(record)
        results.append(
            {
                "mac_hash": mac_hash[:12] + "...",
                "vendor": vendor,
                "is_new": record["is_new_visitor"],
            }
        )
    return {
        "ok": True,
        "data": {"ingested": len(results), "items": results},
    }


@router.get("/visits/{store_id}")
async def get_visit_heatmap(
    store_id: str,
    date_from: Optional[str] = Query(None, description="ISO date, e.g. 2026-04-20"),
    date_to: Optional[str] = Query(None, description="ISO date, e.g. 2026-04-25"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取门店按小时的访问热力图"""
    # 内存模式：返回汇总
    store_visits = [v for v in _visits_store if v["tenant_id"] == x_tenant_id and v["store_id"] == store_id]
    # 简化：按总数返回
    heatmap = [{"hour": h, "visit_count": 0, "unique_visitors": 0} for h in range(24)]
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total_records": len(store_visits),
            "heatmap": heatmap,
        },
    }


@router.post("/match")
async def trigger_match(
    body: MatchReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """触发WiFi访问记录的身份解析"""
    # 内存模式：模拟批量匹配
    unmatched = [v for v in _visits_store if v["tenant_id"] == x_tenant_id and v.get("matched_customer_id") is None]
    return {
        "ok": True,
        "data": {
            "source": "wifi",
            "total": len(unmatched),
            "resolved": 0,
            "unmatched": len(unmatched),
        },
    }


@router.get("/coverage")
async def get_coverage(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """各门店的WiFi身份识别覆盖率"""
    tenant_visits = [v for v in _visits_store if v["tenant_id"] == x_tenant_id]
    total = len(tenant_visits)
    matched = sum(1 for v in tenant_visits if v.get("matched_customer_id"))
    return {
        "ok": True,
        "data": {
            "total_visits": total,
            "matched": matched,
            "match_rate": round(matched / max(total, 1) * 100, 1),
        },
    }
