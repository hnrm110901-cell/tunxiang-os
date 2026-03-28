"""平台团购核销引擎 — 美团/抖音/口碑/广发银行

徐记海鲜每日高频操作：聚合核销（扫码自动识别平台）。
团购券码格式：
  - 美团：纯数字18位
  - 抖音：DY 开头
  - 口碑：KB 开头
  - 广发银行：GF 开头

注：平台 API 对接为 mock 实现，生产环境需配置各平台 API Key。
核销记录必须关联 order_id，确保财务对账闭环。
"""
import re
import uuid
from datetime import datetime, date, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 平台券码格式识别规则 ───

PLATFORM_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("meituan", re.compile(r"^\d{18}$"), "美团"),
    ("douyin", re.compile(r"^DY[A-Za-z0-9]+$"), "抖音"),
    ("koubei", re.compile(r"^KB[A-Za-z0-9]+$"), "口碑"),
    ("bank_gf", re.compile(r"^GF[A-Za-z0-9]+$"), "广发银行"),
]


# ─── 内存存储（mock，生产替换为数据库表） ───


class _PlatformCouponStore:
    """平台团购券存储"""

    _coupons: dict[str, dict] = {}

    @classmethod
    def save(cls, code: str, data: dict) -> None:
        cls._coupons[code] = data

    @classmethod
    def get(cls, code: str) -> Optional[dict]:
        return cls._coupons.get(code)

    @classmethod
    def list_by_store(
        cls,
        store_id: str,
        start_date: date,
        end_date: date,
        platform: Optional[str] = None,
    ) -> list[dict]:
        results = []
        for data in cls._coupons.values():
            if data.get("store_id") != store_id:
                continue
            if data.get("status") != "redeemed":
                continue
            if platform and data.get("platform") != platform:
                continue
            redeemed_at = data.get("redeemed_at")
            if redeemed_at:
                rd = datetime.fromisoformat(redeemed_at).date()
                if start_date <= rd <= end_date:
                    results.append(data)
        return results

    @classmethod
    def clear(cls) -> None:
        cls._coupons.clear()


# ─── 平台识别 ───


def identify_platform(code: str) -> Optional[str]:
    """根据券码格式自动识别平台

    Returns:
        平台标识 (meituan/douyin/koubei/bank_gf) 或 None
    """
    for platform_id, pattern, _ in PLATFORM_PATTERNS:
        if pattern.match(code):
            return platform_id
    return None


def _platform_display_name(platform: str) -> str:
    """获取平台中文名"""
    mapping = {
        "meituan": "美团",
        "douyin": "抖音",
        "koubei": "口碑",
        "bank_gf": "广发银行",
    }
    return mapping.get(platform, platform)


# ─── 各平台验证（mock） ───


