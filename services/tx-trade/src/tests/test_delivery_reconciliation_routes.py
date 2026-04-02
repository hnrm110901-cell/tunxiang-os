"""外卖对账路由存在性检查（不导入 FastAPI app，避免环境 ORM 版本差异）。"""
from pathlib import Path


def test_reconciliation_routes_registered_in_source():
    routes_py = Path(__file__).resolve().parent.parent / "api" / "delivery_ops_routes.py"
    text = routes_py.read_text(encoding="utf-8")
    assert "/reconciliation/candidates" in text
    assert "/reconciliation/summary" in text
    assert "/reconciliation/compensation-suggestions" in text
    assert "/reconciliation/link-internal-order" in text
    assert "list_reconciliation_candidates" in text


def test_repo_has_reconciliation_methods():
    repo_py = Path(__file__).resolve().parent.parent / "repositories" / "delivery_order_repo.py"
    text = repo_py.read_text(encoding="utf-8")
    assert "list_reconciliation_candidates" in text
    assert "reconciliation_summary" in text
    assert "_TERMINAL_STATUSES" in text
    assert "find_internal_order_id_by_omni_platform_order" in text
    assert "link_delivery_to_internal_order" in text
