"""阳光餐饮平台对接适配器。

北京市「阳光餐饮」工程要求餐饮企业公开后厨视频，
接入统一的明厨亮灶监管体系。当前为 Mock 模式。
"""

import uuid
from typing import Any

import structlog

from ..base_city_adapter import SubmissionResult
from ..base_domain_adapter import BaseDomainAdapter

logger = structlog.get_logger(__name__)

# 屯象统一字段 → 阳光餐饮字段映射
_YANGGUANG_FIELD_MAP: dict[str, str] = {
    "device_id": "equipmentId",
    "device_name": "equipmentName",
    "video_stream_url": "videoUrl",
    "store_name": "restaurantName",
    "store_license": "licenseNo",
    "location": "installPosition",
    "status": "onlineStatus",
}


class YangguangKitchenAdapter(BaseDomainAdapter):
    """阳光餐饮适配器 — 北京明厨亮灶。"""

    domain: str = "kitchen"
    platform_name: str = "阳光餐饮"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.platform_api_base = config.get("yangguang_api_base", "")
        logger.info(
            "yangguang_kitchen_init",
            api_base=self.platform_api_base or "(未配置)",
        )

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """将屯象设备数据映射到阳光餐饮平台格式。"""
        normalized: dict[str, Any] = {}

        for tx_field, api_field in _YANGGUANG_FIELD_MAP.items():
            if tx_field in data:
                normalized[api_field] = data[tx_field]

        unmapped = {k: v for k, v in data.items() if k not in _YANGGUANG_FIELD_MAP}
        if unmapped:
            normalized["_extra"] = unmapped

        logger.info(
            "yangguang_kitchen_normalize",
            input_keys=list(data.keys()),
            output_keys=list(normalized.keys()),
        )

        return normalized

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        """提交到阳光餐饮平台。Mock 模式。"""
        mock_ref = f"YANGGUANG-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "yangguang_kitchen_submit_mock",
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 阳光餐饮数据已记录，未实际上报",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        """从阳光餐饮平台拉取通知。Mock 模式。"""
        logger.info(
            "yangguang_kitchen_pull_mock",
            platform=self.platform_name,
            filters=filters,
        )
        return []
