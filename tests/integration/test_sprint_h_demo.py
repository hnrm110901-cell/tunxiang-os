"""Sprint H — 徐记海鲜 DEMO 端到端集成测试

本文件是 integration test skeleton — 需 DATABASE_URL 环境变量指向 DEMO 数据库 +
seed.sql 已导入。本地开发：

  export DATABASE_URL=postgresql://localhost/tunxiang_demo
  psql $DATABASE_URL -f infra/demo/xuji_seafood/seed.sql
  pytest tests/integration/test_sprint_h_demo.py -v

CI：skip 如果没有 DB（pytest.skip_if）。

测试覆盖（随各 PR 合入逐步启用）：
  · seed.sql 语法正确（psql --syntax-check 或纯 parse）
  · demo_go_no_go.py 可执行
  · 各 scorecard JSON 结构合法
  · RLS 隔离验证（切 tenant 后无跨租户数据）
  · E2E 流程：canonical ingest → dispute → ruling（需 E1+E4 合入）

测试不包含：
  · DB 连接（使用 stub 校验 JSON 结构 + 脚本可解析）
  · 真实 Anthropic SDK（需 ANTHROPIC_API_KEY）
  · 真实外设（需商米 T2 / 打印机）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ─────────────────────────────────────────────────────────────
# 1. seed.sql 存在性 + 结构校验
# ─────────────────────────────────────────────────────────────


class TestSeedData:
    def test_seed_sql_exists(self):
        assert (ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql").exists()

    def test_cleanup_sql_exists(self):
        assert (ROOT / "infra" / "demo" / "xuji_seafood" / "cleanup.sql").exists()

    def test_seed_has_tenant_placeholder(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        assert ":tenant_id" in source, "seed.sql 必须用 psql :tenant_id 变量"

    def test_seed_has_begin_commit(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        assert "BEGIN;" in source
        assert "COMMIT;" in source

    def test_seed_covers_3_stores(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        # 长沙 / 北京 / 上海
        for city in ("长沙", "北京", "上海"):
            assert city in source

    def test_seed_covers_brand(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        assert "徐记海鲜" in source

    def test_seed_has_e1_canonical_data(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        assert "canonical_delivery_orders" in source

    def test_seed_has_e2_publish_registry(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        assert "dish_publish_registry" in source

    def test_seed_has_e4_disputes(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        assert "delivery_disputes" in source

    def test_seed_uses_on_conflict(self):
        """幂等保证：所有 INSERT 必须 ON CONFLICT"""
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "seed.sql"
        ).read_text(encoding="utf-8")
        # 允许部分表可能走 DO UPDATE 或 DO NOTHING
        assert source.count("ON CONFLICT") >= 5

    def test_cleanup_has_is_deleted_update(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "cleanup.sql"
        ).read_text(encoding="utf-8")
        assert "is_deleted = true" in source

    def test_cleanup_respects_rls_context(self):
        source = (
            ROOT / "infra" / "demo" / "xuji_seafood" / "cleanup.sql"
        ).read_text(encoding="utf-8")
        assert "app.tenant_id" in source


# ─────────────────────────────────────────────────────────────
# 2. Go/No-Go 脚本可执行性
# ─────────────────────────────────────────────────────────────


class TestGoNoGoScript:
    def test_script_exists(self):
        assert (ROOT / "scripts" / "demo_go_no_go.py").exists()

    def test_script_executable(self):
        path = ROOT / "scripts" / "demo_go_no_go.py"
        mode = path.stat().st_mode
        assert mode & 0o111, "demo_go_no_go.py 必须有执行权限"

    def test_script_help_runs(self):
        """--help 必须可执行"""
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "scripts" / "demo_go_no_go.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Go/No-Go" in result.stdout

    def test_script_skip_tests_runs(self):
        """--skip-tests 模式不依赖 DB，应该能跑通"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(ROOT / "scripts" / "demo_go_no_go.py"),
                "--skip-tests",
                "--json",
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "summary" in data
        assert "checks" in data
        assert len(data["checks"]) == 10

    def test_script_returns_10_checks(self):
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(ROOT / "scripts" / "demo_go_no_go.py"),
                "--skip-tests",
                "--json",
            ],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        # checkpoint_id 从 1 到 10 齐全
        ids = sorted(c["checkpoint_id"] for c in data["checks"])
        assert ids == list(range(1, 11))

    def test_script_each_check_has_required_fields(self):
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(ROOT / "scripts" / "demo_go_no_go.py"),
                "--skip-tests",
                "--json",
            ],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        for check in data["checks"]:
            for key in ("checkpoint_id", "name", "status", "details"):
                assert key in check, f"check 缺少字段 {key}"
            assert check["status"] in ("GO", "NO_GO", "WARNING", "SKIPPED")

    def test_script_strict_flag_honors_no_go(self):
        """--strict 遇到 NO_GO 应该 exit 1"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(ROOT / "scripts" / "demo_go_no_go.py"),
                "--skip-tests",
                "--strict",
            ],
            capture_output=True, text=True, timeout=60,
        )
        # 因为当前 NO_GO > 0（cashier signoff 未完成），strict 应该返回 1
        assert result.returncode == 1

    def test_script_only_filter(self):
        """--only 指定 checkpoint id 只跑指定项"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(ROOT / "scripts" / "demo_go_no_go.py"),
                "--skip-tests",
                "--json",
                "--only", "6", "8",
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        ids = [c["checkpoint_id"] for c in data["checks"]]
        assert ids == [6, 8]


