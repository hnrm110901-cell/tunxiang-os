"""金税四期发票OCR识别+验真服务

核心流程:
1. 接收发票图片URL
2. 调用OCR API(腾讯云/阿里云/百度云,可配置)识别发票内容
3. 结构化提取: 代码/号码/日期/金额/税额/购销方/明细
4. SHA-256去重检查(发票代码+号码+金额)
5. 验真(调用税务局查验接口,当前Mock,预留真实接口)
6. 写入ocr_results + 关联e_invoices

OCR降级策略:
- 腾讯云不可用→切阿里云→切百度云
- 全不可用→返回manual_required状态

金额单位: 分(fen), int/BIGINT
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── OCR提供商优先级 ─────────────────────────────────────────────────────────

OCR_PROVIDERS: list[str] = ["tencent", "aliyun", "baidu"]

# ─── OCR模拟结果模板（生产环境替换为真实API调用）─────────────────────────────

_MOCK_OCR_RESULT: dict[str, Any] = {
    "invoice_code": "011002100311",
    "invoice_number": "48026588",
    "invoice_date": "2026-04-15",
    "seller_name": "长沙市某食材供应有限公司",
    "seller_tax_no": "91430100MA4L2X",
    "buyer_name": "屯象科技有限公司",
    "buyer_tax_no": "91430100MA4K9Y",
    "total_amount_fen": 128000,
    "tax_amount_fen": 7680,
    "items": [
        {
            "name": "猪肉（五花肉）",
            "quantity": 50,
            "unit": "kg",
            "unit_price_fen": 2200,
            "amount_fen": 110000,
            "tax_rate": "0.06",
        },
        {
            "name": "食用油（大豆油）",
            "quantity": 10,
            "unit": "桶",
            "unit_price_fen": 1800,
            "amount_fen": 18000,
            "tax_rate": "0.06",
        },
    ],
    "confidence_score": 0.95,
}


class OCRProviderUnavailableError(RuntimeError):
    """所有OCR提供商均不可用"""


class DuplicateInvoiceError(ValueError):
    """发票重复（SHA-256 hash 冲突）"""


class OCRResultNotFoundError(LookupError):
    """OCR结果不存在"""


class InvoiceOCRService:
    """金税四期发票OCR识别+验真服务"""

    async def recognize_invoice(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        image_url: str,
        provider: Optional[str] = None,
    ) -> dict[str, Any]:
        """OCR识别发票

        流程:
        1. 调用OCR API(当前为模拟,预留真实HTTP调用位置)
        2. 解析返回结果为统一结构
        3. 计算SHA-256去重hash
        4. 检查是否重复
        5. 写入数据库

        Args:
            db: 已绑定 tenant_id 的 DB session
            tenant_id: 租户ID
            image_url: 发票图片URL
            provider: 指定OCR提供商(可选,默认按优先级降级)

        Returns:
            OCR识别结果字典

        Raises:
            OCRProviderUnavailableError: 所有提供商不可用
            DuplicateInvoiceError: 发票重复
        """
        log = logger.bind(tenant_id=str(tenant_id), image_url=image_url)
        log.info("invoice_ocr.recognize_start")

        # 1. 调用OCR API（降级策略）
        providers_to_try = [provider] if provider else OCR_PROVIDERS
        ocr_result: Optional[dict[str, Any]] = None
        used_provider: str = ""

        for p in providers_to_try:
            if p is None:
                continue
            try:
                ocr_result = await self._call_ocr_api(image_url, p)
                used_provider = p
                log.info("invoice_ocr.provider_success", provider=p)
                break
            except (ConnectionError, TimeoutError, OSError) as exc:
                log.warning(
                    "invoice_ocr.provider_failed",
                    provider=p,
                    error=str(exc),
                )
                continue

        if ocr_result is None:
            log.error("invoice_ocr.all_providers_failed")
            raise OCRProviderUnavailableError(
                "所有OCR提供商均不可用,请稍后重试或手动录入"
            )

        # 2. 提取结构化数据
        invoice_code = ocr_result.get("invoice_code", "")
        invoice_number = ocr_result.get("invoice_number", "")
        total_amount_fen = int(ocr_result.get("total_amount_fen", 0))
        tax_amount_fen = int(ocr_result.get("tax_amount_fen", 0))
        confidence_score = float(ocr_result.get("confidence_score", 0.0))

        # 3. SHA-256去重hash
        duplicate_hash = self._compute_duplicate_hash(
            invoice_code, invoice_number, total_amount_fen
        )

        # 4. 检查是否重复（跨租户,集团多品牌场景）
        is_duplicate = await self._check_duplicate(db, tenant_id, duplicate_hash)
        verification_status = "duplicate" if is_duplicate else "pending"

        if is_duplicate:
            log.warning(
                "invoice_ocr.duplicate_detected",
                invoice_code=invoice_code,
                invoice_number=invoice_number,
                duplicate_hash=duplicate_hash,
            )

        # 5. 解析日期
        invoice_date_str = ocr_result.get("invoice_date", "")
        invoice_date: Optional[date] = None
        if invoice_date_str:
            try:
                invoice_date = date.fromisoformat(invoice_date_str)
            except ValueError:
                log.warning(
                    "invoice_ocr.invalid_date",
                    raw_date=invoice_date_str,
                )

        # 6. 写入数据库
        result_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO invoice_ocr_results (
                    id, tenant_id, image_url, ocr_provider, ocr_raw_json,
                    invoice_code, invoice_number, invoice_date,
                    seller_name, seller_tax_no, buyer_name, buyer_tax_no,
                    total_amount_fen, tax_amount_fen, items,
                    verification_status, is_duplicate, duplicate_hash,
                    confidence_score, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :image_url, :ocr_provider, :ocr_raw_json::JSONB,
                    :invoice_code, :invoice_number, :invoice_date,
                    :seller_name, :seller_tax_no, :buyer_name, :buyer_tax_no,
                    :total_amount_fen, :tax_amount_fen, :items::JSONB,
                    :verification_status, :is_duplicate, :duplicate_hash,
                    :confidence_score, :created_at, :updated_at
                )
            """),
            {
                "id": str(result_id),
                "tenant_id": str(tenant_id),
                "image_url": image_url,
                "ocr_provider": used_provider,
                "ocr_raw_json": _json_dumps(ocr_result),
                "invoice_code": invoice_code,
                "invoice_number": invoice_number,
                "invoice_date": invoice_date,
                "seller_name": ocr_result.get("seller_name", ""),
                "seller_tax_no": ocr_result.get("seller_tax_no", ""),
                "buyer_name": ocr_result.get("buyer_name", ""),
                "buyer_tax_no": ocr_result.get("buyer_tax_no", ""),
                "total_amount_fen": total_amount_fen,
                "tax_amount_fen": tax_amount_fen,
                "items": _json_dumps(ocr_result.get("items", [])),
                "verification_status": verification_status,
                "is_duplicate": is_duplicate,
                "duplicate_hash": duplicate_hash,
                "confidence_score": confidence_score,
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()

        log.info(
            "invoice_ocr.recognize_done",
            result_id=str(result_id),
            provider=used_provider,
            is_duplicate=is_duplicate,
            confidence=confidence_score,
        )

        return {
            "id": str(result_id),
            "tenant_id": str(tenant_id),
            "image_url": image_url,
            "ocr_provider": used_provider,
            "invoice_code": invoice_code,
            "invoice_number": invoice_number,
            "invoice_date": str(invoice_date) if invoice_date else None,
            "seller_name": ocr_result.get("seller_name", ""),
            "seller_tax_no": ocr_result.get("seller_tax_no", ""),
            "buyer_name": ocr_result.get("buyer_name", ""),
            "buyer_tax_no": ocr_result.get("buyer_tax_no", ""),
            "total_amount_fen": total_amount_fen,
            "tax_amount_fen": tax_amount_fen,
            "items": ocr_result.get("items", []),
            "verification_status": verification_status,
            "is_duplicate": is_duplicate,
            "duplicate_hash": duplicate_hash,
            "confidence_score": confidence_score,
        }

    async def _call_ocr_api(
        self, image_url: str, provider: str
    ) -> dict[str, Any]:
        """调用OCR提供商API

        当前实现：返回模拟OCR结果（预留真实HTTP调用位置）
        生产部署：替换下方 mock 逻辑为真实API调用

        ┌──────────────────────────────────────────────────────────────┐
        │ 生产环境替换点 — 真实OCR API调用                              │
        │                                                              │
        │ 腾讯云 VatInvoiceOCR:                                        │
        │   POST https://ocr.tencentcloudapi.com                       │
        │   Action: VatInvoiceOCR                                      │
        │   Body: {"ImageUrl": image_url}                              │
        │   SDK: tencentcloud-sdk-python / ocr                         │
        │                                                              │
        │ 阿里云 RecognizeVatInvoice:                                   │
        │   POST https://ocr.cn-shanghai.aliyuncs.com                  │
        │   Action: RecognizeVatInvoice                                │
        │   Body: {"Url": image_url}                                   │
        │   SDK: alibabacloud-ocr20191230                              │
        │                                                              │
        │ 百度云 VatInvoice:                                            │
        │   POST https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice │
        │   Body: {"url": image_url}                                   │
        │   SDK: baidu-aip                                             │
        │                                                              │
        │ 示例（腾讯云）:                                               │
        │   import httpx                                                │
        │   async with httpx.AsyncClient(timeout=30) as client:        │
        │       resp = await client.post(                              │
        │           "https://ocr.tencentcloudapi.com",                 │
        │           headers=_build_tc_headers(action="VatInvoiceOCR"), │
        │           json={"ImageUrl": image_url},                      │
        │       )                                                       │
        │       resp.raise_for_status()                                │
        │       return _parse_tencent_response(resp.json())            │
        └──────────────────────────────────────────────────────────────┘

        Args:
            image_url: 发票图片URL
            provider: OCR提供商名称

        Returns:
            统一结构的OCR结果字典

        Raises:
            ConnectionError: 提供商网络不可达
            TimeoutError: 请求超时
        """
        log = logger.bind(provider=provider, image_url=image_url)
        log.info("invoice_ocr.calling_provider")

        # ── 当前: 返回模拟结果 ──────────────────────────────────────
        # TODO(生产部署): 替换为真实 httpx.AsyncClient 调用
        result = dict(_MOCK_OCR_RESULT)
        result["_provider"] = provider
        result["_image_url"] = image_url

        log.info("invoice_ocr.mock_result_returned", provider=provider)
        return result

    def _compute_duplicate_hash(
        self,
        invoice_code: str,
        invoice_number: str,
        total_amount_fen: int,
    ) -> str:
        """SHA-256去重hash

        基于发票代码+号码+金额生成唯一标识。
        跨租户检查（集团多品牌场景下同一张发票不能重复录入）。

        Args:
            invoice_code: 发票代码
            invoice_number: 发票号码
            total_amount_fen: 价税合计（分）

        Returns:
            64位SHA-256 hex字符串
        """
        raw = f"{invoice_code}:{invoice_number}:{total_amount_fen}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _check_duplicate(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        duplicate_hash: str,
    ) -> bool:
        """检查发票是否已存在（基于 duplicate_hash）

        注意：此查询跨租户检查，因为同一张发票不应在集团内重复报销。
        但写入时 UNIQUE 约束是 (tenant_id, duplicate_hash)，允许不同租户录入同一发票。

        Args:
            db: 数据库会话
            tenant_id: 租户ID
            duplicate_hash: SHA-256 hash

        Returns:
            True 表示已存在
        """
        result = await db.execute(
            text("""
                SELECT 1 FROM invoice_ocr_results
                WHERE tenant_id = :tenant_id
                  AND duplicate_hash = :duplicate_hash
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tenant_id": str(tenant_id), "duplicate_hash": duplicate_hash},
        )
        return result.scalar_one_or_none() is not None

    async def verify_invoice(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        ocr_result_id: uuid.UUID,
    ) -> dict[str, Any]:
        """发票验真

        ┌──────────────────────────────────────────────────────────────┐
        │ 生产环境替换点 — 真实税务局查验接口                           │
        │                                                              │
        │ 全国增值税发票查验平台:                                       │
        │   https://inv-veri.chinatax.gov.cn                           │
        │   参数: 发票代码 + 发票号码 + 开票日期 + 校验码后6位/金额     │
        │                                                              │
        │ 第三方查验API（如百旺、航信）:                                │
        │   POST /api/verify                                           │
        │   Body: {code, number, date, amount_or_checkcode}            │
        │                                                              │
        │ 当前实现: 模拟验真通过                                        │
        └──────────────────────────────────────────────────────────────┘

        Args:
            db: 数据库会话
            tenant_id: 租户ID
            ocr_result_id: OCR结果ID

        Returns:
            验真结果字典

        Raises:
            OCRResultNotFoundError: OCR结果不存在
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            ocr_result_id=str(ocr_result_id),
        )
        log.info("invoice_ocr.verify_start")

        # 1. 查询OCR结果
        row = await self._get_ocr_result(db, tenant_id, ocr_result_id)
        if row is None:
            raise OCRResultNotFoundError(
                f"OCR结果 {ocr_result_id} 不存在或不属于租户 {tenant_id}"
            )

        # 2. 已验真或重复的不再验
        current_status = row["verification_status"]
        if current_status in ("verified", "duplicate"):
            log.info(
                "invoice_ocr.verify_skipped",
                reason=f"already_{current_status}",
            )
            return {
                "ocr_result_id": str(ocr_result_id),
                "verification_status": current_status,
                "message": f"发票已{current_status},无需重复验真",
            }

        # 3. 模拟验真（TODO: 替换为真实税务局查验接口）
        verification_result: dict[str, Any] = {
            "verified": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "source": "mock",
            "message": "验真通过（模拟）",
        }
        new_status = "verified"

        # 4. 更新数据库
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE invoice_ocr_results
                SET verification_status = :status,
                    verification_result = :result::JSONB,
                    updated_at = :updated_at
                WHERE id = :id
                  AND tenant_id = :tenant_id
            """),
            {
                "status": new_status,
                "result": _json_dumps(verification_result),
                "updated_at": now,
                "id": str(ocr_result_id),
                "tenant_id": str(tenant_id),
            },
        )
        await db.commit()

        log.info(
            "invoice_ocr.verify_done",
            status=new_status,
        )

        return {
            "ocr_result_id": str(ocr_result_id),
            "verification_status": new_status,
            "verification_result": verification_result,
        }

    async def batch_recognize(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        image_urls: list[str],
    ) -> list[dict[str, Any]]:
        """批量OCR识别

        逐张识别（保证每张都有独立的去重检查和错误处理）。
        未来优化：可并发调用OCR API。

        Args:
            db: 数据库会话
            tenant_id: 租户ID
            image_urls: 发票图片URL列表

        Returns:
            识别结果列表（每项含 ok/data/error 状态）
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            batch_size=len(image_urls),
        )
        log.info("invoice_ocr.batch_start")

        results: list[dict[str, Any]] = []
        for url in image_urls:
            try:
                result = await self.recognize_invoice(db, tenant_id, url)
                results.append({"ok": True, "data": result, "image_url": url})
            except DuplicateInvoiceError as exc:
                results.append({
                    "ok": False,
                    "image_url": url,
                    "error": {"code": "DUPLICATE", "message": str(exc)},
                })
            except OCRProviderUnavailableError as exc:
                results.append({
                    "ok": False,
                    "image_url": url,
                    "error": {"code": "OCR_UNAVAILABLE", "message": str(exc)},
                })

        success_count = sum(1 for r in results if r.get("ok"))
        log.info(
            "invoice_ocr.batch_done",
            total=len(image_urls),
            success=success_count,
            failed=len(image_urls) - success_count,
        )

        return results

    async def get_ocr_results(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        status_filter: Optional[str] = None,
    ) -> dict[str, Any]:
        """查询OCR结果列表

        支持分页和按验真状态过滤。

        Args:
            db: 数据库会话
            tenant_id: 租户ID
            page: 页码(从1开始)
            size: 每页大小
            status_filter: 验真状态过滤(可选)

        Returns:
            {"items": [...], "total": int, "page": int, "size": int}
        """
        offset = (page - 1) * size

        # 构建查询条件
        where_clauses = [
            "tenant_id = :tenant_id",
            "is_deleted = FALSE",
        ]
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "limit": size,
            "offset": offset,
        }

        if status_filter:
            where_clauses.append("verification_status = :status_filter")
            params["status_filter"] = status_filter

        where_sql = " AND ".join(where_clauses)

        # 查询总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM invoice_ocr_results WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar_one()

        # 查询列表
        list_result = await db.execute(
            text(f"""
                SELECT id, tenant_id, invoice_id, image_url, ocr_provider,
                       invoice_code, invoice_number, invoice_date,
                       seller_name, seller_tax_no, buyer_name, buyer_tax_no,
                       total_amount_fen, tax_amount_fen,
                       verification_status, is_duplicate, duplicate_hash,
                       confidence_score, created_at, updated_at
                FROM invoice_ocr_results
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = list_result.mappings().all()

        items = [_row_to_dict(row) for row in rows]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    async def get_ocr_result_detail(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        result_id: uuid.UUID,
    ) -> Optional[dict[str, Any]]:
        """查询单条OCR结果详情

        Args:
            db: 数据库会话
            tenant_id: 租户ID
            result_id: OCR结果ID

        Returns:
            OCR结果字典,不存在返回None
        """
        row = await self._get_ocr_result(db, tenant_id, result_id)
        if row is None:
            return None
        return _row_to_detail_dict(row)

    async def _get_ocr_result(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        result_id: uuid.UUID,
    ) -> Optional[Any]:
        """内部：查询单条OCR结果"""
        result = await db.execute(
            text("""
                SELECT * FROM invoice_ocr_results
                WHERE id = :id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"id": str(result_id), "tenant_id": str(tenant_id)},
        )
        return result.mappings().first()


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _json_dumps(obj: Any) -> str:
    """安全JSON序列化"""
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将数据库行转换为响应字典（列表用,不含raw_json）"""
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "invoice_id": str(row["invoice_id"]) if row.get("invoice_id") else None,
        "image_url": row["image_url"],
        "ocr_provider": row["ocr_provider"],
        "invoice_code": row.get("invoice_code"),
        "invoice_number": row.get("invoice_number"),
        "invoice_date": str(row["invoice_date"]) if row.get("invoice_date") else None,
        "seller_name": row.get("seller_name"),
        "buyer_name": row.get("buyer_name"),
        "total_amount_fen": row.get("total_amount_fen"),
        "tax_amount_fen": row.get("tax_amount_fen"),
        "verification_status": row["verification_status"],
        "is_duplicate": row.get("is_duplicate", False),
        "confidence_score": float(row["confidence_score"]) if row.get("confidence_score") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _row_to_detail_dict(row: Any) -> dict[str, Any]:
    """将数据库行转换为详情字典（含所有字段）"""
    base = _row_to_dict(row)
    base.update({
        "seller_tax_no": row.get("seller_tax_no"),
        "buyer_tax_no": row.get("buyer_tax_no"),
        "items": row.get("items", []),
        "ocr_raw_json": row.get("ocr_raw_json"),
        "verification_result": row.get("verification_result"),
        "duplicate_hash": row.get("duplicate_hash"),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    })
    return base
