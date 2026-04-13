"""自然人电子税务局 API 封装（个税申报）

当前为 Mock 实现，真实对接需要：
  1. 企业税号 + 数字证书
  2. 自然人税收管理系统扣缴客户端 API
  3. 或对接第三方薪税通（如 51薪税通 / 用友薪福社）

环境变量:
  TAX_BUREAU_TAX_NO          -- 企业税号
  TAX_BUREAU_CERT_PATH       -- 数字证书路径
  TAX_BUREAU_ENV             -- sandbox / production (默认 sandbox)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TaxBureauSDK:
    """自然人电子税务局 API 封装（个税申报）-- 当前为 Mock 实现

    后续接入税务局客户端 API 或第三方薪税通时替换内部逻辑，接口保持不变。
    """

    def __init__(
        self,
        tax_no: str = "",
        cert_path: str = "",
        env: str = "sandbox",
    ) -> None:
        self.tax_no = tax_no or os.getenv("TAX_BUREAU_TAX_NO", "")
        self.cert_path = cert_path or os.getenv("TAX_BUREAU_CERT_PATH", "")
        self.env = env or os.getenv("TAX_BUREAU_ENV", "sandbox")
        self._is_mock = not self.tax_no

        if self._is_mock:
            logger.info(
                "tax_bureau_sdk.mock_mode",
                env=self.env,
                note="TAX_BUREAU_TAX_NO 未配置，使用 Mock 模式",
            )
        else:
            logger.info(
                "tax_bureau_sdk.initialized",
                env=self.env,
                tax_no=self.tax_no[:6] + "****",
            )

    async def submit_monthly_declaration(
        self,
        period: str,
        employees: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """提交月度个税申报

        Args:
            period: 申报月份，格式 "2026-04"
            employees: 员工申报数据列表
                [{name, id_card, income_fen, tax_fen, social_insurance_fen,
                  housing_fund_fen, special_deduction_fen}]

        Returns:
            {task_id, status, accepted_count, rejected: [{name, reason}]}
        """
        task_id = f"TAX-{uuid.uuid4().hex[:12].upper()}"

        if self._is_mock:
            logger.info(
                "tax_bureau_sdk.mock_submit",
                task_id=task_id,
                period=period,
                employee_count=len(employees),
            )
            return {
                "task_id": task_id,
                "status": "accepted",
                "accepted_count": len(employees),
                "rejected": [],
            }

        # TODO: 接入自然人税收管理系统 API
        raise NotImplementedError("真实税务局 API 尚未接入")

    async def query_declaration_status(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        """查询申报状态

        Returns:
            {task_id, status, message, updated_at}
            status: pending / processing / accepted / rejected / partial
        """
        if self._is_mock:
            logger.info(
                "tax_bureau_sdk.mock_query_status",
                task_id=task_id,
            )
            return {
                "task_id": task_id,
                "status": "accepted",
                "message": "申报已受理（Mock）",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        raise NotImplementedError("真实税务局 API 尚未接入")

    async def download_receipt(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        """下载申报回执

        Returns:
            {task_id, receipt_no, receipt_url, generated_at}
        """
        if self._is_mock:
            receipt_no = f"REC-{uuid.uuid4().hex[:8].upper()}"
            logger.info(
                "tax_bureau_sdk.mock_download_receipt",
                task_id=task_id,
                receipt_no=receipt_no,
            )
            return {
                "task_id": task_id,
                "receipt_no": receipt_no,
                "receipt_url": f"https://mock.tax.gov.cn/receipt/{receipt_no}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        raise NotImplementedError("真实税务局 API 尚未接入")

    async def get_employee_tax_record(
        self,
        id_card: str,
        year: int,
    ) -> dict[str, Any]:
        """查询员工年度累计个税记录

        Returns:
            {id_card, year, cumulative_income_fen, cumulative_tax_fen,
             cumulative_deduction_fen, months: [{month, income_fen, tax_fen}]}
        """
        if self._is_mock:
            logger.info(
                "tax_bureau_sdk.mock_get_employee_tax_record",
                id_card_suffix=id_card[-4:] if len(id_card) >= 4 else "****",
                year=year,
            )
            return {
                "id_card": id_card,
                "year": year,
                "cumulative_income_fen": 0,
                "cumulative_tax_fen": 0,
                "cumulative_deduction_fen": 0,
                "months": [],
            }

        raise NotImplementedError("真实税务局 API 尚未接入")

    async def revoke_declaration(
        self,
        task_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """撤销申报

        Returns:
            {task_id, status, message}
        """
        if self._is_mock:
            logger.info(
                "tax_bureau_sdk.mock_revoke",
                task_id=task_id,
                reason=reason,
            )
            return {
                "task_id": task_id,
                "status": "revoked",
                "message": f"申报已撤销（Mock）: {reason}",
            }

        raise NotImplementedError("真实税务局 API 尚未接入")
