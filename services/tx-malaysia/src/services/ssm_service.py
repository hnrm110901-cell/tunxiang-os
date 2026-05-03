"""马来西亚 SSM（Suruhanjaya Syarikat Malaysia）企业注册验证服务

SSM = 马来西亚公司委员会，负责企业注册与商业登记。

职责：
  - 验证公司注册号 + 公司名匹配
  - 模糊搜索公司
  - 获取公司详细资料（董事、股东等）
  - 验证董事身份
  - 查询公司状态（active/dissolved/struck-off）

注意：SSM 官方不提供公开沙箱环境。此服务内置 `_MOCK_DATA` 用于
开发/测试，生产环境需配置 `SSM_API_BASE` + API Key。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# SSM API 配置（生产环境通过环境变量注入）
_SSM_API_BASE = ""  # e.g. "https://api.ssm.com.my/api/v1"
_SSM_API_KEY = ""  # 生产环境 API Key

# ── SSM 公司状态枚举 ────────────────────────────────────────────
SSM_COMPANY_STATUSES = ("active", "dissolved", "struck-off", "winding-up", "inactive", "unknown")


# ── Mock 数据（开发/沙箱测试用） ──────────────────────────────

_MOCK_DATA: dict[str, dict[str, Any]] = {
    "202001000001": {
        "registration_no": "202001000001",
        "company_name": "Tunxiang Technology Sdn Bhd",
        "former_name": None,
        "status": "active",
        "company_type": "Sdn Bhd",
        "business_nature": "软件开发与餐饮科技解决方案",
        "registered_address": {
            "line1": "Level 12, Menara Bintang",
            "line2": "Jalan Ampang",
            "city": "Kuala Lumpur",
            "postcode": "50450",
            "state": "Wilayah Persekutuan",
        },
        "incorporation_date": "2020-01-15",
        "expiry_date": "2025-01-15",
        "last_agm_date": "2024-06-30",
        "paid_up_capital_fen": 1000000_00,  # RM 1,000,000 in fen
        "directors": [
            {"name": "Lee Wei Ming", "ic_number": "800101-01-1234", "position": "Director"},
            {"name": "Tan Siew Ling", "ic_number": "850505-02-5678", "position": "Director"},
        ],
        "shareholders": [
            {"name": "Lee Wei Ming", "shares": 50000, "share_type": "Ordinary"},
            {"name": "Tan Siew Ling", "shares": 50000, "share_type": "Ordinary"},
        ],
    },
    "201901000888": {
        "registration_no": "201901000888",
        "company_name": "MakanMakan Restaurant Sdn Bhd",
        "former_name": "MakanMakan Enterprise",
        "status": "active",
        "company_type": "Sdn Bhd",
        "business_nature": "餐厅运营与餐饮服务",
        "registered_address": {
            "line1": "No 15, Jalan SS2/72",
            "line2": "",
            "city": "Petaling Jaya",
            "postcode": "47300",
            "state": "Selangor",
        },
        "incorporation_date": "2019-03-20",
        "expiry_date": "2025-03-20",
        "last_agm_date": "2024-03-15",
        "paid_up_capital_fen": 500000_00,
        "directors": [
            {"name": "Ahmad bin Ismail", "ic_number": "750808-10-5678", "position": "Managing Director"},
        ],
        "shareholders": [
            {"name": "Ahmad bin Ismail", "shares": 100000, "share_type": "Ordinary"},
        ],
    },
    "202301005555": {
        "registration_no": "202301005555",
        "company_name": "Kedai Kopi Warisan Sdn Bhd",
        "former_name": None,
        "status": "dissolved",
        "company_type": "Sdn Bhd",
        "business_nature": "咖啡店经营",
        "registered_address": {
            "line1": "88, Jalan Tun Razak",
            "line2": "",
            "city": "Kuala Lumpur",
            "postcode": "50400",
            "state": "Wilayah Persekutuan",
        },
        "incorporation_date": "2023-01-10",
        "expiry_date": "2024-01-10",
        "last_agm_date": "2023-12-01",
        "paid_up_capital_fen": 100000_00,
        "directors": [],
        "shareholders": [],
    },
}


# ── 工具函数 ────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── SSM 服务 ────────────────────────────────────────────────────


class SSMService:
    """马来西亚 SSM 企业注册验证服务

    用法:
        ssm = SSMService()
        result = await ssm.verify_company("202001000001", "Tunxiang Technology Sdn Bhd")

    开发/沙箱环境使用内置 `_MOCK_DATA`；生产环境通过 `_SSM_API_BASE` 连接 SSM API。
    """

    def __init__(self, api_base: str = "", api_key: str = "") -> None:
        self._api_base = api_base or _SSM_API_BASE
        self._api_key = api_key or _SSM_API_KEY
        self._use_mock = not self._api_base

    # ════════════════════════════════════════════════════════════
    # 核心验证
    # ════════════════════════════════════════════════════════════

    async def verify_company(
        self,
        registration_no: str,
        company_name: str,
    ) -> dict[str, Any]:
        """验证公司注册号 + 公司名是否匹配

        Args:
            registration_no: SSM 注册号（如 202001000001）
            company_name: 公司全名

        Returns:
            {
                verified: bool,
                company_name: str,
                registration_no: str,
                status: str,
                company_type: str,
                business_nature: str,
                registered_address: dict,
                expiry_date: str,
            }
        """
        log = logger.bind(registration_no=registration_no, company_name=company_name)
        log.info("ssm.verify_company")

        if not registration_no or not registration_no.strip():
            raise ValueError("registration_no is required")
        if not company_name or not company_name.strip():
            raise ValueError("company_name is required")

        if self._use_mock:
            company = _MOCK_DATA.get(registration_no)
            if company is None:
                log.warning("ssm.company_not_found", registration_no=registration_no)
                return {
                    "verified": False,
                    "company_name": company_name,
                    "registration_no": registration_no,
                    "status": "not_found",
                    "company_type": "",
                    "business_nature": "",
                    "registered_address": {},
                    "expiry_date": "",
                    "checked_at": _now_iso(),
                }

            name_match = company["company_name"].lower() == company_name.strip().lower()
            log.info(
                "ssm.verify_result",
                verified=name_match,
                status=company["status"],
                name_match=name_match,
            )

            return {
                "verified": name_match,
                "company_name": company["company_name"],
                "registration_no": registration_no,
                "status": company["status"],
                "company_type": company["company_type"],
                "business_nature": company["business_nature"],
                "registered_address": company["registered_address"],
                "expiry_date": company["expiry_date"],
                "checked_at": _now_iso(),
            }

        # TODO: 生产环境 — 调用 SSM API
        # result = await self._call_ssm_api("verify", {
        #     "registration_no": registration_no,
        #     "company_name": company_name,
        # })
        raise NotImplementedError("SSM production API not yet configured")

    async def search_company(self, keyword: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        """模糊搜索公司

        Args:
            keyword: 搜索关键词（公司名/注册号）
            page: 页码（从 1 开始）
            size: 每页条数

        Returns:
            { total: int, page: int, size: int, items: [...] }
        """
        log = logger.bind(keyword=keyword, page=page, size=size)
        log.info("ssm.search_company")

        if not keyword or not keyword.strip():
            raise ValueError("keyword is required")
        if page < 1:
            raise ValueError("page must be >= 1")
        if size < 1 or size > 100:
            raise ValueError("size must be between 1 and 100")

        if self._use_mock:
            kw = keyword.strip().lower()
            results = []
            for reg_no, company in _MOCK_DATA.items():
                if kw in company["company_name"].lower() or kw in reg_no:
                    results.append({
                        "registration_no": company["registration_no"],
                        "company_name": company["company_name"],
                        "status": company["status"],
                        "company_type": company["company_type"],
                        "incorporation_date": company["incorporation_date"],
                    })

            total = len(results)
            start = (page - 1) * size
            end = start + size
            page_items = results[start:end]

            log.info("ssm.search_result", total=total, returned=len(page_items))
            return {
                "total": total,
                "page": page,
                "size": size,
                "items": page_items,
            }

        raise NotImplementedError("SSM production API not yet configured")

    async def get_company_detail(self, registration_no: str) -> dict[str, Any]:
        """获取公司详细资料（董事、股东及公司信息）"""
        log = logger.bind(registration_no=registration_no)
        log.info("ssm.get_company_detail")

        if not registration_no or not registration_no.strip():
            raise ValueError("registration_no is required")

        if self._use_mock:
            company = _MOCK_DATA.get(registration_no)
            if company is None:
                log.warning("ssm.company_not_found", registration_no=registration_no)
                return {"found": False, "registration_no": registration_no}

            log.info("ssm.detail_returned", company_name=company["company_name"])
            return {
                "found": True,
                "registration_no": company["registration_no"],
                "company_name": company["company_name"],
                "former_name": company["former_name"],
                "status": company["status"],
                "company_type": company["company_type"],
                "business_nature": company["business_nature"],
                "registered_address": company["registered_address"],
                "incorporation_date": company["incorporation_date"],
                "expiry_date": company["expiry_date"],
                "last_agm_date": company["last_agm_date"],
                "paid_up_capital_fen": company["paid_up_capital_fen"],
                "directors": company["directors"],
                "shareholders": company["shareholders"],
            }

        raise NotImplementedError("SSM production API not yet configured")

    async def validate_director(
        self,
        registration_no: str,
        director_name: str,
        ic_number: str,
    ) -> dict[str, Any]:
        """验证董事身份

        Args:
            registration_no: SSM 注册号
            director_name: 董事姓名
            ic_number: 身份证号码

        Returns:
            { validated: bool, registration_no, director_name, ic_number,
              position: str, is_active: bool }
        """
        log = logger.bind(
            registration_no=registration_no,
            director_name=director_name,
        )
        log.info("ssm.validate_director")

        if not registration_no:
            raise ValueError("registration_no is required")
        if not director_name:
            raise ValueError("director_name is required")
        if not ic_number:
            raise ValueError("ic_number is required")

        if self._use_mock:
            company = _MOCK_DATA.get(registration_no)
            if company is None:
                log.warning("ssm.company_not_found", registration_no=registration_no)
                return {
                    "validated": False,
                    "registration_no": registration_no,
                    "director_name": director_name,
                    "ic_number": ic_number,
                    "position": "",
                    "is_active": False,
                }

            for director in company.get("directors", []):
                if (
                    director["name"].lower() == director_name.strip().lower()
                    and director["ic_number"] == ic_number.strip()
                ):
                    log.info("ssm.director_validated", position=director["position"])
                    return {
                        "validated": True,
                        "registration_no": registration_no,
                        "director_name": director["name"],
                        "ic_number": ic_number,
                        "position": director["position"],
                        "is_active": company["status"] == "active",
                    }

            log.warning("ssm.director_not_found")
            return {
                "validated": False,
                "registration_no": registration_no,
                "director_name": director_name,
                "ic_number": ic_number,
                "position": "",
                "is_active": False,
            }

        raise NotImplementedError("SSM production API not yet configured")

    async def check_company_status(self, registration_no: str) -> str:
        """检查公司状态

        Returns:
            "active" | "dissolved" | "struck-off" | "winding-up" | "inactive" | "unknown"
        """
        log = logger.bind(registration_no=registration_no)
        log.info("ssm.check_status")

        if not registration_no or not registration_no.strip():
            raise ValueError("registration_no is required")

        if self._use_mock:
            company = _MOCK_DATA.get(registration_no)
            if company is None:
                log.warning("ssm.company_not_found", registration_no=registration_no)
                return "unknown"

            status = company.get("status", "unknown")
            log.info("ssm.status_result", status=status)
            return status

        raise NotImplementedError("SSM production API not yet configured")

    # ════════════════════════════════════════════════════════════
    # SSM API 调用（生产环境）
    # ════════════════════════════════════════════════════════════

    async def _call_ssm_api(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 SSM 官方 API（生产环境实现）"""
        # TODO: 生产环境实现
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         f"{self._api_base}/{endpoint}",
        #         json=payload,
        #         headers={"X-API-Key": self._api_key},
        #     )
        #     response.raise_for_status()
        #     return response.json()
        raise NotImplementedError("SSM production API not yet configured")