async def verify_meituan_coupon(
    code: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """美团到餐团购验证（mock）

    生产环境对接美团到餐开放平台 API。
    """
    coupon = _PlatformCouponStore.get(code)
    if not coupon:
        # mock: 未预置的券码模拟美团 API 返回有效
        coupon = {
            "code": code,
            "platform": "meituan",
            "platform_name": "美团",
            "deal_name": "美团团购套餐",
            "deal_amount_fen": 19800,
            "status": "valid",
            "store_id": store_id,
            "tenant_id": tenant_id,
            "expires_at": None,
        }
        _PlatformCouponStore.save(code, coupon)

    if coupon.get("tenant_id") != tenant_id:
        return {"valid": False, "code": code, "platform": "meituan", "reason": "租户不匹配"}
    if coupon.get("status") not in ("valid", "active"):
        return {
            "valid": False,
            "code": code,
            "platform": "meituan",
            "reason": f"券状态异常: {coupon.get('status')}",
        }

    logger.info(
        "meituan_coupon_verified",
        code=code,
        deal_name=coupon.get("deal_name"),
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return {
        "valid": True,
        "code": code,
        "platform": "meituan",
        "platform_name": "美团",
        "deal_name": coupon.get("deal_name"),
        "deal_amount_fen": coupon.get("deal_amount_fen", 0),
    }


async def verify_douyin_coupon(
    code: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """抖音团购验证（mock）

    生产环境对接抖音本地生活开放平台 API。
    """
    coupon = _PlatformCouponStore.get(code)
    if not coupon:
        coupon = {
            "code": code,
            "platform": "douyin",
            "platform_name": "抖音",
            "deal_name": "抖音团购套餐",
            "deal_amount_fen": 16800,
            "status": "valid",
            "store_id": store_id,
            "tenant_id": tenant_id,
            "expires_at": None,
        }
        _PlatformCouponStore.save(code, coupon)

    if coupon.get("tenant_id") != tenant_id:
        return {"valid": False, "code": code, "platform": "douyin", "reason": "租户不匹配"}
    if coupon.get("status") not in ("valid", "active"):
        return {
            "valid": False,
            "code": code,
            "platform": "douyin",
            "reason": f"券状态异常: {coupon.get('status')}",
        }

    logger.info(
        "douyin_coupon_verified",
        code=code,
        deal_name=coupon.get("deal_name"),
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return {
        "valid": True,
        "code": code,
        "platform": "douyin",
        "platform_name": "抖音",
        "deal_name": coupon.get("deal_name"),
        "deal_amount_fen": coupon.get("deal_amount_fen", 0),
    }


async def verify_koubei_coupon(
    code: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """口碑团购验证（mock）

    生产环境对接支付宝口碑开放平台 API。
    """
    coupon = _PlatformCouponStore.get(code)
    if not coupon:
        coupon = {
            "code": code,
            "platform": "koubei",
            "platform_name": "口碑",
            "deal_name": "口碑团购套餐",
            "deal_amount_fen": 15800,
            "status": "valid",
            "store_id": store_id,
            "tenant_id": tenant_id,
            "expires_at": None,
        }
        _PlatformCouponStore.save(code, coupon)

    if coupon.get("tenant_id") != tenant_id:
        return {"valid": False, "code": code, "platform": "koubei", "reason": "租户不匹配"}
    if coupon.get("status") not in ("valid", "active"):
        return {
            "valid": False,
            "code": code,
            "platform": "koubei",
            "reason": f"券状态异常: {coupon.get('status')}",
        }

    logger.info(
        "koubei_coupon_verified",
        code=code,
        deal_name=coupon.get("deal_name"),
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return {
        "valid": True,
        "code": code,
        "platform": "koubei",
        "platform_name": "口碑",
        "deal_name": coupon.get("deal_name"),
        "deal_amount_fen": coupon.get("deal_amount_fen", 0),
    }


async def verify_bank_coupon(
    code: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """银行团购验证（mock）— 广发银行

    生产环境对接银行优惠券核销 API。
    """
    coupon = _PlatformCouponStore.get(code)
    if not coupon:
        coupon = {
            "code": code,
            "platform": "bank_gf",
            "platform_name": "广发银行",
            "deal_name": "广发银行信用卡优惠套餐",
            "deal_amount_fen": 29800,
            "status": "valid",
            "store_id": store_id,
            "tenant_id": tenant_id,
            "expires_at": None,
        }
        _PlatformCouponStore.save(code, coupon)

    if coupon.get("tenant_id") != tenant_id:
        return {"valid": False, "code": code, "platform": "bank_gf", "reason": "租户不匹配"}
    if coupon.get("status") not in ("valid", "active"):
        return {
            "valid": False,
            "code": code,
            "platform": "bank_gf",
            "reason": f"券状态异常: {coupon.get('status')}",
        }

    logger.info(
        "bank_coupon_verified",
        code=code,
        deal_name=coupon.get("deal_name"),
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return {
        "valid": True,
        "code": code,
        "platform": "bank_gf",
        "platform_name": "广发银行",
        "deal_name": coupon.get("deal_name"),
        "deal_amount_fen": coupon.get("deal_amount_fen", 0),
    }


# ─── 平台验证路由 ───

_PLATFORM_VERIFIERS = {
    "meituan": verify_meituan_coupon,
    "douyin": verify_douyin_coupon,
    "koubei": verify_koubei_coupon,
    "bank_gf": verify_bank_coupon,
}


# ─── 聚合核销 ───


async def aggregate_verify(
    code: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """聚合验证 — 扫一次自动识别平台 + 验证

    收银员只需扫码，系统自动识别美团/抖音/口碑/广发银行并调用对应验证。
    """
    platform = identify_platform(code)
    if not platform:
        logger.warning(
            "platform_not_identified",
            code=code,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        return {
            "valid": False,
            "code": code,
            "platform": None,
            "reason": "无法识别券码平台，请检查券码格式",
        }

    verifier = _PLATFORM_VERIFIERS[platform]
    result = await verifier(code, store_id, tenant_id, db)

    logger.info(
        "aggregate_verify_completed",
        code=code,
        platform=platform,
        valid=result.get("valid"),
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return result


async def redeem_coupon(
    platform: str,
    code: str,
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """统一核销 — 标记已使用并关联 order_id

    核销记录必须关联 order_id，确保财务对账闭环。
    """
    if not order_id:
        raise ValueError("核销必须关联 order_id")

    coupon = _PlatformCouponStore.get(code)
    if not coupon:
        raise ValueError(f"券不存在: {code}")

    if coupon.get("tenant_id") != tenant_id:
        raise ValueError("租户不匹配")

    if coupon.get("status") not in ("valid", "active"):
        raise ValueError(f"券状态异常，无法核销: {coupon.get('status')}")

    if coupon.get("platform") != platform:
        raise ValueError(
            f"平台不匹配: 券属于 {coupon.get('platform')}，"
            f"请求核销平台为 {platform}"
        )

    now = datetime.now(timezone.utc)
    coupon["status"] = "redeemed"
    coupon["redeemed_at"] = now.isoformat()
    coupon["redeemed_order_id"] = order_id
    _PlatformCouponStore.save(code, coupon)

    logger.info(
        "platform_coupon_redeemed",
        code=code,
        platform=platform,
        order_id=order_id,
        deal_amount_fen=coupon.get("deal_amount_fen", 0),
        tenant_id=tenant_id,
    )
    return {
        "code": code,
        "platform": platform,
        "platform_name": _platform_display_name(platform),
        "order_id": order_id,
        "deal_name": coupon.get("deal_name"),
        "deal_amount_fen": coupon.get("deal_amount_fen", 0),
        "redeemed_at": coupon["redeemed_at"],
    }


# ─── 核销对账报告 ───


async def get_redemption_report(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """核销对账报告 — 按平台/日期汇总核销记录"""
    start_date = date.fromisoformat(date_range[0])
    end_date = date.fromisoformat(date_range[1])

    records = _PlatformCouponStore.list_by_store(store_id, start_date, end_date)

    total_amount_fen = sum(r.get("deal_amount_fen", 0) for r in records)

    # 按平台分组统计
    by_platform: dict[str, dict] = {}
    for r in records:
        p = r.get("platform", "unknown")
        if p not in by_platform:
            by_platform[p] = {
                "platform_name": _platform_display_name(p),
                "count": 0,
                "total_amount_fen": 0,
            }
        by_platform[p]["count"] += 1
        by_platform[p]["total_amount_fen"] += r.get("deal_amount_fen", 0)

    logger.info(
        "redemption_report_generated",
        store_id=store_id,
        date_range=date_range,
        record_count=len(records),
        total_amount_fen=total_amount_fen,
        tenant_id=tenant_id,
    )
    return {
        "store_id": store_id,
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "record_count": len(records),
        "total_amount_fen": total_amount_fen,
        "by_platform": by_platform,
        "records": [
            {
                "code": r.get("code"),
                "platform": r.get("platform"),
                "platform_name": _platform_display_name(r.get("platform", "")),
                "deal_name": r.get("deal_name"),
                "deal_amount_fen": r.get("deal_amount_fen", 0),
                "order_id": r.get("redeemed_order_id"),
                "redeemed_at": r.get("redeemed_at"),
            }
            for r in records
        ],
    }


# ─── 平台对账 ───


async def reconcile_platform(
    platform: str,
    store_id: str,
    date_str: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """平台对账 — 比对平台金额 vs 系统金额

    mock 实现：模拟平台方返回的对账数据，与本地核销记录比对。
    生产环境需调用各平台对账文件下载 API。
    """
    target_date = date.fromisoformat(date_str)
    records = _PlatformCouponStore.list_by_store(
        store_id, target_date, target_date, platform=platform,
    )

    system_total_fen = sum(r.get("deal_amount_fen", 0) for r in records)
    system_count = len(records)

    # mock: 模拟平台方数据（正常情况下应一致）
    platform_total_fen = system_total_fen
    platform_count = system_count

    diff_fen = system_total_fen - platform_total_fen
    diff_count = system_count - platform_count
    is_matched = diff_fen == 0 and diff_count == 0

    logger.info(
        "platform_reconciled",
        platform=platform,
        store_id=store_id,
        date=date_str,
        system_total_fen=system_total_fen,
        platform_total_fen=platform_total_fen,
        is_matched=is_matched,
        tenant_id=tenant_id,
    )
    return {
        "platform": platform,
        "platform_name": _platform_display_name(platform),
        "store_id": store_id,
        "date": date_str,
        "system": {
            "count": system_count,
            "total_amount_fen": system_total_fen,
        },
        "platform_side": {
            "count": platform_count,
            "total_amount_fen": platform_total_fen,
        },
        "diff": {
            "count": diff_count,
            "amount_fen": diff_fen,
        },
        "is_matched": is_matched,
    }
