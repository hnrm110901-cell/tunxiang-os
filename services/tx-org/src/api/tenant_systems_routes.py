"""租户多系统配置管理 API

端点（3个）：
  GET  /api/v1/org/tenant/systems-config
       获取当前租户的四系统配置；app_secret / appkey / api_key 脱敏展示（前4位+***）。

  PUT  /api/v1/org/tenant/systems-config
       全量替换 systems_config（凭证由请求体提供，存入 DB，绝不记录日志）。

  POST /api/v1/org/tenant/systems-config/test/{system_name}
       测试指定系统连通性（调用对应适配器的 health_check / ping 接口）。
       system_name 枚举：pinzhi | aoqiwei_crm | aoqiwei_supply | yiding

响应格式：{"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
凭证绝不硬编码，全部经由 DB 读取。
"""

from __future__ import annotations

import os
import sys
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 将 shared 目录加入路径（兼容不同启动方式）
_SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SERVICE_DIR))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.adapters.config.multi_system_config import (
    AoqiweiCrmConfig,
    AoqiweiSupplyConfig,
    PinzhiConfig,
    TenantSystemsConfig,
    YidingConfig,
)
from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["tenant-systems"])

# ── 凭证字段名（脱敏处理目标） ───────────────────────────────────────────────
_SECRET_FIELDS = {"app_secret", "appkey", "api_key", "token", "secret"}

# ── 支持的系统名枚举 ──────────────────────────────────────────────────────────
_VALID_SYSTEMS = {"pinzhi", "aoqiwei_crm", "aoqiwei_supply", "yiding"}


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _mask_secret(value: str) -> str:
    """凭证脱敏：前4位明文 + ***，空值返回空字符串。"""
    if not value:
        return ""
    return value[:4] + "***"


def _mask_config(config: dict) -> dict:
    """递归脱敏配置 dict 中的凭证字段。"""
    result: dict = {}
    for k, v in config.items():
        if isinstance(v, dict):
            result[k] = _mask_config(v)
        elif isinstance(v, str) and k in _SECRET_FIELDS:
            result[k] = _mask_secret(v)
        else:
            result[k] = v
    return result


async def _load_systems_config(db: AsyncSession, tenant_id: str) -> dict:
    """从 DB 加载租户的 systems_config JSONB，返回原始 dict。"""
    row = await db.execute(
        text("SELECT systems_config FROM tenants WHERE id = :tid::uuid LIMIT 1").bindparams(tid=tenant_id)
    )
    record = row.fetchone()
    if record is None:
        raise HTTPException(status_code=404, detail=f"租户 {tenant_id} 不存在")
    cfg = record[0]
    return cfg if isinstance(cfg, dict) else {}


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────


class UpdateSystemsConfigRequest(BaseModel):
    """全量替换 systems_config 请求体。"""

    systems_config: TenantSystemsConfig


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/api/v1/org/tenant/systems-config")
async def get_systems_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前租户的四系统配置（凭证脱敏）。

    凭证字段（app_secret / appkey / api_key 等）仅显示前4位 + ***。
    """
    tenant_id = _get_tenant_id(request)
    log.info("tenant_systems_config.get", tenant_id=tenant_id)

    raw = await _load_systems_config(db, tenant_id)
    masked = _mask_config(raw)
    return _ok({"tenant_id": tenant_id, "systems_config": masked})


@router.put("/api/v1/org/tenant/systems-config")
async def update_systems_config(
    request: Request,
    body: UpdateSystemsConfigRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量替换租户的 systems_config。

    凭证仅存数据库，不记录日志，不返回原文。
    更新后响应中凭证同样脱敏展示。
    """
    tenant_id = _get_tenant_id(request)

    # 验证租户存在
    await _load_systems_config(db, tenant_id)

    # 序列化为 dict（保留 None 子系统，使 JSONB 记录完整骨架）
    import json

    new_cfg = body.systems_config.model_dump(exclude_none=False)

    await db.execute(
        text(
            """
            UPDATE tenants
               SET systems_config = :cfg::jsonb,
                   updated_at     = NOW()
             WHERE id = :tid::uuid
            """
        ).bindparams(cfg=json.dumps(new_cfg, ensure_ascii=False), tid=tenant_id)
    )
    await db.commit()

    log.info("tenant_systems_config.updated", tenant_id=tenant_id)
    masked = _mask_config(new_cfg)
    return _ok({"tenant_id": tenant_id, "systems_config": masked})


@router.post("/api/v1/org/tenant/systems-config/test/{system_name}")
async def test_system_connectivity(
    request: Request,
    system_name: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """测试指定系统的连通性。

    从 DB 读取租户配置，实例化对应适配器，调用 health_check / ping。
    system_name: pinzhi | aoqiwei_crm | aoqiwei_supply | yiding
    """
    tenant_id = _get_tenant_id(request)

    if system_name not in _VALID_SYSTEMS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的系统名 {system_name!r}，有效值：{sorted(_VALID_SYSTEMS)}",
        )

    log.info("tenant_systems_config.test", tenant_id=tenant_id, system=system_name)

    raw = await _load_systems_config(db, tenant_id)
    sys_raw = raw.get(system_name)

    if not sys_raw:
        return _err(f"租户未配置系统 {system_name}", code=422)

    # 根据系统名分发测试逻辑
    if system_name == "pinzhi":
        return await _test_pinzhi(tenant_id, sys_raw)
    elif system_name == "aoqiwei_crm":
        return await _test_aoqiwei_crm(tenant_id, sys_raw)
    elif system_name == "aoqiwei_supply":
        return await _test_aoqiwei_supply(tenant_id, sys_raw)
    elif system_name == "yiding":
        return await _test_yiding(tenant_id, sys_raw)

    # 不可达，防御性返回
    return _err("未知系统", code=500)


