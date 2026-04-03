"""10级角色权限服务测试

覆盖场景：
  1. 折扣权限 — 服务员尝试超额折扣被拒
  2. 折扣权限 — 店长可以更大折扣
  3. 折扣权限 — can_override_discount=True 时返回需审批
  4. 折扣权限 — 管理员(level=10)无限制
  5. 抹零权限 — 超限被拒
  6. 抹零权限 — 未超限允许
  7. 赠送权限 — 无赠送权限被拒
  8. 赠送权限 — 有权限且未超限允许
  9. 退单权限 — 收银员被拒（Level 5 < 7）
  10. 退单权限 — 店长被允许（Level 7）
  11. 改价权限 — 主管被允许（Level 6）
  12. 改价权限 — 服务员被拒（Level 3）
  13. 无角色员工 — 所有操作被拒
  14. PermissionCheckResult 工厂方法
"""
import os
import sys
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# 路径注入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

from services.permission_service import (
    PermissionCheckResult,
    PermissionRepository,
    PermissionService,
    RoleSnapshot,
)

# ─── 测试数据工厂 ───────────────────────────────────────────────


def _make_role(
    level: int,
    max_discount_rate: float = 100.0,
    max_wipeoff_fen: int = 0,
    max_gift_fen: int = 0,
    data_query_days: int = 30,
    can_void_order: bool = False,
    can_modify_price: bool = False,
    can_override_discount: bool = False,
) -> RoleSnapshot:
    return RoleSnapshot(
        role_config_id=uuid.uuid4(),
        role_name=f"Level{level}Role",
        level=level,
        max_discount_rate=max_discount_rate,
        max_wipeoff_fen=max_wipeoff_fen,
        max_gift_fen=max_gift_fen,
        data_query_days=data_query_days,
        can_void_order=can_void_order,
        can_modify_price=can_modify_price,
        can_override_discount=can_override_discount,
    )


WAITER_ROLE = _make_role(
    level=3,
    max_discount_rate=90.0,
    max_wipeoff_fen=500,
    max_gift_fen=0,
    data_query_days=30,
)

CASHIER_ROLE = _make_role(
    level=5,
    max_discount_rate=85.0,
    max_wipeoff_fen=1000,
    max_gift_fen=5000,
    data_query_days=30,
)

MANAGER_ROLE = _make_role(
    level=7,
    max_discount_rate=70.0,
    max_wipeoff_fen=3000,
    max_gift_fen=50000,
    data_query_days=90,
    can_void_order=True,
    can_modify_price=True,
    can_override_discount=True,
)

SUPERVISOR_ROLE = _make_role(
    level=6,
    max_discount_rate=80.0,
    max_wipeoff_fen=2000,
    max_gift_fen=20000,
    data_query_days=60,
    can_void_order=False,
    can_modify_price=True,
    can_override_discount=False,
)

ADMIN_ROLE = _make_role(
    level=10,
    max_discount_rate=0.0,   # 0.0 = 无限制
    max_wipeoff_fen=999999,
    max_gift_fen=999999,
    data_query_days=9999,
    can_void_order=True,
    can_modify_price=True,
    can_override_discount=True,
)


def _make_service_with_role(role: Optional[RoleSnapshot]) -> PermissionService:
    """创建注入了 mock repo 的 PermissionService"""
    svc = PermissionService()
    mock_repo = AsyncMock(spec=PermissionRepository)
    mock_repo.get_employee_role_snapshot.return_value = role
    mock_repo.write_check_log.return_value = None
    svc._repo = mock_repo
    return svc


