"""test_d3a_rfm_outreach.py —— Sprint D3a RFM 触达规划测试

覆盖：
  1. score_rfm 单维度打分（R/F/M 三种方向）
  2. segment_for 复合分层（S1-S5）
  3. cosine_similarity 边界（空集/无交集/完全重合）
  4. score_cf_candidate CF 打分 + top_items 推荐
  5. RFMOutreachService.build_plan 完整流程（mock Haiku invoker）
  6. 降级路径：haiku_invoker=None → 走 _fallback_message
  7. segment_filter 过滤正确
  8. v266 迁移静态验证（RLS + status 枚举 + CHECK 约束）
  9. ModelRouter 注册 rfm_outreach_message task_type
"""
from __future__ import annotations

import os

# 通过 src 直接导入，避免 services 包冲突
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.rfm_outreach_service import (
    F_BUCKETS,
    M_BUCKETS,
    R_BUCKETS,
    CustomerSnapshot,
    RFMOutreachService,
    cosine_similarity,
    score_cf_candidate,
    score_rfm,
    segment_for,
)

# ──────────────────────────────────────────────────────────────────────
# 1. 单维度 RFM 打分
# ──────────────────────────────────────────────────────────────────────

def test_score_rfm_recency_smaller_better():
    # R 维度：越小越好（越近期到店）
    assert score_rfm(3, R_BUCKETS, higher_better=False) == 5    # ≤7 天 → S1
    assert score_rfm(7, R_BUCKETS, higher_better=False) == 5    # 边界
    assert score_rfm(30, R_BUCKETS, higher_better=False) == 4   # S2
    assert score_rfm(90, R_BUCKETS, higher_better=False) == 3   # S3
    assert score_rfm(180, R_BUCKETS, higher_better=False) == 2  # S4
    assert score_rfm(365, R_BUCKETS, higher_better=False) == 1  # S5


def test_score_rfm_frequency_higher_better():
    assert score_rfm(20, F_BUCKETS, higher_better=True) == 5  # ≥12 次
    assert score_rfm(12, F_BUCKETS, higher_better=True) == 5  # 边界
    assert score_rfm(6, F_BUCKETS, higher_better=True) == 4
    assert score_rfm(3, F_BUCKETS, higher_better=True) == 3
    assert score_rfm(1, F_BUCKETS, higher_better=True) == 2
    assert score_rfm(0, F_BUCKETS, higher_better=True) == 1


def test_score_rfm_monetary_higher_better():
    assert score_rfm(600000, M_BUCKETS, higher_better=True) == 5  # ≥5000 元
    assert score_rfm(200000, M_BUCKETS, higher_better=True) == 4  # 边界
    assert score_rfm(100, M_BUCKETS, higher_better=True) == 1


# ──────────────────────────────────────────────────────────────────────
# 2. segment_for 复合分层
# ──────────────────────────────────────────────────────────────────────

def test_segment_active_customer_is_s1():
    """R=5/F=5/M=5 → min=5 → S1"""
    snap = CustomerSnapshot(
        customer_id="c1", recency_days=3,
        frequency=15, monetary_fen=800000,
    )
    assert segment_for(snap) == "S1"


def test_segment_dormant_customer_is_s5():
    """R=1/F=1/M=5 → min=1 → S5（半年没来就是 S5，不管多有钱）"""
    snap = CustomerSnapshot(
        customer_id="c2", recency_days=200,
        frequency=0, monetary_fen=1000000,
    )
    assert segment_for(snap) == "S5"


def test_segment_weak_dimension_dominates():
    """任一维度最差就决定整体分层"""
    # R 健康但 F/M 差 → 看 min
    snap = CustomerSnapshot(
        customer_id="c3", recency_days=5,  # R=5
        frequency=0,                        # F=1
        monetary_fen=0,                     # M=1
    )
    assert segment_for(snap) == "S5"


# ──────────────────────────────────────────────────────────────────────
# 3. 余弦相似度
# ──────────────────────────────────────────────────────────────────────

def test_cosine_similarity_empty_returns_zero():
    assert cosine_similarity(set(), {"a"}) == 0.0
    assert cosine_similarity({"a"}, set()) == 0.0
    assert cosine_similarity(set(), set()) == 0.0


def test_cosine_similarity_identical_sets():
    assert cosine_similarity({"a", "b"}, {"a", "b"}) == 1.0