# ── 各系统连通性测试实现 ───────────────────────────────────────────────────────


async def _test_pinzhi(tenant_id: str, cfg: dict) -> dict:
    """品智：调用 get_store_info 验证 token + base_url。"""
    from shared.adapters.pinzhi.src.adapter import PinzhiAdapter

    cfg_parsed = PinzhiConfig(**cfg)
    if not cfg_parsed.base_url or not cfg_parsed.app_secret:
        return _err("品智 base_url 或 app_secret 未配置", code=422)

    adapter = PinzhiAdapter(
        {
            "base_url": cfg_parsed.base_url,
            "token": cfg_parsed.app_secret,
            "timeout": 10,
            "retry_times": 1,
        }
    )
    try:
        stores = await adapter.get_store_info()
        return _ok(
            {
                "system": "pinzhi",
                "ok": True,
                "message": f"连通成功，返回 {len(stores)} 个门店",
            }
        )
    except (ValueError, RuntimeError) as exc:
        return _ok({"system": "pinzhi", "ok": False, "message": str(exc)})
    finally:
        await adapter.close()


async def _test_aoqiwei_crm(tenant_id: str, cfg: dict) -> dict:
    """奥琦玮CRM：构造最小请求验证 appid/appkey 签名是否有效。"""
    from shared.adapters.aoqiwei.src.crm_adapter import AoqiweiCrmAdapter

    cfg_parsed = AoqiweiCrmConfig(**cfg)
    if not cfg_parsed.appid or not cfg_parsed.appkey:
        return _err("奥琦玮CRM appid 或 appkey 未配置", code=422)

    adapter = AoqiweiCrmAdapter(
        {
            "base_url": cfg_parsed.api_url,
            "appid": cfg_parsed.appid,
            "appkey": cfg_parsed.appkey,
            "timeout": 10,
            "retry_times": 1,
        }
    )
    try:
        # get_member_info 需要参数，使用一个必定不存在的号码触发业务 400，
        # 只要不是网络/签名错误即视为连通成功。
        await adapter.get_member_info(mobile="10000000000")
        return _ok({"system": "aoqiwei_crm", "ok": True, "message": "连通成功"})
    except RuntimeError as exc:
        # RuntimeError = 网络/超时类错误，视为连通失败
        return _ok({"system": "aoqiwei_crm", "ok": False, "message": str(exc)})
    except (ValueError, Exception) as exc:  # noqa: BLE001 — 业务错误亦视为通信成功
        # 业务层错误（errcode != 0）说明已成功通信
        msg = str(exc)
        if "errcode" in msg or "errmsg" in msg or "会员" in msg:
            return _ok(
                {
                    "system": "aoqiwei_crm",
                    "ok": True,
                    "message": "连通成功（业务响应正常）",
                }
            )
        return _ok({"system": "aoqiwei_crm", "ok": False, "message": msg})
    finally:
        await adapter.aclose()


async def _test_aoqiwei_supply(tenant_id: str, cfg: dict) -> dict:
    """奥琦玮供应链：调用 query_shops 验证 appkey/appsecret。"""
    from shared.adapters.aoqiwei.src.adapter import AoqiweiAdapter

    cfg_parsed = AoqiweiSupplyConfig(**cfg)
    if not cfg_parsed.app_id or not cfg_parsed.app_secret:
        return _err("奥琦玮供应链 app_id 或 app_secret 未配置", code=422)

    adapter = AoqiweiAdapter(
        {
            "base_url": cfg_parsed.api_url,
            "app_key": cfg_parsed.app_id,
            "app_secret": cfg_parsed.app_secret,
            "timeout": 10,
            "retry_times": 1,
        }
    )
    try:
        shops = await adapter.query_shops()
        return _ok(
            {
                "system": "aoqiwei_supply",
                "ok": True,
                "message": f"连通成功，返回 {len(shops)} 个门店",
            }
        )
    except RuntimeError as exc:
        return _ok({"system": "aoqiwei_supply", "ok": False, "message": str(exc)})
    finally:
        await adapter.aclose()


async def _test_yiding(tenant_id: str, cfg: dict) -> dict:
    """易订：调用 health_check (ping) 验证 appid/secret。"""
    from shared.adapters.yiding.src.adapter import YiDingAdapter

    cfg_parsed = YidingConfig(**cfg)
    if not cfg_parsed.api_key:
        return _err("易订 api_key (secret) 未配置", code=422)

    # YiDingConfig TypedDict 键: base_url, appid, secret, hotel_id
    # 注意：api_key 字段对应适配器内部的 secret 参数
    yiding_cfg: dict = {
        "base_url": cfg_parsed.base_url,
        "appid": "",  # appid 存于 yiding.app_id（未来可扩展）
        "secret": cfg_parsed.api_key,
        "hotel_id": cfg_parsed.hotel_id,
        "cache_ttl": 300,
    }
    adapter = YiDingAdapter(yiding_cfg)
    try:
        ok = await adapter.health_check()
        return _ok(
            {
                "system": "yiding",
                "ok": ok,
                "message": "连通成功" if ok else "连通失败，请检查 api_key",
            }
        )
    finally:
        await adapter.close()
