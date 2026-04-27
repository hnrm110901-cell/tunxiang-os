"""Sprint D2 — ROI writeback 集成测试（Tier 2）

覆盖范围：
  1. 迁移 v264 结构正确性（upgrade / downgrade / revision 链 / SQL 片段）
  2. 列默认 NULL（Pydantic / ORM 模型字段类型与可选性）
  3. flag off 时 writeback 不生效（不破坏旧行为）
  4. flag on 时 writeback 成功写入四字段
  5. 视图 SQL 聚合语义正确（按 tenant_id+agent_id+month 分组）
  6. 视图 RLS 防护（WHERE tenant_id IS NOT NULL，防止跨租户泄漏）

技术约束：
  - 不连真实 PostgreSQL；migration SQL 通过字符串/AST 断言检查
  - writeback 测试使用 AsyncMock session，聚焦 _apply_roi_fields 分支
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

# 使 `src.*` 作为包可导入（解决 decision_log_service.py 中的相对 import）
_TX_AGENT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TX_AGENT_DIR not in sys.path:
    sys.path.insert(0, _TX_AGENT_DIR)

# 模块级一次性 import，避免同一 AgentDecisionLog 在多个测试下被注册到不同 metadata
from src.models.decision_log import AgentDecisionLog  # noqa: E402
from src.services import decision_log_service  # noqa: E402
from src.services.decision_log_service import DecisionLogService  # noqa: E402

# ─────────────────────────────────────────────────────────────────
# 辅助：动态 import v264 迁移
# ─────────────────────────────────────────────────────────────────


def _load_v264():
    """从 shared/db-migrations/versions/ 动态 import v264_agent_roi_fields。"""
    here = os.path.dirname(__file__)
    versions_dir = os.path.normpath(
        os.path.join(here, "..", "..", "..", "..", "shared", "db-migrations", "versions")
    )
    target = None
    for fname in os.listdir(versions_dir):
        if fname.startswith("v264_") and fname.endswith(".py"):
            target = os.path.join(versions_dir, fname)
            break
    assert target, f"v264 迁移文件未找到，目录：{versions_dir}"

    spec = importlib.util.spec_from_file_location("_v264", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, target


def _read_v264_source() -> str:
    """读取 v264 原文用于 SQL 片段断言。"""
    _, path = _load_v264()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────
# 1. 迁移文件结构测试
# ─────────────────────────────────────────────────────────────────


class TestV264MigrationStructure:
    """v264 迁移基础结构 — 符合 MIGRATION_RULES.md。"""

    def test_v264_revision_chain(self):
        """v264.revision == 'v264' 且 down_revision == 'v263'。"""
        m, _ = _load_v264()
        assert m.revision == "v264"
        assert m.down_revision == "v263"

    def test_v264_has_upgrade_and_downgrade(self):
        """upgrade() 和 downgrade() 均为可调用。"""
        m, _ = _load_v264()
        assert callable(getattr(m, "upgrade", None))
        assert callable(getattr(m, "downgrade", None))

    def test_v264_migration_idempotent_sql(self):
        """upgrade 使用 IF NOT EXISTS / downgrade 使用 IF EXISTS（幂等）。"""
        src = _read_v264_source()
        # upgrade 侧：四列 ADD 必须用 IF NOT EXISTS
        assert "ADD COLUMN IF NOT EXISTS saved_labor_hours" in src
        assert "ADD COLUMN IF NOT EXISTS prevented_loss_fen" in src
        assert "ADD COLUMN IF NOT EXISTS improved_kpi" in src
        assert "ADD COLUMN IF NOT EXISTS roi_evidence" in src
        # 索引 + 视图 幂等
        assert "CREATE INDEX IF NOT EXISTS idx_agent_decision_roi_tenant_month" in src
        assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_agent_roi_monthly" in src
        # downgrade 侧：所有 DROP 必须用 IF EXISTS
        assert "DROP INDEX IF EXISTS idx_mv_agent_roi_monthly_pk" in src
        assert "DROP MATERIALIZED VIEW IF EXISTS mv_agent_roi_monthly" in src
        assert "DROP INDEX IF EXISTS idx_agent_decision_roi_tenant_month" in src
        assert "DROP COLUMN IF EXISTS roi_evidence" in src
        assert "DROP COLUMN IF EXISTS saved_labor_hours" in src

    def test_v264_columns_are_nullable(self):
        """新增列必须 NULL（向前兼容，零破坏），不得带 NOT NULL。"""
        src = _read_v264_source()
        # 四列定义行均显式标注 NULL 或省略（未写 NOT NULL）
        for col in ("saved_labor_hours", "prevented_loss_fen", "improved_kpi", "roi_evidence"):
            # 找到列定义那一行，确认没有 NOT NULL
            for line in src.splitlines():
                if f"ADD COLUMN IF NOT EXISTS {col}" in line:
                    assert "NOT NULL" not in line, (
                        f"列 {col} 不应为 NOT NULL（违反向前兼容）"
                    )

    def test_prevented_loss_uses_fen_bigint(self):
        """金额字段使用 BIGINT + 单位为分（CLAUDE.md §15 要求）。"""
        src = _read_v264_source()
        # ADD COLUMN 行中 prevented_loss_fen 必须是 BIGINT
        assert "prevented_loss_fen BIGINT" in src
        # comment 明确单位为分
        assert "单位: 分" in src or "单位: 分)" in src or "分)" in src

    def test_materialized_view_rls_safeguard(self):
        """物化视图 WHERE 必须包含 tenant_id IS NOT NULL（RLS 防护）。"""
        src = _read_v264_source()
        # 视图定义区内应包含 RLS 双保险条件
        assert "WHERE tenant_id IS NOT NULL" in src

    def test_materialized_view_group_by_semantics(self):
        """视图按 (tenant_id, agent_id, month) 分组，且使用 date_trunc。"""
        src = _read_v264_source()
        assert "date_trunc('month', created_at)" in src
        # GROUP BY 子句出现预期的三元组
        assert "GROUP BY tenant_id, agent_id, date_trunc('month', created_at)" in src

    def test_materialized_view_has_unique_index_for_concurrent_refresh(self):
        """唯一索引存在，支持 REFRESH MATERIALIZED VIEW CONCURRENTLY。"""
        src = _read_v264_source()
        assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_agent_roi_monthly_pk" in src
        assert "ON mv_agent_roi_monthly (tenant_id, agent_id, month)" in src


# ─────────────────────────────────────────────────────────────────
# 2. 模型字段：默认 NULL，不破坏旧行
# ─────────────────────────────────────────────────────────────────


class TestAgentDecisionLogModelFields:
    """AgentDecisionLog ORM 模型新增字段验证。"""

    def test_roi_fields_are_optional(self):
        """四个 ROI 字段必须在模型上声明为 Optional（可 NULL）。"""

        for col_name in (
            "saved_labor_hours",
            "prevented_loss_fen",
            "improved_kpi",
            "roi_evidence",
        ):
            col = AgentDecisionLog.__table__.c[col_name]
            assert col.nullable is True, f"{col_name} 必须 nullable"

    def test_model_instantiation_without_roi_preserves_backward_compat(self):
        """不提供 ROI 字段时，实例化应成功且四字段为 None。"""
        import uuid

        record = AgentDecisionLog(
            tenant_id=uuid.uuid4(),
            agent_id="discount_guard",
            decision_type="skill_execution",
            input_context={},
            output_action={},
            constraints_check={},
            confidence=0.8,
        )
        assert record.saved_labor_hours is None
        assert record.prevented_loss_fen is None
        assert record.improved_kpi is None
        assert record.roi_evidence is None


# ─────────────────────────────────────────────────────────────────
# 3. Writeback helper: flag off / flag on
# ─────────────────────────────────────────────────────────────────


def _make_record():
    """构造一个 AgentDecisionLog 实例用于 writeback helper 测试。"""
    import uuid

    return AgentDecisionLog(
        tenant_id=uuid.uuid4(),
        agent_id="discount_guard",
        decision_type="skill_execution",
        input_context={},
        output_action={},
        constraints_check={},
        confidence=0.9,
    )


class TestApplyRoiFields:
    """`_apply_roi_fields` 辅助函数的 flag 守护行为。"""

    def test_flag_off_roi_ignored(self):
        """flag off 时，即便传入 roi dict，四字段仍为 None。"""

        record = _make_record()
        roi = {
            "saved_labor_hours": 1.5,
            "prevented_loss_fen": 10000,
            "improved_kpi": {"metric": "gross_margin", "delta_pct": 2.0},
            "roi_evidence": {"source": "test"},
        }
        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=False):
            decision_log_service._apply_roi_fields(record, roi)

        assert record.saved_labor_hours is None
        assert record.prevented_loss_fen is None
        assert record.improved_kpi is None
        assert record.roi_evidence is None

    def test_flag_on_roi_applied(self):
        """flag on 时，四字段按类型校验后写入。"""

        record = _make_record()
        roi = {
            "saved_labor_hours": 1.5,
            "prevented_loss_fen": 12000,
            "improved_kpi": {"metric": "gross_margin", "delta_pct": 2.0},
            "roi_evidence": {"source": "discount_guard_v2", "event_ids": ["e1", "e2"]},
        }
        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            decision_log_service._apply_roi_fields(record, roi)

        assert record.saved_labor_hours == Decimal("1.5")
        assert record.prevented_loss_fen == 12000
        assert record.improved_kpi == {"metric": "gross_margin", "delta_pct": 2.0}
        assert record.roi_evidence == {"source": "discount_guard_v2", "event_ids": ["e1", "e2"]}

    def test_flag_on_but_no_roi_keeps_null(self):
        """flag on 但 roi=None 时，四字段保持 None（无数据可写）。"""

        record = _make_record()
        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            decision_log_service._apply_roi_fields(record, None)

        assert record.saved_labor_hours is None
        assert record.prevented_loss_fen is None
        assert record.improved_kpi is None
        assert record.roi_evidence is None

    def test_flag_on_partial_roi_only_applies_provided(self):
        """flag on + 部分字段：仅已提供的字段被写入。"""

        record = _make_record()
        roi = {"prevented_loss_fen": 5000}
        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            decision_log_service._apply_roi_fields(record, roi)

        assert record.saved_labor_hours is None
        assert record.prevented_loss_fen == 5000
        assert record.improved_kpi is None
        assert record.roi_evidence is None

    def test_flag_on_bool_not_accepted_as_prevented_loss(self):
        """安全：True/False 不应被误判为 prevented_loss_fen 的 int（Python 陷阱）。"""

        record = _make_record()
        roi = {"prevented_loss_fen": True}
        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            decision_log_service._apply_roi_fields(record, roi)

        assert record.prevented_loss_fen is None

    def test_flag_on_rejects_malformed_types(self):
        """flag on + 类型不对的字段：忽略，其它正常字段不受影响。"""

        record = _make_record()
        roi = {
            "saved_labor_hours": "not-a-number",   # 无效
            "prevented_loss_fen": 10000,           # 有效
            "improved_kpi": "not-a-dict",          # 无效
            "roi_evidence": {"ok": True},          # 有效
        }
        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            decision_log_service._apply_roi_fields(record, roi)

        assert record.saved_labor_hours is None
        assert record.prevented_loss_fen == 10000
        assert record.improved_kpi is None
        assert record.roi_evidence == {"ok": True}


# ─────────────────────────────────────────────────────────────────
# 4. DecisionLogService.log_skill_result 与 flag 交互
# ─────────────────────────────────────────────────────────────────


class _FakeResult:
    """模拟 AgentResult，最小字段集合。"""
    def __init__(self, data=None, success=True):
        self.data = data or {}
        self.success = success


class TestLogSkillResultFlagGuard:
    """log_skill_result 在 flag on/off 下的写入行为。"""

    def test_flag_off_writeback_succeeds_fields_null(self):
        """flag off 时 log_skill_result 仍成功，ROI 四字段为 None。"""
        import uuid

        tenant = str(uuid.uuid4())
        result = _FakeResult(data={"roi": {"saved_labor_hours": 2.0}})
        captured: list = []

        mock_db = AsyncMock()
        mock_db.add = lambda rec: captured.append(rec)
        mock_db.flush = AsyncMock()

        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=False):
            asyncio.run(DecisionLogService.log_skill_result(
                db=mock_db,
                tenant_id=tenant,
                agent_id="discount_guard",
                action="detect_anomaly",
                input_context={"foo": 1},
                result=result,
            ))

        assert len(captured) == 1
        rec = captured[0]
        # 旧字段正常
        assert rec.agent_id == "discount_guard"
        assert rec.decision_type == "skill_execution"
        # ROI 字段保持 None（flag off）
        assert rec.saved_labor_hours is None
        assert rec.prevented_loss_fen is None
        assert rec.improved_kpi is None
        assert rec.roi_evidence is None

    def test_flag_on_picks_up_roi_from_result_data(self):
        """flag on 时自动从 result.data['roi'] 拾取四字段。"""
        import uuid

        tenant = str(uuid.uuid4())
        result = _FakeResult(data={
            "roi": {
                "saved_labor_hours": 2.0,
                "prevented_loss_fen": 8800,
                "improved_kpi": {"metric": "waste_rate", "delta_pct": -1.2},
                "roi_evidence": {"algo": "v1", "upstream_event": "discount.alerted"},
            },
        })
        captured: list = []

        mock_db = AsyncMock()
        mock_db.add = lambda rec: captured.append(rec)
        mock_db.flush = AsyncMock()

        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            asyncio.run(DecisionLogService.log_skill_result(
                db=mock_db,
                tenant_id=tenant,
                agent_id="discount_guard",
                action="detect_anomaly",
                input_context={},
                result=result,
            ))

        assert len(captured) == 1
        rec = captured[0]
        assert rec.saved_labor_hours == Decimal("2.0")
        assert rec.prevented_loss_fen == 8800
        assert rec.improved_kpi == {"metric": "waste_rate", "delta_pct": -1.2}
        assert rec.roi_evidence == {"algo": "v1", "upstream_event": "discount.alerted"}

    def test_explicit_roi_arg_overrides_result_data(self):
        """显式 roi 参数优先于 result.data['roi']。"""
        import uuid

        tenant = str(uuid.uuid4())
        # result.data 里有 roi，但调用方显式传了不同的
        result = _FakeResult(data={"roi": {"prevented_loss_fen": 111}})
        captured: list = []

        mock_db = AsyncMock()
        mock_db.add = lambda rec: captured.append(rec)
        mock_db.flush = AsyncMock()

        with patch.object(decision_log_service, "_roi_writeback_enabled", return_value=True):
            asyncio.run(DecisionLogService.log_skill_result(
                db=mock_db,
                tenant_id=tenant,
                agent_id="discount_guard",
                action="act",
                input_context={},
                result=result,
                roi={"prevented_loss_fen": 999},
            ))

        assert len(captured) == 1
        assert captured[0].prevented_loss_fen == 999


# ─────────────────────────────────────────────────────────────────
# 5. Flag 注册
# ─────────────────────────────────────────────────────────────────


class TestRoiFlagRegistration:
    """agent.roi.writeback flag 必须存在且默认 off。"""

    def test_flag_name_constant_declared(self):
        """AgentFlags.ROI_WRITEBACK 常量存在。"""
        from shared.feature_flags.flag_names import AgentFlags
        assert hasattr(AgentFlags, "ROI_WRITEBACK")
        assert AgentFlags.ROI_WRITEBACK == "agent.roi.writeback"

    def test_flag_default_off_in_all_envs(self):
        """YAML 中本 flag 在所有环境均默认 false（避免意外开启）。"""
        import yaml
        here = os.path.dirname(__file__)
        yaml_path = os.path.normpath(os.path.join(
            here, "..", "..", "..", "..", "flags", "agents", "agent_flags.yaml"
        ))
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        roi_flag = next(
            (f for f in data["flags"] if f["name"] == "agent.roi.writeback"), None
        )
        assert roi_flag is not None, "agent.roi.writeback 未在 agent_flags.yaml 注册"
        assert roi_flag["defaultValue"] is False
        for env in ("dev", "test", "uat", "pilot", "prod"):
            assert roi_flag["environments"].get(env) is False, (
                f"{env} 环境不得默认开启 agent.roi.writeback（需创始人签字后手动开）"
            )


# ─────────────────────────────────────────────────────────────────
# 6. RLS / 跨租户隔离语义（基于迁移 SQL 字符串断言）
# ─────────────────────────────────────────────────────────────────


class TestRlsSemantics:
    """确认视图聚合不会从 agent_decision_logs 表穿透租户隔离。"""

    def test_view_uses_base_table_subject_to_rls(self):
        """视图 FROM 的是启用了 RLS 的 agent_decision_logs。

        agent_decision_logs 已在 v099 启用 RLS（app.tenant_id）；
        本视图 SELECT 会继承基表的 RLS（创建者上下文 + 查询者上下文共同过滤）。
        额外的 WHERE tenant_id IS NOT NULL 是双保险。
        """
        src = _read_v264_source()
        # 直接 FROM agent_decision_logs 而非其它中间视图
        assert "FROM agent_decision_logs" in src

    def test_view_where_tenant_not_null_guard(self):
        """WHERE tenant_id IS NOT NULL — 防止任何 NULL tenant_id 脏数据聚入。"""
        src = _read_v264_source()
        assert "WHERE tenant_id IS NOT NULL" in src
        assert "AND is_deleted = false" in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
