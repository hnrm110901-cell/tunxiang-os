"""活动 ROI 预测 HTTP 路由（D3b）

POST /api/v1/agents/activity-roi/predict

鉴权策略（与 tx-brain 现有约定保持一致）：
- 必须带 ``X-Tenant-ID`` 请求头
- 必须带 ``Authorization: Bearer ...`` 请求头（gateway 已验签，本服务只校验存在性）
- body 内的 tenant_id 必须与 X-Tenant-ID 完全一致（防跨租户写）

依赖注入采用 lazy import，便于测试用 monkeypatch / FastAPI dependency_overrides 替换。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError

from ..agents.activity_roi.pipeline import ActivityROIPipeline
from ..agents.activity_roi.schemas import (
    ActivityROIRequest,
    ActivityROIResponse,
    InsufficientHistoricalDataError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents/activity-roi", tags=["activity-roi"])


# ─── 鉴权依赖 ────────────────────────────────────────────────────────────────


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id.strip()


def _require_bearer(authorization: str = Header(..., alias="Authorization")) -> str:
    """gateway 已验证 JWT 签名，这里只检查 bearer 存在。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    return authorization


# ─── Pipeline 注入（lazy） ───────────────────────────────────────────────────


def _get_pipeline() -> ActivityROIPipeline:  # pragma: no cover -- 实际由 override 替换
    """生产入口：从 model_router_singleton + 真实 GMV repo 构造。

    当前阶段 model_router_singleton / 真实仓储未就绪，本函数直接抛 503。
    测试用 ``app.dependency_overrides[_get_pipeline] = lambda: fake_pipeline`` 注入。
    """
    raise HTTPException(
        status_code=503,
        detail=(
            "Activity ROI pipeline 未配置注入：请在应用启动时通过 "
            "app.dependency_overrides[_get_pipeline] 注入实例。"
            "TODO: 等 model_router_singleton + GMV repository 就绪后接入"
        ),
    )


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/predict", response_model=ActivityROIResponse)
async def predict_activity_roi(
    body: dict[str, Any],
    tenant_id: str = Depends(_require_tenant),
    _: str = Depends(_require_bearer),
    pipeline: ActivityROIPipeline = Depends(_get_pipeline),
) -> ActivityROIResponse:
    """预测一个未启动的营销活动 ROI。

    Body 即 ``ActivityROIRequest`` 的 JSON 形式（含 ``tenant_id``）。
    Body 中的 ``tenant_id`` 必须与 ``X-Tenant-ID`` 一致。
    """
    try:
        req = ActivityROIRequest.model_validate(body)
    except ValidationError as exc:
        logger.info("activity_roi_request_invalid: tenant=%s err=%s", tenant_id, exc)
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if str(req.tenant_id) != str(tenant_id):
        logger.warning(
            "activity_roi_tenant_mismatch: header=%s body=%s",
            tenant_id,
            req.tenant_id,
        )
        raise HTTPException(status_code=403, detail="tenant_id mismatch")

    try:
        return await pipeline.predict(req)
    except InsufficientHistoricalDataError as exc:
        logger.info("activity_roi_insufficient_history: tenant=%s err=%s", tenant_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, ValueError, TimeoutError) as exc:
        logger.error("activity_roi_pipeline_failed: tenant=%s err=%s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="activity ROI prediction failed") from exc