def test_cosine_similarity_no_overlap():
    assert cosine_similarity({"a"}, {"b"}) == 0.0


def test_cosine_similarity_partial():
    # |A∩B|=1, |A|=2, |B|=2 → 1/sqrt(4) = 0.5
    assert cosine_similarity({"a", "b"}, {"a", "c"}) == 0.5


# ──────────────────────────────────────────────────────────────────────
# 4. CF 打分
# ──────────────────────────────────────────────────────────────────────

def test_score_cf_candidate_returns_top_items():
    candidate = CustomerSnapshot(
        customer_id="c1", recency_days=120, frequency=1, monetary_fen=5000,
        preferred_items=["d1", "d2"],  # 候选只点过 d1 和 d2
    )
    peers = [
        CustomerSnapshot(
            customer_id="p1", recency_days=3, frequency=15, monetary_fen=800000,
            preferred_items=["d1", "d2", "d3"],  # 与候选 2 个重合 + d3
        ),
        CustomerSnapshot(
            customer_id="p2", recency_days=5, frequency=12, monetary_fen=600000,
            preferred_items=["d1", "d4", "d5"],  # 与候选 1 重合 + d4/d5
        ),
    ]
    cf_score, top_items = score_cf_candidate(candidate, peers)
    assert cf_score > 0
    # 候选没点过的菜才能推荐
    for item in top_items:
        assert item not in {"d1", "d2"}
    # d3 应当排第一（p1 相似度更高，给 d3 更多 weight）
    assert "d3" in top_items


def test_score_cf_candidate_no_overlap_returns_zero():
    candidate = CustomerSnapshot(
        customer_id="c1", recency_days=120, frequency=1, monetary_fen=5000,
        preferred_items=["dx"],
    )
    peers = [
        CustomerSnapshot(
            customer_id="p1", recency_days=3, frequency=15, monetary_fen=800000,
            preferred_items=["dy", "dz"],
        ),
    ]
    cf_score, top_items = score_cf_candidate(candidate, peers)
    assert cf_score == 0.0
    assert top_items == []


# ──────────────────────────────────────────────────────────────────────
# 5. RFMOutreachService.build_plan
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_plan_s4_s5_candidates_get_message():
    """S4/S5 沉睡客户应走完整流程：CF 打分 + Haiku 文案"""
    service = RFMOutreachService()  # haiku_invoker=None → fallback 模板

    candidates = [
        CustomerSnapshot(
            customer_id="dormant-s5", recency_days=200,
            frequency=0, monetary_fen=0,
            preferred_items=["d1", "d2"],
        ),
    ]
    active_peers = [
        CustomerSnapshot(
            customer_id="active-p1", recency_days=3,
            frequency=15, monetary_fen=800000,
            preferred_items=["d1", "d2", "d3"],
        ),
    ]

    plan = await service.build_plan(
        tenant_id="t-1",
        store_id="s-1",
        candidates=candidates,
        active_peers=active_peers,
    )
    assert plan.target_count == 1
    assert plan.candidates[0].segment == "S5"
    assert plan.candidates[0].cf_score > 0
    # 降级文案不为空
    assert plan.candidates[0].outreach_message is not None
    assert len(plan.candidates[0].outreach_message) > 0


@pytest.mark.asyncio
async def test_build_plan_filters_non_target_segments():
    """segment_filter=['S5'] 应过滤掉 S1-S4 候选"""
    service = RFMOutreachService()
    candidates = [
        CustomerSnapshot(
            customer_id="active", recency_days=3,  # S1
            frequency=15, monetary_fen=800000,
            preferred_items=["d1"],
        ),
        CustomerSnapshot(
            customer_id="dormant", recency_days=200,  # S5
            frequency=0, monetary_fen=0,
            preferred_items=["d1"],
        ),
    ]
    peers = [
        CustomerSnapshot(
            customer_id="p1", recency_days=3, frequency=15, monetary_fen=800000,
            preferred_items=["d1", "d2"],
        ),
    ]
    plan = await service.build_plan(
        tenant_id="t-1", store_id=None,
        candidates=candidates, active_peers=peers,
        target_segments=["S5"],
    )
    assert plan.target_count == 1
    assert plan.candidates[0].customer_id == "dormant"


