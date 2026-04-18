"""
租户计费服务 — 单元测试

覆盖：
  1) 月度账单聚合（monthly 档位 × 两个租户安装）
  2) 试用期内金额为 0
  3) 用量累加
  4) 用量超限检查
"""

import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest_asyncio.fixture
async def session():
    from src.models.base import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        from src.models import app_marketplace  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def two_installations(session: AsyncSession):
    from src.models.app_marketplace import Application, AppPricingTier, AppInstallation

    # 应用 1：monthly，pro 档 199元
    app1 = Application(
        id=uuid.uuid4(), code="ai.a", name="A", category="ai_agent",
        price_model="monthly", price_fen=9900, status="published",
    )
    # 应用 2：usage_based，basic 档 99元 + 超限
    app2 = Application(
        id=uuid.uuid4(), code="ai.b", name="B", category="ai_agent",
        price_model="usage_based", price_fen=9900, status="published",
    )
    session.add_all([app1, app2])
    await session.flush()

    t1 = AppPricingTier(
        id=uuid.uuid4(), app_id=app1.id, tier_name="pro",
        monthly_fee_fen=19900,
    )
    t2 = AppPricingTier(
        id=uuid.uuid4(), app_id=app2.id, tier_name="basic",
        monthly_fee_fen=9900, usage_limits_json={"api_calls": 1000},
    )
    session.add_all([t1, t2])

    inst1 = AppInstallation(
        id=uuid.uuid4(), tenant_id="T1", app_id=app1.id, tier_name="pro",
        status="active", installed_at=datetime.utcnow(),
    )
    inst2 = AppInstallation(
        id=uuid.uuid4(), tenant_id="T1", app_id=app2.id, tier_name="basic",
        status="active", installed_at=datetime.utcnow(),
    )
    session.add_all([inst1, inst2])
    await session.commit()
    return inst1, inst2


@pytest.mark.asyncio
async def test_monthly_aggregate(session, two_installations):
    from src.services.billing_service import BillingService
    svc = BillingService(session)
    res = await svc.compute_monthly_invoice("T1", "2026-04")
    # monthly:199元 + usage_based base:99元（无 usage 记录时无超额）
    assert res["total_fen"] == 19900 + 9900
    assert len(res["line_items"]) == 2


@pytest.mark.asyncio
async def test_trial_zeros_line(session, two_installations):
    inst1, _ = two_installations
    inst1.trial_ends_at = datetime.utcnow() + timedelta(days=3)
    await session.commit()
    from src.services.billing_service import BillingService
    svc = BillingService(session)
    res = await svc.compute_monthly_invoice("T1", "2026-04")
    # inst1 试用中 → 0；inst2 仍 99 元
    assert res["total_fen"] == 9900


@pytest.mark.asyncio
async def test_usage_accumulate(session, two_installations):
    _, inst2 = two_installations
    from src.services.billing_service import BillingService
    svc = BillingService(session)
    await svc.apply_usage_data(str(inst2.id), "2026-04", {"api_calls": 500})
    await svc.apply_usage_data(str(inst2.id), "2026-04", {"api_calls": 300})
    chk = await svc.check_usage_exceeded(str(inst2.id))
    assert chk["current_usage"].get("api_calls") == 800
    assert chk["is_exceeded"] is False


@pytest.mark.asyncio
async def test_usage_exceeded(session, two_installations):
    _, inst2 = two_installations
    from src.services.billing_service import BillingService
    svc = BillingService(session)
    await svc.apply_usage_data(str(inst2.id), datetime.utcnow().strftime("%Y-%m"),
                               {"api_calls": 1500})
    chk = await svc.check_usage_exceeded(str(inst2.id))
    assert chk["is_exceeded"] is True
    assert chk["exceeded"]["api_calls"]["used"] == 1500
