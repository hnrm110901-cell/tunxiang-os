"""加盟门店复制服务

从模板门店（总部标杆门店）将以下配置批量复制到新加盟门店：
  1. 菜单结构/定价/菜品分类 — 调用 tx-menu 内部 API
  2. KDS档口配置（dish_dept_mappings）— 调用 tx-menu / tx-ops 内部 API
  3. 销售渠道配置（sales_channels）— 调用 tx-trade / tx-ops 内部 API

异步执行，调用方在 franchise_stores.clone_status 追踪进度：
  pending → cloning → completed | failed

安全约束：
  - source / target 必须属于同一 tenant_id
  - 不复制运营数据（订单/库存/流水/打卡）
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 内部服务地址（从环境变量读取，单元测试可覆盖） ──────────────────────────
_MENU_BASE = os.environ.get("TX_MENU_BASE_URL", "http://tx-menu:8002")
_TRADE_BASE = os.environ.get("TX_TRADE_BASE_URL", "http://tx-trade:8001")
_OPS_BASE = os.environ.get("TX_OPS_BASE_URL", "http://tx-ops:8005")

_HTTP_TIMEOUT = 30.0  # 秒


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  公共入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def clone_store(
    db: AsyncSession,
    tenant_id: str,
    template_store_id: str,
    target_store_id: str,
) -> dict[str, Any]:
    """从模板门店复制配置到目标门店。

    Args:
        db:               AsyncSession，用于更新 franchise_stores.clone_status
        tenant_id:        租户 UUID 字符串
        template_store_id: 模板门店 ID（复制源）
        target_store_id:  新加盟门店 ID（复制目标）

    Returns:
        {
            "status": "completed" | "failed",
            "cloned_items": {
                "menu_categories": int,
                "menu_items": int,
                "kds_mappings": int,
                "sales_channels": int,
            },
            "errors": list[str]   # 非致命错误列表
        }
    """
    log = logger.bind(
        tenant_id=tenant_id,
        template_store_id=template_store_id,
        target_store_id=target_store_id,
    )
    log.info("franchise_clone.start")

    cloned_items: dict[str, int] = {
        "menu_categories": 0,
        "menu_items": 0,
        "kds_mappings": 0,
        "sales_channels": 0,
    }
    errors: list[str] = []

    headers = {
        "X-Tenant-ID": tenant_id,
        "X-Internal-Call": "1",
    }

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        # ── 1. 复制菜单（分类 + 菜品 + 价格） ──────────────────────────
        try:
            resp = await client.post(
                f"{_MENU_BASE}/api/v1/menu/stores/{target_store_id}/clone",
                json={"template_store_id": template_store_id},
                headers=headers,
            )
            if resp.status_code == 200:
                body = resp.json()
                cloned_items["menu_categories"] = body.get("data", {}).get("categories_cloned", 0)
                cloned_items["menu_items"] = body.get("data", {}).get("items_cloned", 0)
                log.info(
                    "franchise_clone.menu_done",
                    categories=cloned_items["menu_categories"],
                    items=cloned_items["menu_items"],
                )
            else:
                err = f"tx-menu clone returned {resp.status_code}: {resp.text[:200]}"
                errors.append(err)
                log.warning("franchise_clone.menu_failed", detail=err)
        except httpx.HTTPError as exc:
            err = f"tx-menu HTTP error: {exc}"
            errors.append(err)
            log.warning("franchise_clone.menu_http_error", exc=str(exc))

        # ── 2. 复制 KDS 档口配置（dish_dept_mappings） ──────────────────
        try:
            resp = await client.post(
                f"{_OPS_BASE}/api/v1/ops/stores/{target_store_id}/kds/clone",
                json={"template_store_id": template_store_id},
                headers=headers,
            )
            if resp.status_code == 200:
                body = resp.json()
                cloned_items["kds_mappings"] = body.get("data", {}).get("mappings_cloned", 0)
                log.info(
                    "franchise_clone.kds_done",
                    mappings=cloned_items["kds_mappings"],
                )
            else:
                err = f"tx-ops kds clone returned {resp.status_code}: {resp.text[:200]}"
                errors.append(err)
                log.warning("franchise_clone.kds_failed", detail=err)
        except httpx.HTTPError as exc:
            err = f"tx-ops kds HTTP error: {exc}"
            errors.append(err)
            log.warning("franchise_clone.kds_http_error", exc=str(exc))

        # ── 3. 复制销售渠道配置（sales_channels） ───────────────────────
        try:
            resp = await client.post(
                f"{_TRADE_BASE}/api/v1/trade/stores/{target_store_id}/channels/clone",
                json={"template_store_id": template_store_id},
                headers=headers,
            )
            if resp.status_code == 200:
                body = resp.json()
                cloned_items["sales_channels"] = body.get("data", {}).get("channels_cloned", 0)
                log.info(
                    "franchise_clone.channels_done",
                    channels=cloned_items["sales_channels"],
                )
            else:
                err = f"tx-trade channels clone returned {resp.status_code}: {resp.text[:200]}"
                errors.append(err)
                log.warning("franchise_clone.channels_failed", detail=err)
        except httpx.HTTPError as exc:
            err = f"tx-trade channels HTTP error: {exc}"
            errors.append(err)
            log.warning("franchise_clone.channels_http_error", exc=str(exc))

    # 全部下游报错 → 整体失败；部分报错仍视为完成（非致命）
    final_status = "failed" if len(errors) == 3 else "completed"

    log.info(
        "franchise_clone.finish",
        status=final_status,
        cloned_items=cloned_items,
        error_count=len(errors),
    )

    return {
        "status": final_status,
        "cloned_items": cloned_items,
        "errors": errors,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助：更新 franchise_stores.clone_status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _update_clone_status(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    clone_status: str,
) -> None:
    """更新 franchise_stores.clone_status，顺带刷新 updated_at。"""
    await db.execute(
        text("""
            UPDATE franchise_stores
               SET clone_status = :clone_status,
                   updated_at   = now()
             WHERE store_id  = :store_id
               AND tenant_id = :tenant_id
        """),
        {"clone_status": clone_status, "store_id": store_id, "tenant_id": tenant_id},
    )
    await db.commit()