@pytest.mark.asyncio
async def test_build_plan_calls_haiku_invoker_when_provided():
    """haiku_invoker 提供时应被调用，而非走降级"""
    invoked = []

    async def mock_haiku(prompt: str, model_id: str) -> str:
        invoked.append({"prompt": prompt, "model": model_id})
        return "来自 Haiku 的个性化文案。"

    service = RFMOutreachService(haiku_invoker=mock_haiku)
    plan = await service.build_plan(
        tenant_id="t-1", store_id=None,
        candidates=[CustomerSnapshot(
            customer_id="c1", recency_days=200, frequency=0, monetary_fen=0,
            preferred_items=["d1"],
        )],
        active_peers=[CustomerSnapshot(
            customer_id="p1", recency_days=3, frequency=15, monetary_fen=800000,
            preferred_items=["d1", "d2"],
        )],
    )
    assert plan.target_count == 1
    assert plan.candidates[0].outreach_message == "来自 Haiku 的个性化文案。"
    assert len(invoked) == 1
    assert invoked[0]["model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_build_plan_haiku_failure_falls_back_to_template():
    """Haiku invoker 抛异常时不崩溃，走降级模板"""
    async def boom_haiku(prompt: str, model_id: str) -> str:
        raise RuntimeError("Haiku API 429")

    service = RFMOutreachService(haiku_invoker=boom_haiku)
    plan = await service.build_plan(
        tenant_id="t-1", store_id=None,
        candidates=[CustomerSnapshot(
            customer_id="c1", recency_days=200, frequency=0, monetary_fen=0,
            preferred_items=["d1"],
        )],
        active_peers=[CustomerSnapshot(
            customer_id="p1", recency_days=3, frequency=15, monetary_fen=800000,
            preferred_items=["d1", "d2"],
        )],
    )
    assert plan.target_count == 1
    msg = plan.candidates[0].outreach_message
    assert msg is not None and "Haiku" not in msg   # 是 fallback 不是 LLM 输出


@pytest.mark.asyncio
async def test_build_plan_no_candidates_returns_empty():
    service = RFMOutreachService()
    plan = await service.build_plan(
        tenant_id="t-1", store_id=None,
        candidates=[], active_peers=[],
    )
    assert plan.target_count == 0
    assert plan.estimated_revenue_fen == 0


# ──────────────────────────────────────────────────────────────────────
# 6. v266 迁移静态校验
# ──────────────────────────────────────────────────────────────────────

def test_v266_migration_creates_table_with_required_columns():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v266_rfm_outreach_campaigns.py"
    )
    if not os.path.exists(path):
        pytest.skip("迁移文件不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()

    assert "CREATE TABLE IF NOT EXISTS rfm_outreach_campaigns" in content
    assert "rfm_segment" in content
    assert "target_customer_ids" in content
    assert "cf_scoring_snapshot" in content
    assert "message_template" in content
    assert "message_model" in content
    assert "estimated_roi_summary" in content
    assert "attributed_order_ids" in content


def test_v266_has_status_enum_check():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v266_rfm_outreach_campaigns.py"
    )
    if not os.path.exists(path):
        pytest.skip("迁移文件不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()

    # status 枚举必须包含核心状态
    for s in ("plan_generated", "human_confirmed", "sending", "sent", "attributed"):
        assert s in content, f"缺 status={s}"


def test_v266_has_rls_policy():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v266_rfm_outreach_campaigns.py"
    )
    if not os.path.exists(path):
        pytest.skip("迁移文件不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "rfm_outreach_tenant_isolation" in content
    assert "app.tenant_id" in content


def test_v266_down_revision_chains_to_v265():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v266_rfm_outreach_campaigns.py"
    )
    if not os.path.exists(path):
        pytest.skip("迁移文件不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert 'down_revision = "v265_mv_roi"' in content


# ──────────────────────────────────────────────────────────────────────
# 7. ModelRouter 注册
# ──────────────────────────────────────────────────────────────────────

def test_model_router_registers_rfm_outreach_message_as_simple():
    """rfm_outreach_message task 必须路由到 Haiku（SIMPLE complexity）"""
    try:
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..",
            "services", "tunxiang-api", "src", "shared", "core", "model_router.py"
        )
        if not os.path.exists(path):
            pytest.skip("model_router.py 路径不存在")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert '"rfm_outreach_message": TaskComplexity.SIMPLE' in content
        assert '"claude-haiku-4-5"' in content, "SIMPLE 复杂度必须映射到 haiku-4-5"
    except (ImportError, FileNotFoundError):
        pytest.skip("model_router 模块未安装")