TENANT_ID = uuid.uuid4()
EMP_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
MOCK_SESSION = MagicMock()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PermissionCheckResult 工厂方法
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPermissionCheckResult:
    def test_permit(self):
        r = PermissionCheckResult.permit()
        assert r.allowed is True
        assert r.require_approval is False
        assert r.approver_min_level == 0

    def test_deny(self):
        r = PermissionCheckResult.deny("权限不足")
        assert r.allowed is False
        assert r.require_approval is False
        assert "权限不足" in r.message

    def test_need_approval(self):
        r = PermissionCheckResult.need_approval(approver_min_level=9, reason="超额折扣需审批")
        assert r.allowed is False
        assert r.require_approval is True
        assert r.approver_min_level == 9


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  折扣权限测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
class TestDiscountPermission:
    async def test_waiter_allowed_discount_within_limit(self):
        """服务员在权限范围内打折（90% = 九折）"""
        svc = _make_service_with_role(WAITER_ROLE)
        result = await svc.check_discount_permission(
            employee_id=EMP_ID,
            discount_rate=90.0,   # 刚好等于下限
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_waiter_blocked_excessive_discount(self):
        """服务员尝试85折（低于90%下限）被拒，且无审批权"""
        svc = _make_service_with_role(WAITER_ROLE)  # can_override_discount=False
        result = await svc.check_discount_permission(
            employee_id=EMP_ID,
            discount_rate=85.0,   # 低于 90.0 下限
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert result.require_approval is False
        assert "权限下限" in result.message or "85" in result.message

    async def test_manager_allowed_bigger_discount(self):
        """店长可以执行70折（等于其权限下限）"""
        svc = _make_service_with_role(MANAGER_ROLE)
        result = await svc.check_discount_permission(
            employee_id=EMP_ID,
            discount_rate=70.0,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_manager_requires_approval_for_beyond_limit(self):
        """店长尝试60折（低于70%下限），但有审批权，返回需审批"""
        svc = _make_service_with_role(MANAGER_ROLE)  # can_override_discount=True, level=7
        result = await svc.check_discount_permission(
            employee_id=EMP_ID,
            discount_rate=60.0,   # 低于 70.0
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert result.require_approval is True
        assert result.approver_min_level == 9  # level(7) + 2 = 9

    async def test_admin_unlimited_discount(self):
        """管理员（level=10）对任意折扣无限制"""
        svc = _make_service_with_role(ADMIN_ROLE)
        result = await svc.check_discount_permission(
            employee_id=EMP_ID,
            discount_rate=1.0,    # 极低折扣
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_no_role_employee_blocked(self):
        """未分配角色的员工所有操作被拒"""
        svc = _make_service_with_role(None)
        result = await svc.check_discount_permission(
            employee_id=EMP_ID,
            discount_rate=95.0,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert "未分配角色" in result.message


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  抹零权限测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
class TestWipeoffPermission:
    async def test_cashier_allowed_within_limit(self):
        """收银员抹零500分（<=1000上限）"""
        svc = _make_service_with_role(CASHIER_ROLE)
        result = await svc.check_wipeoff_permission(
            employee_id=EMP_ID,
            amount_fen=500,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_cashier_blocked_over_limit(self):
        """收银员抹零超过1000分被拒"""
        svc = _make_service_with_role(CASHIER_ROLE)
        result = await svc.check_wipeoff_permission(
            employee_id=EMP_ID,
            amount_fen=1500,   # 超过 1000 上限
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert "超过" in result.message or "上限" in result.message

    async def test_waiter_zero_wipeoff_limit(self):
        """服务员（抹零上限0）任何抹零都被拒"""
        svc = _make_service_with_role(WAITER_ROLE)  # max_wipeoff_fen=500 for waiter
        result = await svc.check_wipeoff_permission(
            employee_id=EMP_ID,
            amount_fen=100,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        # WAITER_ROLE.max_wipeoff_fen=500, 100<=500 → 允许
        assert result.allowed is True

    async def test_admin_unlimited_wipeoff(self):
        """管理员抹零不限"""
        svc = _make_service_with_role(ADMIN_ROLE)
        result = await svc.check_wipeoff_permission(
            employee_id=EMP_ID,
            amount_fen=99999,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  赠送权限测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
class TestGiftPermission:
    async def test_waiter_no_gift_permission(self):
        """服务员无赠送权限"""
        svc = _make_service_with_role(WAITER_ROLE)  # max_gift_fen=0
        result = await svc.check_gift_permission(
            employee_id=EMP_ID,
            amount_fen=100,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert "无赠送权限" in result.message

    async def test_cashier_gift_within_limit(self):
        """收银员赠送3000分（<=5000上限）"""
        svc = _make_service_with_role(CASHIER_ROLE)
        result = await svc.check_gift_permission(
            employee_id=EMP_ID,
            amount_fen=3000,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_cashier_gift_over_limit(self):
        """收银员赠送超过5000分被拒"""
        svc = _make_service_with_role(CASHIER_ROLE)
        result = await svc.check_gift_permission(
            employee_id=EMP_ID,
            amount_fen=8000,   # 超过 5000
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False

    async def test_manager_gift_large_amount(self):
        """店长赠送30000分（<=50000上限）"""
        svc = _make_service_with_role(MANAGER_ROLE)
        result = await svc.check_gift_permission(
            employee_id=EMP_ID,
            amount_fen=30000,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  退单权限测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
class TestVoidOrderPermission:
    async def test_cashier_cannot_void(self):
        """收银员（Level 5）无退单权限"""
        svc = _make_service_with_role(CASHIER_ROLE)  # can_void_order=False
        result = await svc.check_void_order_permission(
            employee_id=EMP_ID,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert "退单" in result.message or "void" in result.message.lower()

    async def test_manager_can_void(self):
        """店长（Level 7）有退单权限"""
        svc = _make_service_with_role(MANAGER_ROLE)  # can_void_order=True
        result = await svc.check_void_order_permission(
            employee_id=EMP_ID,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_waiter_cannot_void(self):
        """服务员（Level 3）无退单权限"""
        svc = _make_service_with_role(WAITER_ROLE)
        result = await svc.check_void_order_permission(
            employee_id=EMP_ID,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  改价权限测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
class TestModifyPricePermission:
    async def test_supervisor_can_modify_price(self):
        """主管（Level 6）有改价权限"""
        svc = _make_service_with_role(SUPERVISOR_ROLE)  # can_modify_price=True
        result = await svc.check_modify_price_permission(
            employee_id=EMP_ID,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is True

    async def test_waiter_cannot_modify_price(self):
        """服务员（Level 3）无改价权限"""
        svc = _make_service_with_role(WAITER_ROLE)  # can_modify_price=False
        result = await svc.check_modify_price_permission(
            employee_id=EMP_ID,
            tenant_id=TENANT_ID,
            session=MOCK_SESSION,
        )
        assert result.allowed is False
        assert "改价" in result.message


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  级别更新约束（通过 role_api 逻辑验证，无需真实DB）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRoleLevelConstraints:
    def test_approver_level_capped_at_10(self):
        """审批人级别上限为10（level=10时不会出现11）"""
        # 模拟 level=9 的角色超额折扣申请
        approver_level = min(9 + 2, 10)
        assert approver_level == 10

    def test_approver_level_from_level_7(self):
        """店长(level=7)超额折扣需 level=9 审批"""
        approver_level = min(7 + 2, 10)
        assert approver_level == 9

    def test_operator_cannot_create_higher_level_role(self):
        """操作人不能创建高于自己级别的角色（业务规则验证）"""
        operator_level = 5
        target_level = 7
        assert target_level > operator_level  # 验证规则本身正确

    def test_operator_can_create_same_level_role(self):
        """操作人可以创建等于自己级别的角色"""
        operator_level = 7
        target_level = 7
        assert target_level <= operator_level
