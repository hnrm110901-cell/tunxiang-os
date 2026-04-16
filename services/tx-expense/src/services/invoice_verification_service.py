"""
发票核验引擎服务
核心能力：
  1. OCR结构化识别（百度/阿里云，按环境变量切换）
  2. 金税四期真伪核验（<3秒，异步超时）
  3. 集团级去重（跨品牌跨门店SHA-256哈希唯一）
  4. 科目自动建议（Claude API语义分类）
  5. 税额合规性校验

安全约束：
  - 所有 API Key 从环境变量读取，绝不硬编码
  - OCR 图片不落盘，直接传 base64
  - 金税接口响应完整存档（verify_response）供审计

金额约定：所有金额均为分(fen)。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_enums import InvoiceType, OcrProvider, OcrStatus, VerifyStatus

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

_VAT_ALLOWED_TAX_RATES = {Decimal("0.01"), Decimal("0.03"), Decimal("0.06"), Decimal("0.09"), Decimal("0.13")}
_TAX_TOLERANCE_FEN = 2   # 允许误差：0.02元 = 2分
_QUOTA_INVOICE_MAX_FEN = 100_000  # 定额发票单张限额：1000元（单位：分），实际以税局规定为准

# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_amount_to_fen(amount_str: str) -> Optional[int]:
    """将OCR返回的金额字符串转为分（int）。如 '1,234.56' → 123456"""
    if not amount_str:
        return None
    try:
        cleaned = amount_str.replace(",", "").replace("¥", "").replace("￥", "").strip()
        yuan = Decimal(cleaned)
        return int(yuan * 100)
    except (InvalidOperation, ValueError):
        return None


def _parse_date_str(raw: str) -> Optional[str]:
    """将OCR返回的各种日期格式统一转为 YYYY-MM-DD，失败则返回 None。"""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# OCR 识别
# ─────────────────────────────────────────────────────────────────────────────

async def _get_baidu_access_token(client: httpx.AsyncClient) -> str:
    """用 API Key + Secret Key 换取百度 access_token（有效期30天）。"""
    api_key = os.environ.get("BAIDU_OCR_API_KEY", "")
    secret_key = os.environ.get("BAIDU_OCR_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise EnvironmentError("BAIDU_OCR_API_KEY 或 BAIDU_OCR_SECRET_KEY 未配置")

    resp = await client.post(
        "https://aip.baidubce.com/oauth/2.0/token",
        params={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"百度 OCR 鉴权失败：{data}")
    return token


async def _ocr_baidu(file_bytes: bytes) -> dict:
    """调用百度增值税发票OCR接口，返回标准化结构。"""
    img_b64 = base64.b64encode(file_bytes).decode("utf-8")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _get_baidu_access_token(client)
            resp = await client.post(
                "https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice",
                params={"access_token": token},
                data={"image": img_b64},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.TimeoutException as exc:
            log.warning("baidu_ocr_timeout", error=str(exc))
            return _ocr_error_result("baidu", "OCR请求超时（10秒）")
        except httpx.HTTPStatusError as exc:
            log.warning("baidu_ocr_http_error", status_code=exc.response.status_code, error=str(exc))
            return _ocr_error_result("baidu", f"HTTP错误：{exc.response.status_code}")
        except EnvironmentError as exc:
            log.warning("baidu_ocr_config_error", error=str(exc))
            return _ocr_error_result("baidu", str(exc))

    if "error_code" in raw:
        log.warning("baidu_ocr_api_error", error_code=raw.get("error_code"), msg=raw.get("error_msg"))
        return _ocr_error_result("baidu", raw.get("error_msg", "百度OCR接口错误"), raw_response=raw)

    words = raw.get("words_result", {})

    # 映射发票类型
    raw_type = words.get("InvoiceType", "")
    invoice_type = _map_baidu_invoice_type(raw_type)

    result = {
        "success": True,
        "provider": "baidu",
        "confidence": _extract_baidu_confidence(raw),
        "invoice_type": invoice_type,
        "invoice_code": words.get("InvoiceCode", {}).get("word") or None,
        "invoice_number": words.get("InvoiceNum", {}).get("word") or None,
        "invoice_date": _parse_date_str(words.get("InvoiceDate", {}).get("word", "")),
        "seller_name": words.get("SellerName", {}).get("word") or None,
        "seller_tax_id": words.get("SellerRegisterNum", {}).get("word") or None,
        "buyer_name": words.get("PurchaserName", {}).get("word") or None,
        "buyer_tax_id": words.get("PurchaserRegisterNum", {}).get("word") or None,
        "total_amount_fen": _parse_amount_to_fen(words.get("TotalAmount", {}).get("word", "")),
        "tax_amount_fen": _parse_amount_to_fen(words.get("TotalTax", {}).get("word", "")),
        "amount_without_tax_fen": _parse_amount_to_fen(words.get("AmountWithoutTax", {}).get("word", "")),
        "tax_rate": _parse_tax_rate(words.get("TaxRate", {}).get("word", "")),
        "items": _parse_baidu_items(words.get("CommodityName", []), words),
        "raw_response": raw,
        "error": None,
    }
    log.info("baidu_ocr_success", invoice_type=invoice_type, invoice_number=result["invoice_number"])
    return result


def _map_baidu_invoice_type(raw_type: str) -> str:
    mapping = {
        "增值税专用发票": InvoiceType.VAT_SPECIAL.value,
        "增值税普通发票": InvoiceType.VAT_GENERAL.value,
        "增值税电子普通发票": InvoiceType.VAT_GENERAL.value,
        "增值税电子专用发票": InvoiceType.VAT_SPECIAL.value,
        "定额发票": InvoiceType.QUOTA.value,
        "通用机打发票": InvoiceType.RECEIPT.value,
    }
    return mapping.get(raw_type, InvoiceType.OTHER.value)


def _extract_baidu_confidence(raw: dict) -> float:
    """从百度 OCR 返回中提取平均置信度，无则返回 0.8（默认高置信）。"""
    scores = []
    for v in raw.get("words_result", {}).values():
        if isinstance(v, dict) and "confidence" in v:
            scores.append(float(v["confidence"]))
    return round(sum(scores) / len(scores), 4) if scores else 0.80


def _parse_tax_rate(rate_str: str) -> Optional[float]:
    """'6%' → 0.06，'0.06' → 0.06，失败返回 None。"""
    if not rate_str:
        return None
    try:
        cleaned = rate_str.strip().replace("%", "")
        val = float(cleaned)
        if val > 1:
            val = val / 100
        return round(val, 4)
    except ValueError:
        return None


def _parse_baidu_items(commodity_names: list, words: dict) -> list:
    """尝试解析百度OCR的发票明细行（如果有结构化返回）。"""
    items = []
    commodity_amounts = words.get("CommodityAmount", [])
    commodity_taxes = words.get("CommodityTaxRate", [])
    for idx, name_obj in enumerate(commodity_names):
        if isinstance(name_obj, dict):
            name = name_obj.get("word", "")
        else:
            name = str(name_obj)
        amount_str = ""
        if idx < len(commodity_amounts) and isinstance(commodity_amounts[idx], dict):
            amount_str = commodity_amounts[idx].get("word", "")
        tax_rate_str = ""
        if idx < len(commodity_taxes) and isinstance(commodity_taxes[idx], dict):
            tax_rate_str = commodity_taxes[idx].get("word", "")
        items.append({
            "name": name,
            "amount_fen": _parse_amount_to_fen(amount_str),
            "tax_rate": _parse_tax_rate(tax_rate_str),
        })
    return items


async def _ocr_aliyun(file_bytes: bytes) -> dict:
    """调用阿里云发票OCR接口，返回标准化结构。"""
    endpoint = os.environ.get("ALIYUN_OCR_ENDPOINT", "")
    access_key_id = os.environ.get("ALIYUN_OCR_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("ALIYUN_OCR_ACCESS_KEY_SECRET", "")

    if not endpoint or not access_key_id or not access_key_secret:
        return _ocr_error_result("aliyun", "ALIYUN_OCR_ENDPOINT / ALIYUN_OCR_ACCESS_KEY_ID / ALIYUN_OCR_ACCESS_KEY_SECRET 未全部配置")

    img_b64 = base64.b64encode(file_bytes).decode("utf-8")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                endpoint,
                json={"image": img_b64},
                headers={
                    "Authorization": f"APPCODE {access_key_id}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.TimeoutException as exc:
            log.warning("aliyun_ocr_timeout", error=str(exc))
            return _ocr_error_result("aliyun", "OCR请求超时（10秒）")
        except httpx.HTTPStatusError as exc:
            log.warning("aliyun_ocr_http_error", status_code=exc.response.status_code)
            return _ocr_error_result("aliyun", f"HTTP错误：{exc.response.status_code}")

    # 阿里云 OCR 响应结构因产品不同而异，做通用适配
    if raw.get("code") not in (None, 0, "0", "Success"):
        return _ocr_error_result("aliyun", raw.get("message", "阿里云OCR接口错误"), raw_response=raw)

    data = raw.get("data", raw)

    result = {
        "success": True,
        "provider": "aliyun",
        "confidence": float(data.get("confidence", 0.80)),
        "invoice_type": _map_aliyun_invoice_type(data.get("invoiceType", "")),
        "invoice_code": data.get("invoiceCode") or None,
        "invoice_number": data.get("invoiceNumber") or None,
        "invoice_date": _parse_date_str(data.get("invoiceDate", "")),
        "seller_name": data.get("sellerName") or None,
        "seller_tax_id": data.get("sellerTaxNumber") or None,
        "buyer_name": data.get("buyerName") or None,
        "buyer_tax_id": data.get("buyerTaxNumber") or None,
        "total_amount_fen": _parse_amount_to_fen(str(data.get("totalAmount", ""))),
        "tax_amount_fen": _parse_amount_to_fen(str(data.get("taxAmount", ""))),
        "amount_without_tax_fen": _parse_amount_to_fen(str(data.get("amountWithoutTax", ""))),
        "tax_rate": _parse_tax_rate(str(data.get("taxRate", ""))),
        "items": data.get("items", []),
        "raw_response": raw,
        "error": None,
    }
    log.info("aliyun_ocr_success", invoice_type=result["invoice_type"], invoice_number=result["invoice_number"])
    return result


def _map_aliyun_invoice_type(raw_type: str) -> str:
    mapping = {
        "vat_invoice_special": InvoiceType.VAT_SPECIAL.value,
        "vat_invoice": InvoiceType.VAT_GENERAL.value,
        "quota_invoice": InvoiceType.QUOTA.value,
        "receipt": InvoiceType.RECEIPT.value,
    }
    return mapping.get(raw_type.lower(), InvoiceType.OTHER.value)


def _ocr_mock_result() -> dict:
    """Mock OCR 结果，用于开发/测试环境。"""
    return {
        "success": True,
        "provider": "mock",
        "confidence": 0.99,
        "invoice_type": InvoiceType.VAT_GENERAL.value,
        "invoice_code": "011001800311",
        "invoice_number": "12345678",
        "invoice_date": "2026-03-15",
        "seller_name": "测试餐饮供应商有限公司",
        "seller_tax_id": "91110108MA01ABCD12",
        "buyer_name": "屯象测试门店",
        "buyer_tax_id": "91430100MA4LTEST01",
        "total_amount_fen": 113000,      # 1130.00元
        "tax_amount_fen": 13000,          # 130.00元（税率约11.5%，示例数据）
        "amount_without_tax_fen": 100000, # 1000.00元
        "tax_rate": 0.13,
        "items": [
            {"name": "食材采购-猪肉", "amount_fen": 60000, "tax_rate": 0.09},
            {"name": "食材采购-蔬菜", "amount_fen": 40000, "tax_rate": 0.09},
        ],
        "raw_response": {"mock": True},
        "error": None,
    }


def _ocr_error_result(provider: str, error_msg: str, raw_response: Optional[dict] = None) -> dict:
    """统一的 OCR 失败结果结构。"""
    return {
        "success": False,
        "provider": provider,
        "confidence": 0.0,
        "invoice_type": None,
        "invoice_code": None,
        "invoice_number": None,
        "invoice_date": None,
        "seller_name": None,
        "seller_tax_id": None,
        "buyer_name": None,
        "buyer_tax_id": None,
        "total_amount_fen": None,
        "tax_amount_fen": None,
        "amount_without_tax_fen": None,
        "tax_rate": None,
        "items": [],
        "raw_response": raw_response or {},
        "error": error_msg,
    }


async def ocr_recognize(file_bytes: bytes, file_type: str, provider: str = None) -> dict:
    """
    发票OCR识别。
    provider: 'baidu'/'aliyun'/'mock'，默认从环境变量 OCR_PROVIDER 读取。

    返回标准化结构（无论哪个provider都返回相同格式）：
    {
      "success": bool,
      "provider": str,
      "confidence": float,          # 0.0-1.0
      "invoice_type": str,          # vat_special/vat_general/quota/receipt/other
      "invoice_code": str | None,
      "invoice_number": str | None,
      "invoice_date": str | None,   # YYYY-MM-DD
      "seller_name": str | None,
      "seller_tax_id": str | None,
      "buyer_name": str | None,
      "buyer_tax_id": str | None,
      "total_amount_fen": int | None,      # 分
      "tax_amount_fen": int | None,        # 分
      "amount_without_tax_fen": int | None,# 分
      "tax_rate": float | None,            # 0.06 表示6%
      "items": [...],                       # 明细行
      "raw_response": dict,                # provider原始返回
      "error": str | None,
    }
    """
    resolved_provider = (provider or os.environ.get("OCR_PROVIDER", OcrProvider.MOCK.value)).lower()

    log.info("ocr_recognize_start", provider=resolved_provider, file_type=file_type, file_size=len(file_bytes))

    if resolved_provider == OcrProvider.BAIDU.value:
        return await _ocr_baidu(file_bytes)
    elif resolved_provider == OcrProvider.ALIYUN.value:
        return await _ocr_aliyun(file_bytes)
    elif resolved_provider == OcrProvider.MOCK.value:
        return _ocr_mock_result()
    else:
        log.warning("ocr_unknown_provider", provider=resolved_provider)
        return _ocr_error_result(resolved_provider, f"未知的OCR提供商：{resolved_provider}")


# ─────────────────────────────────────────────────────────────────────────────
# 金税四期核验
# ─────────────────────────────────────────────────────────────────────────────

async def verify_with_tax_authority(
    invoice_code: str,
    invoice_number: str,
    invoice_date: str,    # YYYY-MM-DD
    total_amount_fen: int,
    buyer_tax_id: str = None,
) -> dict:
    """
    调用金税四期接口验真。
    环境变量：TAX_VERIFY_API_URL / TAX_VERIFY_API_KEY
    超时：3秒（用户等待场景，必须快速）

    返回：
    {
      "verified": bool,             # True=真票 False=假票
      "status": str,                # verified_real/verified_fake/verify_failed/skipped
      "message": str,               # 核验说明
      "raw_response": dict,
    }

    特殊处理：
    - 定额发票（无invoice_code/number）：直接返回 status=skipped
    - 接口超时：返回 status=verify_failed，message说明原因（不阻断流程）
    - TAX_VERIFY_API_URL 未配置：返回 status=skipped，message="金税接口未配置，跳过核验"
    """
    # 定额发票跳过核验
    if not invoice_code or not invoice_number:
        log.info("tax_verify_skipped", reason="quota_invoice_or_missing_fields")
        return {
            "verified": False,
            "status": VerifyStatus.SKIPPED.value,
            "message": "定额发票或缺少发票代码/号码，跳过核验",
            "raw_response": {},
        }

    api_url = os.environ.get("TAX_VERIFY_API_URL", "")
    api_key = os.environ.get("TAX_VERIFY_API_KEY", "")

    if not api_url:
        log.info("tax_verify_skipped", reason="api_url_not_configured")
        return {
            "verified": False,
            "status": VerifyStatus.SKIPPED.value,
            "message": "金税接口未配置，跳过核验",
            "raw_response": {},
        }

    # 金额从分转为元（字符串，保留两位小数）
    total_amount_yuan = str(Decimal(total_amount_fen) / 100)

    payload = {
        "invoice_code": invoice_code,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "total_amount": total_amount_yuan,
    }
    if buyer_tax_id:
        payload["buyer_tax_id"] = buyer_tax_id

    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            resp = await client.post(
                api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                },
                timeout=3.0,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.TimeoutException:
            log.warning("tax_verify_timeout", invoice_number=invoice_number)
            return {
                "verified": False,
                "status": VerifyStatus.VERIFY_FAILED.value,
                "message": "金税四期核验接口超时（3秒），请稍后重试",
                "raw_response": {},
            }
        except httpx.HTTPStatusError as exc:
            log.warning("tax_verify_http_error", status_code=exc.response.status_code, invoice_number=invoice_number)
            return {
                "verified": False,
                "status": VerifyStatus.VERIFY_FAILED.value,
                "message": f"金税四期核验接口HTTP错误：{exc.response.status_code}",
                "raw_response": {},
            }
        except httpx.RequestError as exc:
            log.warning("tax_verify_request_error", error=str(exc), invoice_number=invoice_number)
            return {
                "verified": False,
                "status": VerifyStatus.VERIFY_FAILED.value,
                "message": f"金税四期核验接口网络错误：{exc}",
                "raw_response": {},
            }

    # 解析核验结果（根据实际金税四期接口协议适配）
    verified = raw.get("verified", False) or raw.get("result") == "real"
    if verified:
        status = VerifyStatus.VERIFIED_REAL.value
        message = "金税四期核验通过，发票真实有效"
    else:
        status = VerifyStatus.VERIFIED_FAKE.value
        message = raw.get("message", "金税四期核验未通过，疑似虚假发票")

    log.info("tax_verify_done", status=status, invoice_number=invoice_number)
    return {
        "verified": verified,
        "status": status,
        "message": message,
        "raw_response": raw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 集团级去重
# ─────────────────────────────────────────────────────────────────────────────

def compute_dedup_hash(invoice_code: str, invoice_number: str, total_amount_fen: int) -> str:
    """
    计算发票去重哈希。
    SHA-256(invoice_code + ":" + invoice_number + ":" + str(total_amount_fen))
    """
    content = f"{invoice_code}:{invoice_number}:{total_amount_fen}"
    return hashlib.sha256(content.encode()).hexdigest()


async def check_duplicate(
    db: AsyncSession,
    tenant_id: UUID,
    dedup_hash: str,
    exclude_invoice_id: UUID = None,
) -> Optional[dict]:
    """
    集团级重复发票检查（跨品牌跨门店，全 tenant 范围）。
    返回：None（无重复）或 {"duplicate_invoice_id": UUID, "store_id": UUID, "uploaded_at": str}
    注意：这是集团级查重，不只查本门店！
    """
    query = """
        SELECT id, store_id, created_at
        FROM invoices
        WHERE tenant_id = :tenant_id
          AND dedup_hash = :dedup_hash
          AND is_deleted = FALSE
    """
    params: dict = {"tenant_id": str(tenant_id), "dedup_hash": dedup_hash}

    if exclude_invoice_id:
        query += " AND id != :exclude_id"
        params["exclude_id"] = str(exclude_invoice_id)

    query += " LIMIT 1"

    try:
        result = await db.execute(text(query), params)
        row = result.mappings().one_or_none()
    except (OperationalError, SQLAlchemyError) as exc:
        log.warning("check_duplicate_db_error", error=str(exc), dedup_hash=dedup_hash)
        return None

    if row is None:
        return None

    return {
        "duplicate_invoice_id": row["id"],
        "store_id": row["store_id"],
        "uploaded_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 科目自动建议（Claude API）
# ─────────────────────────────────────────────────────────────────────────────

async def suggest_category(
    seller_name: str,
    items_description: str,    # 发票明细商品名称拼接
    invoice_type: str,
    existing_categories: list[dict],  # [{"id": str, "name": str, "code": str}]
) -> dict:
    """
    调用 Claude API 分析发票内容，建议最合适的费用科目。
    环境变量：ANTHROPIC_API_KEY / CLAUDE_MODEL（默认 claude-haiku-4-5-20251001，低成本）

    返回：
    {
      "category_id": str | None,   # 建议的科目ID（从 existing_categories 中选）
      "category_name": str | None,
      "confidence": float,          # 0.0-1.0
      "reasoning": str,            # 简短推理说明
    }

    若 ANTHROPIC_API_KEY 未配置：返回 {"category_id": None, "confidence": 0, "reasoning": "AI科目建议未配置"}
    超时：5秒
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "category_id": None,
            "category_name": None,
            "confidence": 0.0,
            "reasoning": "AI科目建议未配置",
        }

    if not existing_categories:
        return {
            "category_id": None,
            "category_name": None,
            "confidence": 0.0,
            "reasoning": "科目列表为空，无法建议",
        }

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    categories_text = "\n".join(
        f"- ID={cat['id']}, 名称={cat['name']}, 代码={cat.get('code', '')}"
        for cat in existing_categories
    )
    prompt = (
        f"你是餐饮企业财务助手，请根据以下发票信息，从候选科目中选择最合适的一个费用科目。\n\n"
        f"发票信息：\n"
        f"- 销售方：{seller_name or '未知'}\n"
        f"- 商品/服务描述：{items_description or '无明细'}\n"
        f"- 发票类型：{invoice_type}\n\n"
        f"候选科目（请从以下选择一个）：\n{categories_text}\n\n"
        f"请以JSON格式返回，字段：category_id（选择的科目ID字符串）、confidence（0.0-1.0）、reasoning（一句话说明）。"
        f"只返回JSON，不要其他内容。"
    )

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model,
                    "max_tokens": 256,
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            log.warning("suggest_category_claude_timeout")
            return {
                "category_id": None,
                "category_name": None,
                "confidence": 0.0,
                "reasoning": "AI科目建议超时（5秒）",
            }
        except httpx.HTTPStatusError as exc:
            log.warning("suggest_category_claude_http_error", status_code=exc.response.status_code)
            return {
                "category_id": None,
                "category_name": None,
                "confidence": 0.0,
                "reasoning": f"AI接口HTTP错误：{exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.warning("suggest_category_claude_request_error", error=str(exc))
            return {
                "category_id": None,
                "category_name": None,
                "confidence": 0.0,
                "reasoning": f"AI接口网络错误：{exc}",
            }

    try:
        content_blocks = data.get("content", [])
        text_content = next(
            (blk["text"] for blk in content_blocks if blk.get("type") == "text"), ""
        )
        # 提取 JSON（防止模型返回 markdown 代码块）
        text_content = text_content.strip()
        if text_content.startswith("```"):
            text_content = text_content.split("```")[1]
            if text_content.startswith("json"):
                text_content = text_content[4:]
            text_content = text_content.strip()

        parsed = json.loads(text_content)
        suggested_id = parsed.get("category_id")
        confidence = float(parsed.get("confidence", 0.0))
        reasoning = parsed.get("reasoning", "")

        # 验证建议的ID确实在候选列表中
        matched_cat = next((c for c in existing_categories if c["id"] == suggested_id), None)
        if not matched_cat:
            log.warning("suggest_category_invalid_id", suggested_id=suggested_id)
            return {
                "category_id": None,
                "category_name": None,
                "confidence": 0.0,
                "reasoning": f"AI建议的科目ID不在候选列表中：{suggested_id}",
            }

        log.info("suggest_category_done", category_id=suggested_id, confidence=confidence)
        return {
            "category_id": suggested_id,
            "category_name": matched_cat["name"],
            "confidence": confidence,
            "reasoning": reasoning,
        }
    except (json.JSONDecodeError, KeyError, StopIteration, ValueError) as exc:
        log.warning("suggest_category_parse_error", error=str(exc))
        return {
            "category_id": None,
            "category_name": None,
            "confidence": 0.0,
            "reasoning": f"AI返回解析失败：{exc}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 税额合规性检查
# ─────────────────────────────────────────────────────────────────────────────

def check_tax_compliance(
    invoice_type: str,
    total_amount_fen: int,
    tax_amount_fen: int,
    tax_rate: float,
) -> list[str]:
    """
    检查税额计算是否合规。
    返回合规问题列表（空列表=无问题）：
    - "税额与税率不匹配：期望 {expected}元，实际 {actual}元（偏差 {rate}%）"
    - "专用发票税率不在允许范围（1%/3%/6%/9%/13%）"
    - "普通发票金额超过万元限额"（仅适用定额发票）
    允许误差：0.02元（分位四舍五入导致的偏差）
    """
    issues: list[str] = []

    if total_amount_fen is None or tax_amount_fen is None or tax_rate is None:
        return issues  # 数据不完整，跳过校验

    tax_rate_decimal = Decimal(str(tax_rate))
    total_fen_dec = Decimal(str(total_amount_fen))
    tax_fen_dec = Decimal(str(tax_amount_fen))

    # 校验1：税额与税率一致性
    # 含税总额 = 不含税金额 × (1 + 税率) → 税额 = 总额 - 总额/(1+税率) = 总额 × 税率/(1+税率)
    if tax_rate_decimal > 0:
        expected_tax_fen = (total_fen_dec * tax_rate_decimal / (1 + tax_rate_decimal)).to_integral_value()
        deviation_fen = abs(tax_fen_dec - expected_tax_fen)
        if deviation_fen > _TAX_TOLERANCE_FEN:
            expected_yuan = float(expected_tax_fen) / 100
            actual_yuan = float(tax_fen_dec) / 100
            deviation_rate = float(deviation_fen / expected_tax_fen * 100) if expected_tax_fen != 0 else 0.0
            issues.append(
                f"税额与税率不匹配：期望 {expected_yuan:.2f}元，实际 {actual_yuan:.2f}元"
                f"（偏差 {deviation_rate:.2f}%）"
            )

    # 校验2：增值税专用发票税率范围
    if invoice_type == InvoiceType.VAT_SPECIAL.value:
        if tax_rate_decimal not in _VAT_ALLOWED_TAX_RATES:
            rates_str = "/".join(str(int(r * 100)) + "%" for r in sorted(_VAT_ALLOWED_TAX_RATES))
            issues.append(
                f"专用发票税率不在允许范围（{rates_str}），实际税率：{int(tax_rate_decimal * 100)}%"
            )

    # 校验3：定额发票单张金额超限
    if invoice_type == InvoiceType.QUOTA.value:
        if total_amount_fen > _QUOTA_INVOICE_MAX_FEN:
            issues.append(
                f"定额发票金额超过单张限额：实际 {total_amount_fen / 100:.2f}元，"
                f"限额 {_QUOTA_INVOICE_MAX_FEN / 100:.2f}元"
            )

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# 核心流程：上传并处理发票
# ─────────────────────────────────────────────────────────────────────────────

async def process_invoice_upload(
    db: AsyncSession,
    tenant_id: UUID,
    brand_id: UUID,
    store_id: UUID,
    uploader_id: UUID,
    file_bytes: bytes,
    file_name: str,
    file_type: str,
    file_url: str,          # 已上传到Supabase Storage的URL
    file_size: int,
    application_id: UUID = None,
    expected_amount_fen: int = None,   # 申请单中预期金额，用于比对
) -> dict:
    """
    发票上传完整处理流程：
    1. 创建 Invoice 记录（ocr_status=PENDING）
    2. 异步并行执行：OCR识别 + （若有invoice_code则）金税核验
    3. 更新 Invoice 字段（OCR结果 + 核验结果）
    4. 计算 dedup_hash，检查集团去重
    5. 若有 expected_amount_fen：比对金额（deviation > 1% 则标记）
    6. 获取科目列表，调用 suggest_category
    7. 校验发票日期合规性（是否在当年内）
    8. 更新 Invoice 最终状态
    9. 创建 InvoiceItem 记录（如果OCR解析出明细）
    10. 返回完整处理结果
    """
    invoice_id = uuid.uuid4()
    compliance_issues: list[str] = []
    needs_manual_review = False

    log.info(
        "invoice_upload_start",
        invoice_id=str(invoice_id),
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        file_name=file_name,
        file_size=file_size,
    )

    # ── Step 1: 创建 Invoice 记录（ocr_status=PENDING）──────────────────────
    try:
        await db.execute(
            text("""
                INSERT INTO invoices (
                    id, tenant_id, brand_id, store_id, uploader_id,
                    application_id, file_name, file_type, file_url, file_size,
                    ocr_status, verify_status, is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :brand_id, :store_id, :uploader_id,
                    :application_id, :file_name, :file_type, :file_url, :file_size,
                    :ocr_status, :verify_status, FALSE, NOW(), NOW()
                )
            """),
            {
                "id": str(invoice_id),
                "tenant_id": str(tenant_id),
                "brand_id": str(brand_id),
                "store_id": str(store_id),
                "uploader_id": str(uploader_id),
                "application_id": str(application_id) if application_id else None,
                "file_name": file_name,
                "file_type": file_type,
                "file_url": file_url,
                "file_size": file_size,
                "ocr_status": OcrStatus.PENDING.value,
                "verify_status": VerifyStatus.PENDING.value,
            },
        )
        await db.flush()
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("invoice_create_db_error", error=str(exc), invoice_id=str(invoice_id), exc_info=True)
        return {
            "invoice_id": str(invoice_id),
            "ocr_success": False,
            "verify_status": VerifyStatus.SKIPPED.value,
            "is_duplicate": False,
            "duplicate_of": None,
            "amount_matched": None,
            "amount_deviation_rate": None,
            "suggested_category": None,
            "compliance_issues": [f"数据库写入失败：{exc}"],
            "needs_manual_review": True,
        }

    # 更新状态为处理中
    await _update_invoice_field(db, invoice_id, "ocr_status", OcrStatus.PROCESSING.value)

    # ── Step 2: 并行执行 OCR 识别（金税核验需等 OCR 结果）──────────────────
    ocr_result = await ocr_recognize(file_bytes, file_type)

    invoice_code = ocr_result.get("invoice_code")
    invoice_number = ocr_result.get("invoice_number")
    invoice_date_str = ocr_result.get("invoice_date")
    invoice_type = ocr_result.get("invoice_type") or InvoiceType.OTHER.value
    total_amount_fen = ocr_result.get("total_amount_fen")
    tax_amount_fen = ocr_result.get("tax_amount_fen")
    tax_rate = ocr_result.get("tax_rate")

    # 并行执行金税核验（仅当 OCR 成功且有发票代码时）
    if ocr_result["success"] and invoice_code and invoice_number and invoice_date_str and total_amount_fen:
        verify_task = asyncio.create_task(
            verify_with_tax_authority(
                invoice_code=invoice_code,
                invoice_number=invoice_number,
                invoice_date=invoice_date_str,
                total_amount_fen=total_amount_fen,
                buyer_tax_id=ocr_result.get("buyer_tax_id"),
            )
        )
        verify_result = await verify_task
    else:
        verify_result = {
            "verified": False,
            "status": VerifyStatus.SKIPPED.value,
            "message": "OCR失败或缺少必要字段，跳过金税核验",
            "raw_response": {},
        }

    # ── Step 3: 更新 Invoice OCR + 核验字段 ─────────────────────────────────
    ocr_status = OcrStatus.SUCCESS.value if ocr_result["success"] else OcrStatus.FAILED.value
    verify_status = verify_result["status"]

    try:
        await db.execute(
            text("""
                UPDATE invoices SET
                    ocr_status = :ocr_status,
                    ocr_provider = :ocr_provider,
                    invoice_type = :invoice_type,
                    invoice_code = :invoice_code,
                    invoice_number = :invoice_number,
                    invoice_date = :invoice_date,
                    seller_name = :seller_name,
                    seller_tax_id = :seller_tax_id,
                    buyer_name = :buyer_name,
                    buyer_tax_id = :buyer_tax_id,
                    total_amount = :total_amount,
                    tax_amount = :tax_amount,
                    amount_without_tax = :amount_without_tax,
                    tax_rate = :tax_rate,
                    ocr_confidence = :ocr_confidence,
                    ocr_raw_response = :ocr_raw_response,
                    verify_status = :verify_status,
                    verify_response = :verify_response,
                    updated_at = NOW()
                WHERE id = :invoice_id AND tenant_id = :tenant_id
            """),
            {
                "ocr_status": ocr_status,
                "ocr_provider": ocr_result.get("provider"),
                "invoice_type": invoice_type,
                "invoice_code": invoice_code,
                "invoice_number": invoice_number,
                "invoice_date": invoice_date_str,
                "seller_name": ocr_result.get("seller_name"),
                "seller_tax_id": ocr_result.get("seller_tax_id"),
                "buyer_name": ocr_result.get("buyer_name"),
                "buyer_tax_id": ocr_result.get("buyer_tax_id"),
                "total_amount": total_amount_fen,
                "tax_amount": tax_amount_fen,
                "amount_without_tax": ocr_result.get("amount_without_tax_fen"),
                "tax_rate": tax_rate,
                "ocr_confidence": ocr_result.get("confidence"),
                "ocr_raw_response": json.dumps(ocr_result.get("raw_response", {}), ensure_ascii=False),
                "verify_status": verify_status,
                "verify_response": json.dumps(verify_result.get("raw_response", {}), ensure_ascii=False),
                "invoice_id": str(invoice_id),
                "tenant_id": str(tenant_id),
            },
        )
        await db.flush()
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("invoice_update_ocr_error", error=str(exc), invoice_id=str(invoice_id), exc_info=True)
        compliance_issues.append(f"OCR结果写入失败：{exc}")
        needs_manual_review = True

    # ── Step 4: 集团去重 ─────────────────────────────────────────────────────
    is_duplicate = False
    duplicate_of = None

    if invoice_code and invoice_number and total_amount_fen:
        dedup_hash = compute_dedup_hash(invoice_code, invoice_number, total_amount_fen)
        duplicate_info = await check_duplicate(db, tenant_id, dedup_hash, exclude_invoice_id=invoice_id)
        if duplicate_info:
            is_duplicate = True
            duplicate_of = duplicate_info
            compliance_issues.append(
                f"发现重复发票：已存在发票ID {duplicate_info['duplicate_invoice_id']}，"
                f"上传时间 {duplicate_info['uploaded_at']}"
            )
            needs_manual_review = True
            await _update_invoice_field(db, invoice_id, "dedup_hash", dedup_hash)
            await _update_invoice_field(db, invoice_id, "is_duplicate", True)
            log.warning("invoice_duplicate_found", invoice_id=str(invoice_id), duplicate_of=str(duplicate_info["duplicate_invoice_id"]))
        else:
            await _update_invoice_field(db, invoice_id, "dedup_hash", dedup_hash)

    # ── Step 5: 金额比对 ─────────────────────────────────────────────────────
    amount_matched: Optional[bool] = None
    amount_deviation_rate: Optional[float] = None

    if expected_amount_fen and total_amount_fen:
        deviation_fen = abs(total_amount_fen - expected_amount_fen)
        amount_deviation_rate = round(deviation_fen / expected_amount_fen, 4) if expected_amount_fen else 0.0
        amount_matched = amount_deviation_rate <= 0.01  # 允许1%偏差
        if not amount_matched:
            compliance_issues.append(
                f"发票金额与申请金额不匹配：发票 {total_amount_fen / 100:.2f}元，"
                f"申请 {expected_amount_fen / 100:.2f}元（偏差 {amount_deviation_rate * 100:.2f}%）"
            )
            needs_manual_review = True

    # ── Step 6: 科目自动建议 ─────────────────────────────────────────────────
    suggested_category: Optional[dict] = None
    try:
        categories = await _fetch_categories(db, tenant_id)
        if categories and ocr_result["success"]:
            items_desc = "；".join(
                item.get("name", "") for item in ocr_result.get("items", []) if item.get("name")
            )
            suggested_category = await suggest_category(
                seller_name=ocr_result.get("seller_name", ""),
                items_description=items_desc,
                invoice_type=invoice_type,
                existing_categories=categories,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("suggest_category_error", error=str(exc), invoice_id=str(invoice_id))

    # ── Step 7: 发票日期合规性 ───────────────────────────────────────────────
    if invoice_date_str:
        try:
            inv_date = datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
            current_year = date.today().year
            if inv_date.year != current_year:
                compliance_issues.append(
                    f"发票日期不在当年（{current_year}年）：发票日期为 {invoice_date_str}"
                )
                needs_manual_review = True
            if inv_date > date.today():
                compliance_issues.append(f"发票日期 {invoice_date_str} 为未来日期，疑似虚假发票")
                needs_manual_review = True
        except ValueError:
            compliance_issues.append(f"发票日期格式无法解析：{invoice_date_str}")

    # ── 税额合规性 ────────────────────────────────────────────────────────────
    if total_amount_fen and tax_amount_fen and tax_rate:
        tax_issues = check_tax_compliance(invoice_type, total_amount_fen, tax_amount_fen, tax_rate)
        compliance_issues.extend(tax_issues)
        if tax_issues:
            needs_manual_review = True

    # 假票强制人工复核
    if verify_status == VerifyStatus.VERIFIED_FAKE.value:
        needs_manual_review = True
        compliance_issues.append("金税四期核验为假票，需人工复核")

    # ── Step 8: 更新最终状态 ─────────────────────────────────────────────────
    try:
        await db.execute(
            text("""
                UPDATE invoices SET
                    compliance_issues = :compliance_issues,
                    needs_manual_review = :needs_manual_review,
                    suggested_category_id = :suggested_category_id,
                    updated_at = NOW()
                WHERE id = :invoice_id AND tenant_id = :tenant_id
            """),
            {
                "compliance_issues": json.dumps(compliance_issues, ensure_ascii=False),
                "needs_manual_review": needs_manual_review,
                "suggested_category_id": suggested_category.get("category_id") if suggested_category else None,
                "invoice_id": str(invoice_id),
                "tenant_id": str(tenant_id),
            },
        )
        await db.flush()
    except (OperationalError, SQLAlchemyError) as exc:
        log.warning("invoice_update_final_status_error", error=str(exc), invoice_id=str(invoice_id))

    # ── Step 9: 写入 InvoiceItem 明细 ────────────────────────────────────────
    ocr_items = ocr_result.get("items", [])
    if ocr_items and ocr_result["success"]:
        await _create_invoice_items(db, invoice_id, tenant_id, ocr_items)

    # ── Step 10: 集团级跨品牌去重检查 ────────────────────────────────────────
    # 仅当 OCR 识别出 invoice_code + invoice_number 时才执行（定额发票等跳过）
    group_dedup_result: Optional[dict] = None
    if invoice_code and invoice_number:
        try:
            from .invoice_dedup_service import invoice_dedup_service as _dedup_svc
            group_dedup_result = await _dedup_svc.check_group_dedup(
                db=db,
                invoice_code=invoice_code,
                invoice_number=invoice_number,
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                expense_application_id=application_id,
            )
            if group_dedup_result.get("is_duplicate"):
                # 在 invoices 记录的 notes 字段追加集团去重警告
                warning_note = (
                    f"[集团去重警告] {group_dedup_result.get('message', '跨品牌重复发票')}"
                )
                try:
                    await db.execute(
                        text("""
                            UPDATE invoices SET
                                notes = CASE
                                    WHEN notes IS NULL OR notes = '' THEN :note
                                    ELSE notes || '；' || :note
                                END,
                                updated_at = NOW()
                            WHERE id = :invoice_id AND tenant_id = :tenant_id
                        """),
                        {
                            "note": warning_note,
                            "invoice_id": str(invoice_id),
                            "tenant_id": str(tenant_id),
                        },
                    )
                    await db.flush()
                except (OperationalError, SQLAlchemyError) as exc:
                    log.error(
                        "invoice_group_dedup_note_update_error",
                        error=str(exc),
                        invoice_id=str(invoice_id),
                        exc_info=True,
                    )

                compliance_issues.append(warning_note)
                needs_manual_review = True
        except (OperationalError, SQLAlchemyError, ValueError) as exc:
            # 集团去重失败不阻断主流程，降级处理
            log.error(
                "invoice_group_dedup_check_error",
                error=str(exc),
                invoice_id=str(invoice_id),
                invoice_code=invoice_code,
                invoice_number=invoice_number,
                exc_info=True,
            )

    log.info(
        "invoice_upload_done",
        invoice_id=str(invoice_id),
        ocr_success=ocr_result["success"],
        verify_status=verify_status,
        is_duplicate=is_duplicate,
        group_dedup_is_duplicate=group_dedup_result.get("is_duplicate") if group_dedup_result else None,
        compliance_issues_count=len(compliance_issues),
        needs_manual_review=needs_manual_review,
    )

    return {
        "invoice_id": str(invoice_id),
        "ocr_success": ocr_result["success"],
        "verify_status": verify_status,
        "is_duplicate": is_duplicate,
        "duplicate_of": duplicate_of,
        "amount_matched": amount_matched,
        "amount_deviation_rate": amount_deviation_rate,
        "suggested_category": suggested_category,
        "compliance_issues": compliance_issues,
        "needs_manual_review": needs_manual_review,
        "group_dedup": group_dedup_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 批量重新核验（管理端）
# ─────────────────────────────────────────────────────────────────────────────

async def reverify_invoices(
    db: AsyncSession,
    tenant_id: UUID,
    invoice_ids: list[UUID],
) -> dict:
    """
    批量重新触发金税核验（适用于接口恢复后补核验）。
    并发限制：最多5个并发（避免接口限流）。
    返回：{"success": N, "failed": N, "skipped": N}
    """
    if not invoice_ids:
        return {"success": 0, "failed": 0, "skipped": 0}

    log.info("reverify_invoices_start", tenant_id=str(tenant_id), count=len(invoice_ids))

    # 查询需要核验的发票信息
    ids_str = ",".join(f"'{str(iid)}'" for iid in invoice_ids)
    query = text(f"""
        SELECT id, invoice_code, invoice_number, invoice_date, total_amount, buyer_tax_id
        FROM invoices
        WHERE tenant_id = :tenant_id
          AND id IN ({ids_str})
          AND is_deleted = FALSE
    """)
    try:
        result = await db.execute(query, {"tenant_id": str(tenant_id)})
        rows = result.mappings().all()
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("reverify_invoices_query_error", error=str(exc), exc_info=True)
        return {"success": 0, "failed": len(invoice_ids), "skipped": 0}

    success_count = 0
    failed_count = 0
    skipped_count = 0
    semaphore = asyncio.Semaphore(5)  # 最多5个并发

    async def _reverify_one(row: dict) -> None:
        nonlocal success_count, failed_count, skipped_count

        iid = row["id"]
        async with semaphore:
            try:
                verify_result = await verify_with_tax_authority(
                    invoice_code=row.get("invoice_code", ""),
                    invoice_number=row.get("invoice_number", ""),
                    invoice_date=(
                        row["invoice_date"].strftime("%Y-%m-%d")
                        if row.get("invoice_date") else ""
                    ),
                    total_amount_fen=row.get("total_amount") or 0,
                    buyer_tax_id=row.get("buyer_tax_id"),
                )
                new_status = verify_result["status"]

                await db.execute(
                    text("""
                        UPDATE invoices SET
                            verify_status = :status,
                            verify_response = :response,
                            updated_at = NOW()
                        WHERE id = :iid AND tenant_id = :tenant_id
                    """),
                    {
                        "status": new_status,
                        "response": json.dumps(verify_result.get("raw_response", {}), ensure_ascii=False),
                        "iid": str(iid),
                        "tenant_id": str(tenant_id),
                    },
                )
                await db.flush()

                if new_status == VerifyStatus.SKIPPED.value:
                    skipped_count += 1
                elif new_status == VerifyStatus.VERIFY_FAILED.value:
                    failed_count += 1
                else:
                    success_count += 1

                log.info("reverify_one_done", invoice_id=str(iid), new_status=new_status)

            except (OperationalError, SQLAlchemyError, OSError, RuntimeError) as exc:
                failed_count += 1
                log.error("reverify_one_error", invoice_id=str(iid), error=str(exc), exc_info=True)

    await asyncio.gather(*[_reverify_one(dict(row)) for row in rows])

    # 未查到的 ID 算跳过
    found_ids = {str(row["id"]) for row in rows}
    not_found = [iid for iid in invoice_ids if str(iid) not in found_ids]
    skipped_count += len(not_found)

    log.info(
        "reverify_invoices_done",
        tenant_id=str(tenant_id),
        success=success_count,
        failed=failed_count,
        skipped=skipped_count,
    )
    return {"success": success_count, "failed": failed_count, "skipped": skipped_count}


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助方法
# ─────────────────────────────────────────────────────────────────────────────

async def _update_invoice_field(db: AsyncSession, invoice_id: UUID, field: str, value) -> None:
    """单字段更新发票记录，封装重复SQL。"""
    try:
        await db.execute(
            text(f"UPDATE invoices SET {field} = :{field}, updated_at = NOW() WHERE id = :invoice_id"),
            {field: value, "invoice_id": str(invoice_id)},
        )
        await db.flush()
    except (OperationalError, SQLAlchemyError) as exc:
        log.warning("update_invoice_field_error", field=field, invoice_id=str(invoice_id), error=str(exc))


async def _fetch_categories(db: AsyncSession, tenant_id: UUID) -> list[dict]:
    """查询租户科目列表，用于科目建议。"""
    try:
        result = await db.execute(
            text("""
                SELECT id::text, name, code
                FROM expense_categories
                WHERE tenant_id = :tenant_id
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                ORDER BY sort_order ASC
            """),
            {"tenant_id": str(tenant_id)},
        )
        return [{"id": row["id"], "name": row["name"], "code": row["code"]} for row in result.mappings().all()]
    except (OperationalError, SQLAlchemyError) as exc:
        log.warning("fetch_categories_error", error=str(exc), tenant_id=str(tenant_id))
        return []


async def _create_invoice_items(
    db: AsyncSession,
    invoice_id: UUID,
    tenant_id: UUID,
    items: list[dict],
) -> None:
    """批量写入 InvoiceItem 发票明细行。"""
    if not items:
        return
    for item in items:
        item_id = uuid.uuid4()
        try:
            await db.execute(
                text("""
                    INSERT INTO invoice_items (
                        id, tenant_id, invoice_id, name, amount, tax_rate,
                        is_deleted, created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :invoice_id, :name, :amount, :tax_rate,
                        FALSE, NOW(), NOW()
                    )
                """),
                {
                    "id": str(item_id),
                    "tenant_id": str(tenant_id),
                    "invoice_id": str(invoice_id),
                    "name": item.get("name", ""),
                    "amount": item.get("amount_fen"),
                    "tax_rate": item.get("tax_rate"),
                },
            )
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning(
                "create_invoice_item_error",
                invoice_id=str(invoice_id),
                item_name=item.get("name"),
                error=str(exc),
            )
    try:
        await db.flush()
    except (OperationalError, SQLAlchemyError) as exc:
        log.warning("create_invoice_items_flush_error", invoice_id=str(invoice_id), error=str(exc))
