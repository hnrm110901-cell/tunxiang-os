"""绩效积分 API 已接 DB：静态检查（不启动 app）。"""

from pathlib import Path


def test_performance_routes_use_employee_points_service():
    perf = Path(__file__).resolve().parent.parent / "api" / "performance_routes.py"
    t = perf.read_text(encoding="utf-8")
    assert "get_leaderboard" in t
    assert "get_employee_points_detail" in t
    assert "apply_manual_points_delta" in t
    assert "待 employee_points" not in t


def test_migration_defines_employee_point_logs():
    mig = (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "shared"
        / "db-migrations"
        / "versions"
        / "v123_employee_point_logs.py"
    )
    assert mig.is_file()
    s = mig.read_text(encoding="utf-8")
    assert "employee_point_logs" in s
    assert "ROW LEVEL SECURITY" in s