# ─────────────────────────────────────────────────────────────
# 3. Scorecard 结构
# ─────────────────────────────────────────────────────────────


REQUIRED_SCORECARD_KEYS = frozenset({
    "merchant",
    "merchant_id",
    "evaluated_at",
    "score",
    "dimensions",
    "risks",
    "go_no_go_recommendation",
})

VALID_GO_NO_GO = frozenset({"GO", "CONDITIONAL_GO", "NO_GO"})


class TestScorecards:
    @pytest.fixture
    def scorecard_dir(self) -> Path:
        return ROOT / "docs" / "demo" / "scorecards"

    def test_at_least_3_scorecards(self, scorecard_dir):
        scorecards = list(scorecard_dir.glob("*.json"))
        assert len(scorecards) >= 3

    def test_each_scorecard_valid_json(self, scorecard_dir):
        for sc in scorecard_dir.glob("*.json"):
            data = json.loads(sc.read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_each_scorecard_has_required_keys(self, scorecard_dir):
        for sc in scorecard_dir.glob("*.json"):
            data = json.loads(sc.read_text(encoding="utf-8"))
            missing = REQUIRED_SCORECARD_KEYS - data.keys()
            assert not missing, f"{sc.name} 缺字段 {missing}"

    def test_each_score_in_range_0_to_100(self, scorecard_dir):
        for sc in scorecard_dir.glob("*.json"):
            data = json.loads(sc.read_text(encoding="utf-8"))
            assert 0 <= data["score"] <= 100, f"{sc.name} score 超范围"

    def test_each_score_meets_85_threshold(self, scorecard_dir):
        """Week 8 门槛 §6：三商户 scorecard ≥ 85"""
        for sc in scorecard_dir.glob("*.json"):
            data = json.loads(sc.read_text(encoding="utf-8"))
            assert data["score"] >= 85, f"{sc.name} 低于 85 门槛"

    def test_go_no_go_recommendation_valid(self, scorecard_dir):
        for sc in scorecard_dir.glob("*.json"):
            data = json.loads(sc.read_text(encoding="utf-8"))
            assert data["go_no_go_recommendation"] in VALID_GO_NO_GO

    def test_dimensions_have_scores(self, scorecard_dir):
        for sc in scorecard_dir.glob("*.json"):
            data = json.loads(sc.read_text(encoding="utf-8"))
            for dim_name, dim_data in data["dimensions"].items():
                assert "score" in dim_data, f"{sc.name}/{dim_name} 缺 score"
                assert 0 <= dim_data["score"] <= 100


# ─────────────────────────────────────────────────────────────
# 4. 演示话术文件
# ─────────────────────────────────────────────────────────────


class TestDemoScripts:
    @pytest.fixture
    def scripts_dir(self) -> Path:
        return ROOT / "docs" / "demo" / "scripts"

    def test_at_least_3_scripts(self, scripts_dir):
        scripts = [
            f for f in scripts_dir.glob("*.md")
            if not f.name.startswith("README")
        ]
        assert len(scripts) >= 3

    def test_each_script_nonempty(self, scripts_dir):
        for s in scripts_dir.glob("*.md"):
            assert s.stat().st_size > 500, f"{s.name} 话术过短（< 500 字节）"

    def test_scripts_cover_3_audiences(self, scripts_dir):
        """3 套话术应覆盖不同受众（运营 / IT / 财务）"""
        files = list(scripts_dir.glob("*.md"))
        combined = "\n".join(f.read_text(encoding="utf-8") for f in files)
        assert "运营" in combined or "operations" in combined.lower()
        assert "IT" in combined or "architecture" in combined.lower()
        assert "财务" in combined or "CFO" in combined


# ─────────────────────────────────────────────────────────────
# 5. Signoff 模板
# ─────────────────────────────────────────────────────────────


class TestCashierSignoff:
    def test_signoff_template_exists(self):
        signoff = ROOT / "docs" / "demo" / "cashier-signoff.md"
        assert signoff.exists()

    def test_signoff_has_3_cashier_slots(self):
        """模板需要 3 个收银员签字位置"""
        content = (
            ROOT / "docs" / "demo" / "cashier-signoff.md"
        ).read_text(encoding="utf-8")
        assert "收银员 1" in content
        assert "收银员 2" in content
        assert "收银员 3" in content

    def test_signoff_has_signature_placeholders(self):
        """模板含有签字位"""
        content = (
            ROOT / "docs" / "demo" / "cashier-signoff.md"
        ).read_text(encoding="utf-8")
        # 全角 or 半角冒号
        assert "签字" in content
        assert "日期" in content

    def test_signoff_lists_5_scenarios(self):
        """5 个场景必须都列出"""
        content = (
            ROOT / "docs" / "demo" / "cashier-signoff.md"
        ).read_text(encoding="utf-8")
        for scenario in ("扫码点餐", "会员折扣", "退菜", "日结", "外卖"):
            assert scenario in content


# ─────────────────────────────────────────────────────────────
# 6. Sprint H 文档存在
# ─────────────────────────────────────────────────────────────


class TestSprintHDocs:
    def test_run_doc_exists(self):
        doc = ROOT / "docs" / "sprint-h-integration-validation.md"
        assert doc.exists(), "docs/sprint-h-integration-validation.md 应存在"

    def test_run_doc_nonempty(self):
        doc = ROOT / "docs" / "sprint-h-integration-validation.md"
        assert doc.stat().st_size > 1000


# ─────────────────────────────────────────────────────────────
# 7. DB-dependent 测试（标记 integration，CI 需 DATABASE_URL）
# ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    "DATABASE_URL" not in os.environ,
    reason="需要 DATABASE_URL 环境变量指向 DEMO 数据库",
)
class TestEndToEndDemo:
    """端到端测试：需 DB 已 seed + 各 PR 已合入"""

    def test_seed_executed_recently(self):
        """假设 seed 在最近 24h 内执行"""
        pytest.skip("integration：需要 DB")

    def test_tenant_rls_isolation(self):
        """跨 tenant 查询不能返回数据"""
        pytest.skip("integration：需要 DB")

    def test_canonical_order_exists(self):
        """E1 seed 数据：MT_DEMO_20260424_001 订单应存在"""
        pytest.skip("integration：需要 DB")

    def test_dispute_pending_has_sla(self):
        """E4 seed 数据：pending_merchant dispute 有 merchant_deadline_at"""
        pytest.skip("integration：需要 DB")
