"""沪食安追溯平台对接适配器。

沪食安(Shanghai Food Safety Traceability)是上海市食品安全追溯管理平台，
要求入驻餐饮企业定期上报食材进货信息。

当前为 Mock 模式，预留了真实 HTTP 调用位置。
"""

import uuid
from typing import Any

import structlog

from ..base_city_adapter import SubmissionResult
from ..base_domain_adapter import BaseDomainAdapter

logger = structlog.get_logger(__name__)

# 屯象统一字段 → 沪食安API字段映射
_TRACE_FIELD_MAP: dict[str, str] = {
    "product_name": "productName",
    "batch_no": "batchCode",
    "supplier_name": "supplierName",
    "supplier_license": "supplierLicense",
    "quantity": "quantity",
    "unit": "unit",
    "production_date": "productionDate",
    "expiry_date": "expiryDate",
    "inbound_date": "inboundDate",
    "category": "categoryCode",
    "origin": "originPlace",
    "inspector": "inspectorName",
    "cert_no": "certNo",
    "cert_url": "certFileUrl",
    "remark": "remark",
}


class ShushianTraceAdapter(BaseDomainAdapter):
    """沪食安追溯适配器。

    负责将屯象 trace_inbound_record 数据转换为沪食安 API 格式并上报。
    """

    domain: str = "trace"
    platform_name: str = "沪食安"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.platform_api_base = config.get("shushian_api_base", "")
        logger.info(
            "shushian_trace_init",
            api_base=self.platform_api_base or "(未配置)",
        )

    async def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """将屯象 trace_inbound_record 字段映射到沪食安 API 格式。

        映射规则:
        - product_name → productName
        - batch_no → batchCode
        - supplier_name → supplierName
        - supplier_license → supplierLicense
        - quantity → quantity
        - unit → unit
        - production_date → productionDate
        - expiry_date → expiryDate
        - inbound_date → inboundDate
        - category → categoryCode
        - origin → originPlace
        - inspector → inspectorName
        - cert_no → certNo
        - cert_url → certFileUrl
        - remark → remark
        """
        normalized: dict[str, Any] = {}

        for tx_field, api_field in _TRACE_FIELD_MAP.items():
            if tx_field in data:
                normalized[api_field] = data[tx_field]

        # 保留未映射字段到 _extra 供调试
        unmapped = {k: v for k, v in data.items() if k not in _TRACE_FIELD_MAP}
        if unmapped:
            normalized["_extra"] = unmapped

        logger.info(
            "shushian_trace_normalize",
            input_keys=list(data.keys()),
            output_keys=list(normalized.keys()),
            unmapped_keys=list(unmapped.keys()) if unmapped else [],
        )

        return normalized

    async def submit(self, payload: dict[str, Any]) -> SubmissionResult:
        """提交追溯数据到沪食安平台。

        当前为 Mock 模式，仅记录日志。
        TODO: 接入真实 HTTP POST 调用。
        """
        mock_ref = f"SHUSHIAN-{uuid.uuid4().hex[:12].upper()}"

        logger.info(
            "shushian_trace_submit_mock",
            platform=self.platform_name,
            api_base=self.platform_api_base or "(未配置)",
            mock_ref=mock_ref,
            payload=payload,
        )

        # ---------------------------------------------------------------
        # 真实对接时替换以下代码:
        #
        # async with httpx.AsyncClient() as client:
        #     resp = await client.post(
        #         f"{self.platform_api_base}/api/trace/submit",
        #         json=payload,
        #         headers={"Authorization": f"Bearer {self.config['token']}"},
        #         timeout=30,
        #     )
        #     resp.raise_for_status()
        #     result = resp.json()
        #     return SubmissionResult(
        #         success=True,
        #         platform_ref=result.get("refNo", ""),
        #         raw_response=result,
        #     )
        # ---------------------------------------------------------------

        return SubmissionResult(
            success=True,
            platform_ref=mock_ref,
            message="Mock模式: 沪食安追溯数据已记录，未实际上报",
            raw_response={"mock": True, "ref": mock_ref},
        )

    async def pull(self, **filters: Any) -> list[dict[str, Any]]:
        """从沪食安拉取追溯相关通知/检查结果。

        当前为 Mock 模式，返回空列表。
        """
        logger.info(
            "shushian_trace_pull_mock",
            platform=self.platform_name,
            filters=filters,
        )
        return []

    async def health_check(self) -> bool:
        """检查沪食安平台连通性。"""
        if not self.platform_api_base:
            logger.debug("shushian_trace_health_skip", reason="api_base未配置")
            return True  # Mock 模式视为健康

        # TODO: 真实健康检查
        # async with httpx.AsyncClient() as client:
        #     resp = await client.get(f"{self.platform_api_base}/health")
        #     return resp.status_code == 200
        return True
