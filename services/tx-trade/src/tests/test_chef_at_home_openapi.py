"""大厨到家：main.py 挂载与路由前缀校验（不导入完整 FastAPI app，避免 CI/Python 版本差异）。"""

from pathlib import Path


def test_main_registers_chef_at_home_router():
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert "chef_at_home_router" in text
    assert "include_router(chef_at_home_router)" in text
    assert "TX_FEATURE_CHEF_AT_HOME" in text


def test_chef_at_home_routes_prefix_in_source():
    routes_py = Path(__file__).resolve().parent.parent / "api" / "chef_at_home_routes.py"
    text = routes_py.read_text(encoding="utf-8")
    assert 'prefix="/api/v1/chef-at-home"' in text
