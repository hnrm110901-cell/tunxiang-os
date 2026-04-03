"""全渠道统一订单：源码与 main 挂载检查。"""
from pathlib import Path


def test_unified_order_hub_service_exists():
    svc = Path(__file__).resolve().parent.parent / "services" / "unified_order_hub.py"
    t = svc.read_text(encoding="utf-8")
    assert "list_unified_orders" in t
    assert "delivery_unlinked" in t
    assert "internal_order_id IS NULL" in t
    assert "_parse_status_filter" in t
    assert "channel_key_exact" in t


def test_main_includes_omni_channel_router():
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert "omni_channel_router" in text
    assert "omni_channel_router, prefix=\"/api/v1\"" in text


def test_omni_routes_expose_unified_orders():
    routes = Path(__file__).resolve().parent.parent / "api" / "omni_channel_routes.py"
    t = routes.read_text(encoding="utf-8")
    assert "/unified-orders" in t or "unified-orders" in t
    assert "channel_key=channel_key" in t
    assert "status=status" in t
