"""E8 区域追踪与整改测试"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.regional_management import (
    dispatch_rectification,
    track_rectification,
    submit_review,
    get_regional_scorecard,
    cross_store_benchmark,
    generate_regional_report,
    get_rectification_archive,
    RECTIFICATION_STATUSES,
    RECTIFICATION_TRANSITIONS,
    _score_to_color,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  整改派发与状态机
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDispatchRectification:
    @pytest.mark.asyncio
    async def test_dispatch_creates_record(self):
        result = await dispatch_rectification(
            "region_east", "store_01", "issue_123", "emp_a", "2026-04-15", "t1", db=None
        )
        assert result["rectification_id"].startswith("rect_region_east_")
        assert result["status"] == "dispatched"
        assert result["store_id"] == "store_01"
        assert result["assignee_id"] == "emp_a"
        assert result["tenant_id"] == "t1"

    @pytest.mark.asyncio
    async def test_dispatch_fields_complete(self):
        result = await dispatch_rectification(
            "r1", "s1", "i1", "a1", "2026-05-01", "t1", db=None
        )
        required_keys = {
            "rectification_id", "region_id", "store_id", "issue_id",
            "assignee_id", "deadline", "status", "tenant_id", "created_at",
        }
        assert required_keys.issubset(result.keys())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  进度跟踪
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTrackRectification:
    @pytest.mark.asyncio
    async def test_valid_transition(self):
        record = {"status": "dispatched", "progress_notes": []}
        result = await track_rectification(
            "rect_001", "t1", db=None,
            record=record, new_status="in_progress", note="started work",
        )
        assert result["status"] == "in_progress"
        assert record["status"] == "in_progress"
        assert len(record["progress_notes"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        record = {"status": "dispatched", "progress_notes": []}
        with pytest.raises(ValueError, match="Cannot transition"):
            await track_rectification(
                "rect_001", "t1", db=None,
                record=record, new_status="submitted",
            )

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """dispatched → in_progress → submitted"""
        record = {"status": "dispatched", "progress_notes": []}
        await track_rectification("r1", "t1", db=None, record=record, new_status="in_progress")
        assert record["status"] == "in_progress"
        await track_rectification("r1", "t1", db=None, record=record, new_status="submitted")
        assert record["status"] == "submitted"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  复查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSubmitReview:
    @pytest.mark.asyncio
    async def test_pass_review_closes(self):
        record = {"status": "submitted", "review_result": None}
        result = await submit_review(
            "rect_001", "reviewer_1", "pass", "t1", db=None, record=record,
        )
        assert result["result"] == "pass"
        assert result["status"] == "closed"
        assert record["status"] == "closed"

    @pytest.mark.asyncio
    async def test_fail_review_stays_reviewed(self):
        record = {"status": "submitted", "review_result": None}
        result = await submit_review(
            "rect_001", "reviewer_1", "fail", "t1", db=None, record=record,
        )
        assert result["result"] == "fail"
        assert result["status"] == "reviewed"
        assert record["status"] == "reviewed"

    @pytest.mark.asyncio
    async def test_review_wrong_status_raises(self):
        record = {"status": "dispatched", "review_result": None}
        with pytest.raises(ValueError, match="requires status 'submitted'"):
            await submit_review("r1", "rev1", "pass", "t1", db=None, record=record)

    @pytest.mark.asyncio
    async def test_invalid_result_raises(self):
        with pytest.raises(ValueError, match="must be 'pass' or 'fail'"):
            await submit_review("r1", "rev1", "maybe", "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  评分卡
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRegionalScorecard:
    def test_score_to_color(self):
        assert _score_to_color(90) == "green"
        assert _score_to_color(80) == "green"
        assert _score_to_color(79) == "yellow"
        assert _score_to_color(60) == "yellow"
        assert _score_to_color(59) == "red"
        assert _score_to_color(0) == "red"

    @pytest.mark.asyncio
    async def test_scorecard_generation(self):
        scores = [
            {"store_id": "s1", "score": 90},
            {"store_id": "s2", "score": 70},
            {"store_id": "s3", "score": 50},
        ]
        result = await get_regional_scorecard("r1", "t1", db=None, store_scores=scores)
        assert result["color_counts"]["green"] == 1
        assert result["color_counts"]["yellow"] == 1
        assert result["color_counts"]["red"] == 1
        assert result["avg_score"] == 70.0
        # 按分数升序，最差排前面
        assert result["stores"][0]["store_id"] == "s3"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  跨店对标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCrossStoreBenchmark:
    @pytest.mark.asyncio
    async def test_benchmark_ranking(self):
        metrics = {"s1": 95.0, "s2": 80.0, "s3": 60.0}
        result = await cross_store_benchmark(
            "food_safety_score", "r1", "t1", db=None, store_metrics=metrics,
        )
        assert result["metric"] == "food_safety_score"
        assert result["ranking"][0]["store_id"] == "s1"
        assert result["ranking"][0]["rank"] == 1
        assert result["summary"]["avg"] == 78.33
        assert result["summary"]["total_stores"] == 3

    @pytest.mark.asyncio
    async def test_empty_benchmark(self):
        result = await cross_store_benchmark("x", "r1", "t1", db=None, store_metrics={})
        assert result["summary"]["total_stores"] == 0
        assert result["ranking"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  月报
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRegionalReport:
    @pytest.mark.asyncio
    async def test_report_with_data(self):
        rects = [
            {"status": "closed", "review_result": "pass"},
            {"status": "closed", "review_result": "pass"},
            {"status": "in_progress"},
            {"status": "reviewed", "review_result": "fail"},
        ]
        scores = [{"store_id": "s1", "score": 85}, {"store_id": "s2", "score": 75}]
        result = await generate_regional_report(
            "r1", "2026-03", "t1", db=None,
            rectifications=rects, store_scores=scores,
        )
        summary = result["rectification_summary"]
        assert summary["total"] == 4
        assert summary["closed"] == 2
        assert summary["closure_rate_pct"] == 50.0
        assert summary["reviewed_fail"] == 1
        assert result["score_summary"]["avg_score"] == 80.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  归档
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRectificationArchive:
    @pytest.mark.asyncio
    async def test_archive_filters_closed(self):
        rects = [
            {"id": "r1", "status": "closed"},
            {"id": "r2", "status": "in_progress"},
            {"id": "r3", "status": "closed"},
            {"id": "r4", "status": "submitted"},
        ]
        result = await get_rectification_archive("r1", "t1", db=None, rectifications=rects)
        assert result["summary"]["archived_count"] == 2
        assert result["summary"]["pending_count"] == 2
        assert len(result["archived"]) == 2
        assert all(r["status"] == "closed" for r in result["archived"])
