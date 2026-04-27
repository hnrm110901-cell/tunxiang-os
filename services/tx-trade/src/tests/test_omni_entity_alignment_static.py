"""Omni 落库与 Order 实体对齐：静态断言（无 ORM 导入链）。"""

from pathlib import Path


def _svc_text() -> str:
    p = Path(__file__).resolve().parent.parent / "services" / "omni_channel_service.py"
    return p.read_text(encoding="utf-8")


def _routes_text() -> str:
    p = Path(__file__).resolve().parent.parent / "api" / "omni_channel_routes.py"
    return p.read_text(encoding="utf-8")


def test_omni_persist_uses_sales_channel_and_metadata():
    t = _svc_text()
    assert "sales_channel_id=order.source_channel" in t
    assert 'order_type="delivery"' in t
    assert '"omni"' in t and "platform_order_id" in t
    assert "stable_omni_order_no" in t
    assert "OrderModel.source_channel" not in t


def test_omni_routes_use_sales_channel_not_legacy_source_channel():
    t = _routes_text()
    assert "source_channel" not in t
    assert "sales_channel_id" in t
    assert "omni_order_match_clause" in t
