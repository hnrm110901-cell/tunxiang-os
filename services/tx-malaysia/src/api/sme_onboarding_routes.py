"""马来西亚 SME 商家入驻 API 端点 — Phase 3 Sprint 3.6

整合 SSM 企业验证 + 政府补贴计费 + e-Invoice 注册三大流程，
为中小餐饮企业提供一站式入驻体验。

流程：
  1. SSM (Suruhanjaya Syarikat Malaysia) 企业注册验证
  2. 自动检查 MDEC / SME Corp 补贴资格
  3. LHDN MyInvois e-Invoice 注册
  4. 返回入驻状态与下一步指引

端点：
  - POST  /api/v1/my/onboarding/start    启动入驻流程
  - GET   /api/v1/my/onboarding/{id}     查询入驻状态
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/my/onboarding", tags=["my-onboarding"])


# ── 请求/响应模型 ───────────────────────────────────────────────────


class OnboardingStartRequest(BaseModel):
    """启动马来西亚入驻流程的请求参数"""

    business_name: str = Field(..., description="企业名称（与 SSM 注册一致）")
    registration_number: str = Field(
        ...,
        description="SSM 注册号（如 202001000001）",
        max_length=20,
    )
    business_type: str = Field(
        "sdn_bhd",
        description="企业类型（sdn_bhd / enterprise / sole_proprietorship）",
    )
    contact_email: str = Field(..., description="企业联系邮箱")
    contact_phone: str = Field(..., description="企业联系电话")
    business_address: str = Field(..., description="企业注册地址")
    owner_name: Optional[str] = Field(None, description="企业主姓名")
    owner_id_number: Optional[str] = Field(None, description="企业主身份证/护照号")


class OnboardingStartResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class OnboardingStatusResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


# ── 内部状态常量 ───────────────────────────────────────────────────

ONBOARDING_STEPS: list[str] = [
    "ssm_verification",       # SSM 企业注册验证
    "subsidy_eligibility",    # 政府补贴资格检查
    "einvoice_registration",  # MyInvois e-Invoice 注册
    "complete",               # 入驻完成
]

ONBOARDING_STATUSES: list[str] = [
    "pending",
    "in_progress",
    "completed",
    "failed",
    "rejected",
]


# ── DI ──────────────────────────────────────────────────────────


async def get_onboarding_service() -> SMEOnboardingService:
    return SMEOnboardingService()


# ── 服务层 ─────────────────────────────────────────────────────────


class SMEOnboardingService:
    """马来西亚 SME 入驻流程编排服务

    三阶段入驻流程：
      1. SSM 验证 — 核对企业注册号和名称是否匹配
      2. 补贴资格 — 检查 MDEC/SME Corp 的可用补贴方案
      3. e-Invoice — 注册 MyInvois 电子发票
    """

    async def start_onboarding(
        self,
        tenant_id: str,
        request: OnboardingStartRequest,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """启动马来西亚 SME 入驻流程

        创建入驻记录，依次执行三阶段流程，并返回当前状态。

        Args:
            tenant_id: 商户 UUID.
            request: 入驻请求参数.
            db: 数据库会话.

        Returns:
            {
                onboarding_id: str,
                business_name, registration_number, business_type,
                status, current_step, completed_steps: [],
                ssm_verification: { verified, message },
                subsidy_eligibility: null (待执行),
                einvoice_registration: null (待执行),
            }
        """
        log = logger.bind(
            tenant_id=tenant_id,
            registration_number=request.registration_number,
        )
        log.info("onboarding.start")

        # 1. SSM 验证
        ssm_result = await self._verify_ssm(
            registration_number=request.registration_number,
            business_name=request.business_name,
        )
        if not ssm_result["verified"]:
            log.warning(
                "onboarding.ssm_verification_failed",
                reason=ssm_result["message"],
            )
            # 创建失败记录
            onboarding_id = str(uuid4())
            await self._save_onboarding_record(
                db=db,
                onboarding_id=onboarding_id,
                tenant_id=tenant_id,
                request=request,
                status="failed",
                current_step="ssm_verification",
                completed_steps=[],
                details={"ssm_verification": ssm_result},
            )
            return {
                "onboarding_id": onboarding_id,
                "business_name": request.business_name,
                "registration_number": request.registration_number,
                "business_type": request.business_type,
                "status": "failed",
                "current_step": "ssm_verification",
                "completed_steps": [],
                "ssm_verification": ssm_result,
                "subsidy_eligibility": None,
                "einvoice_registration": None,
                "message": ssm_result["message"],
            }

        # 2. 检查补贴资格
        subsidy_result = await self._check_subsidy_eligibility(
            registration_number=request.registration_number,
            business_type=request.business_type,
        )

        # 3. e-Invoice 注册
        einvoice_result = await self._register_einvoice(
            registration_number=request.registration_number,
            business_name=request.business_name,
            contact_email=request.contact_email,
        )

        completed = [
            "ssm_verification",
            "subsidy_eligibility",
            "einvoice_registration",
        ]

        overall_status = "completed"
        if not einvoice_result["registered"]:
            overall_status = "failed"
            current_step = "einvoice_registration"
        else:
            current_step = "complete"

        onboarding_id = str(uuid4())
        await self._save_onboarding_record(
            db=db,
            onboarding_id=onboarding_id,
            tenant_id=tenant_id,
            request=request,
            status=overall_status,
            current_step=current_step,
            completed_steps=completed if overall_status == "completed" else completed[:2],
            details={
                "ssm_verification": ssm_result,
                "subsidy_eligibility": subsidy_result,
                "einvoice_registration": einvoice_result,
            },
        )

        log.info(
            "onboarding.complete",
            status=overall_status,
            onboarding_id=onboarding_id,
        )

        return {
            "onboarding_id": onboarding_id,
            "business_name": request.business_name,
            "registration_number": request.registration_number,
            "business_type": request.business_type,
            "status": overall_status,
            "current_step": current_step,
            "completed_steps": completed,
            "ssm_verification": ssm_result,
            "subsidy_eligibility": subsidy_result,
            "einvoice_registration": einvoice_result,
        }

    async def get_onboarding_status(
        self,
        onboarding_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询入驻流程当前状态

        Args:
            onboarding_id: 入驻记录 UUID.
            tenant_id: 商户 UUID.
            db: 数据库会话.

        Returns:
            入驻状态详情，包括各阶段结果。

        Raises:
            ValueError: 入驻记录不存在或不属于该租户.
        """
        log = logger.bind(onboarding_id=onboarding_id, tenant_id=tenant_id)
        log.info("onboarding.status_check")

        try:
            row = await db.execute(
                text("""
                    SELECT
                        id, tenant_id, business_name, registration_number,
                        business_type, status, current_step, completed_steps,
                        details, created_at, updated_at
                    FROM sme_onboarding_records
                    WHERE id = :oid AND tenant_id = :tid AND is_deleted = FALSE
                """),
                {"oid": onboarding_id, "tid": tenant_id},
            )
            record = row.mappings().fetchone()
        except Exception as exc:
            log.warning("onboarding.status_query_failed", error=str(exc))
            record = None

        if record is None:
            raise ValueError(
                f"Onboarding record not found: {onboarding_id}"
            )

        return {
            "onboarding_id": str(record["id"]),
            "business_name": record["business_name"],
            "registration_number": record["registration_number"],
            "business_type": record["business_type"],
            "status": record["status"],
            "current_step": record["current_step"],
            "completed_steps": record["completed_steps"] or [],
            "details": record["details"] or {},
            "created_at": (
                record["created_at"].isoformat()
                if record["created_at"] else None
            ),
            "updated_at": (
                record["updated_at"].isoformat()
                if record["updated_at"] else None
            ),
        }

    # ─── SSM 验证 ────────────────────────────────────────────────

    @staticmethod
    async def _verify_ssm(
        registration_number: str,
        business_name: str,
    ) -> dict[str, Any]:
        """验证 SSM 企业注册信息

        模拟调用 SSM API (Suruhanjaya Syarikat Malaysia) 验证企业注册号。
        生产环境应集成真实的 SSM eInfo API。

        Args:
            registration_number: SSM 注册号.
            business_name: 企业名称（用于比对）.

        Returns:
            { verified: bool, message: str, registration_number: str }
        """
        log = logger.bind(
            registration_number=registration_number,
        )

        # 模拟 SSM API 调用
        # 实际生产环境应替换为：
        #   ssm_client = SSMClient()
        #   result = await ssm_client.verify(registration_number)
        if len(registration_number) < 8:
            log.warning("onboarding.ssm_invalid_format")
            return {
                "verified": False,
                "message": f"Invalid SSM registration number format: "
                           f"{registration_number}. Expected at least 8 characters.",
                "registration_number": registration_number,
                "business_name_matched": False,
            }

        # 模拟：SSM 验证通过（格式正确的情况下）
        log.info("onboarding.ssm_verified")
        return {
            "verified": True,
            "message": "SSM registration verified successfully.",
            "registration_number": registration_number,
            "business_name_matched": True,
            "company_status": "active",
            "company_type": "sdn_bhd",
        }

    # ─── 补贴资格检查 ────────────────────────────────────────────

    @staticmethod
    async def _check_subsidy_eligibility(
        registration_number: str,
        business_type: str,
    ) -> dict[str, Any]:
        """检查企业是否符合 MDEC / SME Corp 补贴方案资格

        模拟补贴资格评估。生产环境应集成 MDEC Smart Automation Grant
        和 SME Corp 的 API 查询实际可用额度。

        Args:
            registration_number: SSM 注册号.
            business_type: 企业类型.

        Returns:
            {
                eligible: bool,
                programs: [ { program, rate, max_amount, description } ],
                message: str,
            }
        """
        log = logger.bind(
            registration_number=registration_number,
            business_type=business_type,
        )

        # 适用于 Sdn Bhd 和 Enterprise 的常见补贴方案
        eligible_programs = [
            {
                "program": "MDEC Smart Automation Grant",
                "rate": 0.50,
                "max_amount_fen": 50000000,  # RM 500,000
                "max_amount_rm": 500000.00,
                "description": "50% subsidy for automation & digitalisation",
            },
            {
                "program": "SME Corp Business Digitalisation",
                "rate": 0.30,
                "max_amount_fen": 15000000,  # RM 150,000
                "max_amount_rm": 150000.00,
                "description": "30% subsidy for SME digital transformation",
            },
        ]

        if business_type == "sole_proprietorship":
            # 个体户通常只有有限补贴方案
            eligible_programs = [
                {
                    "program": "SME Corp Micro Business Grant",
                    "rate": 0.20,
                    "max_amount_fen": 5000000,  # RM 50,000
                    "max_amount_rm": 50000.00,
                    "description": "20% subsidy for micro business digitalisation",
                },
            ]

        log.info(
            "onboarding.subsidy_checked",
            program_count=len(eligible_programs),
        )

        return {
            "eligible": True,
            "programs": eligible_programs,
            "message": (
                f"Found {len(eligible_programs)} eligible subsidy programs."
            ),
        }

    # ─── e-Invoice 注册 ──────────────────────────────────────────

    @staticmethod
    async def _register_einvoice(
        registration_number: str,
        business_name: str,
        contact_email: str,
    ) -> dict[str, Any]:
        """向 LHDN MyInvois 注册电子发票

        模拟调用 LHDN MyInvois API。生产环境应集成 MyInvois SDK。

        Args:
            registration_number: SSM 注册号.
            business_name: 企业名称.
            contact_email: 联系邮箱.

        Returns:
            {
                registered: bool,
                einvoice_id: str | None,
                message: str,
            }
        """
        log = logger.bind(
            registration_number=registration_number,
        )

        # 模拟 e-Invoice API 注册
        # 生产环境应替换为：
        #   myinvois = MyInvoisClient()
        #   result = await myinvois.register(registration_number, business_name)
        einvoice_id = f"EI-{registration_number}-{uuid4().hex[:8].upper()}"

        log.info("onboarding.einvoice_registered", einvoice_id=einvoice_id)

        return {
            "registered": True,
            "einvoice_id": einvoice_id,
            "message": (
                "Successfully registered for LHDN MyInvois e-Invoice. "
                "You can now issue electronic invoices."
            ),
        }

    # ─── 持久化 ──────────────────────────────────────────────────

    @staticmethod
    async def _save_onboarding_record(
        db: AsyncSession,
        onboarding_id: str,
        tenant_id: str,
        request: OnboardingStartRequest,
        status: str,
        current_step: str,
        completed_steps: list[str],
        details: dict[str, Any],
    ) -> None:
        """持久化入驻记录到数据库

        Args:
            db: 数据库会话.
            onboarding_id: 入驻记录 UUID.
            tenant_id: 商户 UUID.
            request: 入驻请求参数.
            status: 入驻状态.
            current_step: 当前步骤.
            completed_steps: 已完成步骤列表.
            details: 各阶段的详细结果.
        """
        try:
            await db.execute(
                text("""
                    INSERT INTO sme_onboarding_records (
                        id, tenant_id, business_name, registration_number,
                        business_type, contact_email, contact_phone,
                        business_address, owner_name, owner_id_number,
                        status, current_step, completed_steps, details,
                        created_at, updated_at
                    ) VALUES (
                        :oid, :tid, :biz_name, :reg_no,
                        :biz_type, :email, :phone,
                        :address, :owner, :owner_id,
                        :status, :step, :completed, :details,
                        NOW(), NOW()
                    )
                """),
                {
                    "oid": onboarding_id,
                    "tid": tenant_id,
                    "biz_name": request.business_name,
                    "reg_no": request.registration_number,
                    "biz_type": request.business_type,
                    "email": request.contact_email,
                    "phone": request.contact_phone,
                    "address": request.business_address,
                    "owner": request.owner_name or "",
                    "owner_id": request.owner_id_number or "",
                    "status": status,
                    "step": current_step,
                    "completed": completed_steps,
                    "details": details,
                },
            )
            await db.commit()
        except Exception as exc:
            log = logger.bind(onboarding_id=onboarding_id)
            log.error("onboarding.save_failed", error=str(exc))
            await db.rollback()
            raise


# ── 端点 ──────────────────────────────────────────────────────────


@router.post("/start")
async def start_onboarding(
    request: OnboardingStartRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: SMEOnboardingService = Depends(get_onboarding_service),
):
    """启动马来西亚 SME 入驻流程

    三步自动执行：
      1. SSM 企业注册验证 — 核对企业注册号和名称
      2. 政府补贴资格检查 — 匹配 MDEC / SME Corp 补贴方案
      3. MyInvois e-Invoice 注册 — 开通电子发票

    入驻过程中任一阶段失败会记录原因并返回失败状态。
    """
    try:
        result = await service.start_onboarding(
            tenant_id=x_tenant_id,
            request=request,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{onboarding_id}")
async def get_onboarding_status(
    onboarding_id: str = Path(..., description="入驻记录 UUID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: SMEOnboardingService = Depends(get_onboarding_service),
):
    """查询入驻流程状态

    返回指定入驻记录的当前状态、已完成步骤、各阶段详细信息。
    """
    try:
        result = await service.get_onboarding_status(
            onboarding_id=onboarding_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
