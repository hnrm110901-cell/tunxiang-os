"""上海明厨亮灶智慧监管平台对接适配器。

上海市要求餐饮企业接入明厨亮灶系统，上报设备信息和视频流。
当前为 Mock 模式。
"""

import uuid
from typing import Any

import structlog

from ..base_city_adapter import SubmissionResult
from ..base_domain_adapter import BaseDomainAdapter

logger = structlog.get_logger(__name__)

# 屯象统一字段 → 上海明厨亮灶字段映射
_KITCHEN_FIELD_MAP: dict[str, str] = {
    "device_id": "deviceCode",
    "device_name": "deviceName",
    "device_type": "deviceType",
    "video_stream_url": "streamUrl",
    "video_protocol": "streamProtocol",
    "location": "installLocation",
    "store_name": "shopName",
    "store_license": "shopLicense",
    "status": "deviceStatus",
    "install_date": "installDate",
    "resolution": "resolution",
}


class ShanghaiKitchenAdapter(BaseDomainAdapter):
    """上海明厨亮灶适配器。

    负责上报设备信息和视频流 URL 到上海明厨亮灶智慧监管平台。
    """

    domain: str = "kitchen"
    platform_name: str = "上海明厨亮灶智慧监管平台"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.platform_api_base = config.get("shanghai_kitchen_api_base", "")
        logger.info(
            "shanghai_kitchen_init",
            api_base=self.platform_api_base or "(未配置)",
        )

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """将屯象设备/视频流数据映射到上海明厨亮灶平台格式。"""
        normalized: dict[str, Any] = {}

        for tx_field, api_field in _KITCHEN_FIELD_MAP.items():
            if tx_field in data:
                normalized[api_field] = data[tx_field]

        unmapped = {k: v for k, v in data.items() if k not in _KITCHEN_FIELD_MAP}
        if unmapped:
            normalized["_extra"] = unmapped

        logger.info(
            "shanghai_kitchen_normalize",
            input_keys=list(data.keys()),
            output_keys=list(normalized.keys()),
        )

        return normalized

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        """提交设备/视频流信息到上海明厨亮灶平台。Mock 模式。"""
        mock_ref = f"SHKITCHEN-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "shanghai_kitchen_submit_mock",
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 上海明厨亮灶数据已记录，未实际上报",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        """从上海明厨亮灶平台拉取通知。Mock 模式。"""
        logger.info(
            "shanghai_kitchen_pull_mock",
            platform=self.platform_name,
            filters=filters,
        )
        return []
