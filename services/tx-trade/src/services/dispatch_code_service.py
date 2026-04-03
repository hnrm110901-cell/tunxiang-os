"""外卖出餐码服务 — 生成、持久化、扫码确认、平台回调

# SCHEMA SQL:
# CREATE TABLE dispatch_codes (
#   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#   tenant_id UUID NOT NULL,
#   order_id UUID NOT NULL,
#   code TEXT NOT NULL,
#   platform TEXT NOT NULL DEFAULT 'unknown',
#   confirmed BOOLEAN NOT NULL DEFAULT FALSE,
#   confirmed_at TIMESTAMPTZ,
#   operator_id UUID,
#   created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
#   UNIQUE(tenant_id, order_id),
#   UNIQUE(tenant_id, code)
# );
# ALTER TABLE dispatch_codes ENABLE ROW LEVEL SECURITY;
# CREATE POLICY dispatch_codes_tenant ON dispatch_codes
#   USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID);
"""
import random
import string
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_BASE62_CHARS = string.ascii_uppercase + string.ascii_lowercase + string.digits
CODE_LENGTH = 6
MAX_COLLISION_RETRIES = 10

SUPPORTED_PLATFORMS = ("meituan", "eleme", "douyin", "dianping")


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class DispatchCode:
    """出餐码记录（对应 dispatch_codes 表）"""
    id: str
    tenant_id: str
    order_id: str
    code: str
    platform: str
    confirmed: bool
    confirmed_at: Optional[datetime]
    operator_id: Optional[str]
    created_at: datetime


@dataclass
class ScanResult:
    """扫码确认结果"""
    success: bool
    order_id: Optional[str] = None
    platform: Optional[str] = None
    already_confirmed: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 内存存储（生产替换为真实 DB）
# ---------------------------------------------------------------------------

# tenant_id -> {order_id -> DispatchCode}
_store_by_order: dict[str, dict[str, DispatchCode]] = {}
# tenant_id -> {code -> DispatchCode}
_store_by_code: dict[str, dict[str, DispatchCode]] = {}


def _get_by_order(tenant_id: str, order_id: str) -> Optional[DispatchCode]:
    return _store_by_order.get(tenant_id, {}).get(order_id)


def _get_by_code(tenant_id: str, code: str) -> Optional[DispatchCode]:
    return _store_by_code.get(tenant_id, {}).get(code)


def _save(dc: DispatchCode) -> None:
    _store_by_order.setdefault(dc.tenant_id, {})[dc.order_id] = dc
    _store_by_code.setdefault(dc.tenant_id, {})[dc.code] = dc


def _list_pending(tenant_id: str) -> list[DispatchCode]:
    return [
        dc for dc in _store_by_order.get(tenant_id, {}).values()
        if not dc.confirmed
    ]


# ---------------------------------------------------------------------------
# 纯函数：生成短码
# ---------------------------------------------------------------------------

def generate_dispatch_code(order_id: str, tenant_id: str) -> str:
    """为外卖订单生成 6 位 base62 短码（碰撞检测）。

    Args:
        order_id:  订单 UUID 字符串
        tenant_id: 租户 UUID 字符串

    Returns:
        6 位字母数字短码

    Raises:
        RuntimeError: 超过最大重试次数仍有碰撞
    """
    for attempt in range(MAX_COLLISION_RETRIES):
        code = "".join(random.choices(_BASE62_CHARS, k=CODE_LENGTH))
        if _get_by_code(tenant_id, code) is None:
            logger.debug(
                "dispatch_code_generated",
                code=code,
                order_id=order_id,
                tenant_id=tenant_id,
                attempt=attempt,
            )
            return code
    raise RuntimeError(
        f"生成出餐码碰撞超过 {MAX_COLLISION_RETRIES} 次，请检查存储容量"
    )


# ---------------------------------------------------------------------------
# Mock 平台回调客户端
# ---------------------------------------------------------------------------

class _MockPlatformClient:
    """Mock 平台出餐回调（生产环境替换为真实 HTTP 调用）"""

    async def notify_dispatch(self, platform: str, order_id: str) -> dict:
        logger.info(
            "mock_platform_dispatch_notify",
            platform=platform,
            order_id=order_id,
        )
        return {"code": "ok", "order_id": order_id, "platform": platform}


_platform_client = _MockPlatformClient()


def set_platform_client(client: Any) -> None:
    """注入真实平台客户端（测试或生产调用）"""
    global _platform_client
    _platform_client = client


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------

