"""浙食链追溯平台对接适配器。

浙食链是浙江省食品安全追溯闭环管理系统，
要求食品生产经营者上报进货查验记录。当前为 Mock 模式。
"""

import uuid
from typing import Any

import structlog

from ..base_city_adapter import SubmissionResult
from ..base_domain_adapter import BaseDomainAdapter

logger = structlog.get_logger(__name__)

# 屯象统一字段 → 浙食链字段映射
_ZHESHILIAN_FIELD_MAP: dict[str, str] = {
    "product_name": "foodName",
    "batch_no": "batchNo",
    "supplier_name": "supplierName",
    "supplier_license": "supplierCertNo",
    "quantity": "qty",
    "unit": "qtyUnit",
    "production_date": "prodDate",
    "expiry_date": "expDate",
    "inbound_date": "purchaseDate",
    "category": "foodCategory",
    "origin": "origin",
    "cert_no": "checkCertNo",
}


class ZheshilianTraceAdapter(BaseDomainAdapter):
    """浙食链追溯适配器。"""

    domain: str = "trace"
    platform_name: str = "浙食链"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.platform_api_base = config.get("zheshilian_api_base", "")
        logger.info(
            "zheshilian_trace_init",
            api_base=self.platform_api_base or "(未配置)",
        )

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """将屯象追溯数据映射到浙食链格式。"""
        normalized: dict[str, Any] = {}

        for tx_field, api_field in _ZHESHILIAN_FIELD_MAP.items():
            if tx_field in data:
                normalized[api_field] = data[tx_field]

        unmapped = {k: v for k, v in data.items() if k not in _ZHESHILIAN_FIELD_MAP}
        if unmapped:
            normalized["_extra"] = unmapped

        logger.info(
            "zheshilian_trace_normalize",
            input_keys=list(data.keys()),
            output_keys=list(normalized.keys()),
        )

        return normalized

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        """提交到浙食链平台。Mock 模式。"""
        mock_ref = f"ZHESHILIAN-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "zheshilian_trace_submit_mock",
            platform=self.platform_name,
            mock_ref=mock_ref,
            payload=payload,
        )

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 浙食链追溯数据已记录，未实际上报",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        """从浙食链拉取通知。Mock 模式。"""
        logger.info(
            "zheshilian_trace_pull_mock",
            platform=self.platform_name,
            filters=filters,
        )
        return []
