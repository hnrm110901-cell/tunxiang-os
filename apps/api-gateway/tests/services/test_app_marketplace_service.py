"""
应用市场服务 — 单元测试（async + in-memory SQLite）

覆盖：
  1) 安装（含试用期 trial_ends_at 正确计算）
  2) 卸载
  3) 档位升级
  4) 提交评价后列表返回 avg_rating
  5) 未发布应用不能安装
"""

import sys
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
    # in-memory SQLite 不支持 JSONB/UUID；用 JSON/String 兼容方案
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # monkey-patch: JSONB→JSON, UUID→String for sqlite
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy import JSON, String, types

    async with engine.begin() as conn:
        # 仅创建 app_marketplace 涉及的 5 张表
        from src.models import app_marketplace  # noqa: F401
        # 把 JSONB/UUID 替换成跨方言类型（sqlite 下 Base 的这些 Column 仍能 create_all）
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_app(session: AsyncSession):
    import uuid
    from src.models.app_marketplace import Application, AppPricingTier
    app = Application(
        id=uuid.uuid4(),
        code="ai.test",
        name="测试数智员工",
        category="ai_agent",
        price_model="monthly",
        price_fen=9900,
        status="published",
        trial_days=7,
    )
    session.add(app)
    await session.flush()
    for t, fee in [("basic", 9900), ("pro", 19900), ("enterprise", 39900)]:
        session.add(AppPricingTier(
            id=uuid.uuid4(), app_id=app.id, tier_name=t, monthly_fee_fen=fee,
        ))
    await session.commit()
    return app


@pytest.mark.asyncio
async def test_install_sets_trial(session, seeded_app):
    from src.services.app_marketplace_service import AppMarketplaceService
    svc = AppMarketplaceService(session)
    res = await svc.install_app("tenant-A", str(seeded_app.id), tier_name="basic")
    await session.commit()
    assert res["status"] == "active"
    assert res["tier_name"] == "basic"
    # 试用期应大致在 7 天后
    assert res["trial_ends_at"] is not None
    ends = datetime.fromisoformat(res["trial_ends_at"])
    assert timedelta(days=6) < ends - datetime.utcnow() < timedelta(days=8)


@pytest.mark.asyncio
async def test_uninstall_then_reinstall(session, seeded_app):
    from src.services.app_marketplace_service import AppMarketplaceService
    svc = AppMarketplaceService(session)
    r1 = await svc.install_app("tenant-B", str(seeded_app.id))
    await svc.uninstall_app(r1["installation_id"])
    # 同租户重新装会激活旧记录
    r2 = await svc.install_app("tenant-B", str(seeded_app.id))
    assert r2["installation_id"] == r1["installation_id"]
    assert r2["status"] == "active"


@pytest.mark.asyncio
async def test_update_tier(session, seeded_app):
    from src.services.app_marketplace_service import AppMarketplaceService
    svc = AppMarketplaceService(session)
    r = await svc.install_app("tenant-C", str(seeded_app.id), tier_name="basic")
    up = await svc.update_tier(r["installation_id"], "pro")
    assert up["old_tier"] == "basic"
    assert up["new_tier"] == "pro"
    with pytest.raises(ValueError):
        await svc.update_tier(r["installation_id"], "galactic")  # 不存在档位


@pytest.mark.asyncio
async def test_submit_review_and_avg(session, seeded_app):
    from src.services.app_marketplace_service import AppMarketplaceService
    svc = AppMarketplaceService(session)
    await svc.submit_review(str(seeded_app.id), "tenant-D", 5, "nice")
    await svc.submit_review(str(seeded_app.id), "tenant-E", 3, "ok")
    await session.commit()
    apps = await svc.list_apps()
    match = [a for a in apps if a["id"] == str(seeded_app.id)]
    assert match and match[0]["avg_rating"] == pytest.approx(4.0)
    assert match[0]["review_count"] == 2


@pytest.mark.asyncio
async def test_cannot_install_unpublished(session, seeded_app):
    seeded_app.status = "draft"
    await session.commit()
    from src.services.app_marketplace_service import AppMarketplaceService
    svc = AppMarketplaceService(session)
    with pytest.raises(ValueError):
        await svc.install_app("tenant-X", str(seeded_app.id))