class DispatchCodeService:
    """出餐码核心业务逻辑"""

    # ── 生成并持久化 ──────────────────────────────────────────────────────────

    @staticmethod
    async def generate(
        order_id: str,
        tenant_id: str,
        db: Any = None,
        platform: str = "unknown",
    ) -> DispatchCode:
        """生成出餐码并持久化，幂等——已存在则直接返回。

        Args:
            order_id:  订单 UUID
            tenant_id: 租户 UUID
            db:        AsyncSession（留作 ORM 扩展，当前使用内存存储）
            platform:  外卖平台（meituan/eleme/douyin/dianping）

        Returns:
            DispatchCode dataclass
        """
        existing = _get_by_order(tenant_id, order_id)
        if existing is not None:
            logger.info(
                "dispatch_code_already_exists",
                order_id=order_id,
                tenant_id=tenant_id,
                code=existing.code,
            )
            return existing

        code = generate_dispatch_code(order_id, tenant_id)
        dc = DispatchCode(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            order_id=order_id,
            code=code,
            platform=platform,
            confirmed=False,
            confirmed_at=None,
            operator_id=None,
            created_at=datetime.now(timezone.utc),
        )
        _save(dc)

        logger.info(
            "dispatch_code_created",
            order_id=order_id,
            tenant_id=tenant_id,
            code=code,
            platform=platform,
        )
        return dc

    # ── 扫码确认出餐 ──────────────────────────────────────────────────────────

    @staticmethod
    async def confirm_by_scan(
        code: str,
        operator_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> ScanResult:
        """扫码确认出餐。

        成功路径：
          1. 查找出餐码
          2. 幂等检测（已确认则返回 already_confirmed=True）
          3. 更新状态为 confirmed，记录 confirmed_at / operator_id
          4. 调用平台出餐回调（失败记录日志但不阻塞）

        Args:
            code:        6 位出餐码
            operator_id: 操作员 UUID（打包员）
            tenant_id:   租户 UUID（跨租户隔离，仅查本租户数据）
            db:          AsyncSession（留作 ORM 扩展）

        Returns:
            ScanResult
        """
        dc = _get_by_code(tenant_id, code)
        if dc is None:
            logger.warning(
                "dispatch_code_not_found",
                code=code,
                tenant_id=tenant_id,
            )
            return ScanResult(
                success=False,
                error=f"出餐码 {code} 不存在或不属于当前租户",
            )

        if dc.confirmed:
            logger.info(
                "dispatch_code_already_confirmed",
                code=code,
                order_id=dc.order_id,
                tenant_id=tenant_id,
            )
            return ScanResult(
                success=True,
                order_id=dc.order_id,
                platform=dc.platform,
                already_confirmed=True,
            )

        # 更新确认状态
        dc.confirmed = True
        dc.confirmed_at = datetime.now(timezone.utc)
        dc.operator_id = operator_id
        _save(dc)

        logger.info(
            "dispatch_code_confirmed",
            code=code,
            order_id=dc.order_id,
            platform=dc.platform,
            operator_id=operator_id,
            tenant_id=tenant_id,
        )

        # 平台出餐回调（失败不阻塞）
        await _notify_platform(dc.platform, dc.order_id)

        return ScanResult(
            success=True,
            order_id=dc.order_id,
            platform=dc.platform,
            already_confirmed=False,
        )

    # ── 按订单查询 ────────────────────────────────────────────────────────────

    @staticmethod
    async def get_by_order(
        order_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> Optional[DispatchCode]:
        """按订单 ID 查询出餐码（租户隔离）。"""
        return _get_by_order(tenant_id, order_id)

    # ── 待确认列表 ────────────────────────────────────────────────────────────

    @staticmethod
    async def list_pending(
        tenant_id: str,
        store_id: Optional[str] = None,
        db: Any = None,
    ) -> list[DispatchCode]:
        """返回未确认的出餐码列表（待出餐订单）。

        Args:
            tenant_id: 租户 UUID
            store_id:  门店过滤（当前内存实现暂不使用，留作 ORM 扩展）
            db:        AsyncSession
        """
        return _list_pending(tenant_id)


# ---------------------------------------------------------------------------
# 平台回调（内部）
# ---------------------------------------------------------------------------

async def _notify_platform(platform: str, order_id: str) -> None:
    """调用平台出餐回调，失败记录日志但不向上抛出。

    Args:
        platform: meituan / eleme / douyin / dianping / unknown
        order_id: 订单 UUID
    """
    if platform not in SUPPORTED_PLATFORMS:
        logger.info(
            "dispatch_notify_skip_unknown_platform",
            platform=platform,
            order_id=order_id,
        )
        return

    try:
        result = await _platform_client.notify_dispatch(platform, order_id)
        logger.info(
            "dispatch_platform_notify_ok",
            platform=platform,
            order_id=order_id,
            result=result,
        )
    except (ConnectionError, TimeoutError, OSError) as exc:  # noqa: BLE001
        logger.error(
            "dispatch_platform_notify_failed",
            platform=platform,
            order_id=order_id,
            error=str(exc),
            exc_info=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "dispatch_platform_notify_unexpected",
            platform=platform,
            order_id=order_id,
            error=str(exc),
            exc_info=True,
        )
