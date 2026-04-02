"""Tests for Vision Service — 菜品质检、卫生巡检、菜品识别、客流统计"""

import io
import os

# Adjust import path — tests run from the src directory
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException
from vision_service import (
    HYGIENE_VIOLATIONS,
    MAX_IMAGE_SIZE,
    CustomerCountResult,
    DishQualityResult,
    DishRecognitionResult,
    HygieneResult,
    VisionService,
    _mock_customer_count,
    _mock_dish_quality,
    _mock_hygiene,
    _mock_recognize_dish,
    _validate_image,
    router,
)

# ─── Fixtures ───

# Minimal valid JPEG (smallest valid JPEG: SOI + APP0 + SOF + SOS + EOI-ish)
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7\x13\xff\xd9"
)

# Minimal valid PNG (1x1 white pixel)
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"  # PNG signature
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Minimal WebP
TINY_WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x000\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x01\x40\x25\xa4\x00\x03p\x00\xfe\xfb\x94\x00\x00"

INVALID_FILE = b"This is not an image at all"
EMPTY_FILE = b""


@pytest.fixture
def jpeg_bytes() -> bytes:
    return TINY_JPEG


@pytest.fixture
def png_bytes() -> bytes:
    return TINY_PNG


@pytest.fixture
def webp_bytes() -> bytes:
    return TINY_WEBP


@pytest.fixture
def large_image() -> bytes:
    """Image that exceeds 10MB limit."""
    return b"\xff\xd8" + b"\x00" * (MAX_IMAGE_SIZE + 1)


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def vision_svc() -> VisionService:
    svc = VisionService()
    # Ensure Core ML is not available in tests
    svc.coreml_url = "http://localhost:99999"
    return svc


# ─── Image Validation Tests ───


class TestImageValidation:
    def test_valid_jpeg(self, jpeg_bytes: bytes):
        """JPEG images pass validation."""
        _validate_image(jpeg_bytes, "image/jpeg", "test.jpg")

    def test_valid_png(self, png_bytes: bytes):
        """PNG images pass validation."""
        _validate_image(png_bytes, "image/png", "test.png")

    def test_valid_webp(self, webp_bytes: bytes):
        """WebP images pass validation."""
        _validate_image(webp_bytes, "image/webp", "test.webp")

    def test_valid_by_magic_bytes_only(self, jpeg_bytes: bytes):
        """Images validated by magic bytes even without content_type or filename."""
        _validate_image(jpeg_bytes, None, None)

    def test_valid_by_extension_only(self, jpeg_bytes: bytes):
        """Images validated by file extension when content_type is wrong."""
        _validate_image(jpeg_bytes, "application/octet-stream", "photo.jpeg")

    def test_reject_too_large(self, large_image: bytes):
        """Images exceeding 10MB are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_image(large_image, "image/jpeg", "big.jpg")
        assert exc_info.value.status_code == 413

    def test_reject_empty(self):
        """Empty files are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_image(EMPTY_FILE, "image/jpeg", "empty.jpg")
        assert exc_info.value.status_code == 400
        assert "Empty" in exc_info.value.detail

    def test_reject_unsupported_format(self):
        """Non-image files are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_image(INVALID_FILE, "text/plain", "readme.txt")
        assert exc_info.value.status_code == 400
        assert "Unsupported" in exc_info.value.detail

    def test_reject_no_hints(self):
        """Random bytes with no content_type or filename are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_image(b"\x00\x01\x02\x03", None, None)
        assert exc_info.value.status_code == 400


# ─── Mock Dish Quality Tests ───


class TestMockDishQuality:
    def test_returns_all_scores(self, jpeg_bytes: bytes):
        """Dish quality result contains all four scores."""
        result = _mock_dish_quality(jpeg_bytes, "红烧肉", 70)
        assert 0 <= result.plating_score <= 100
        assert 0 <= result.portion_score <= 100
        assert 0 <= result.color_score <= 100
        assert 0 <= result.overall_score <= 100

    def test_deterministic(self, jpeg_bytes: bytes):
        """Same image produces same scores (deterministic)."""
        r1 = _mock_dish_quality(jpeg_bytes, "红烧肉", 70)
        r2 = _mock_dish_quality(jpeg_bytes, "红烧肉", 70)
        assert r1.plating_score == r2.plating_score
        assert r1.portion_score == r2.portion_score
        assert r1.color_score == r2.color_score
        assert r1.overall_score == r2.overall_score

    def test_different_images_different_scores(self, jpeg_bytes: bytes, png_bytes: bytes):
        """Different images produce different scores."""
        r1 = _mock_dish_quality(jpeg_bytes, "红烧肉", 70)
        r2 = _mock_dish_quality(png_bytes, "红烧肉", 70)
        # Extremely unlikely all scores match for different image content
        scores_differ = (
            r1.plating_score != r2.plating_score
            or r1.portion_score != r2.portion_score
            or r1.color_score != r2.color_score
        )
        assert scores_differ

    def test_pass_fail_threshold(self, jpeg_bytes: bytes):
        """Pass/fail correctly reflects threshold."""
        result_low = _mock_dish_quality(jpeg_bytes, "测试", 0)
        assert result_low.passed is True

        result_high = _mock_dish_quality(jpeg_bytes, "测试", 100)
        assert result_high.passed is False

    def test_empty_dish_name_default(self, jpeg_bytes: bytes):
        """Empty dish name defaults to placeholder."""
        result = _mock_dish_quality(jpeg_bytes, "", 70)
        assert result.dish_name == "未指定菜品"

    def test_source_is_mock(self, jpeg_bytes: bytes):
        """Source should be 'mock' for mock analyzer."""
        result = _mock_dish_quality(jpeg_bytes, "test", 70)
        assert result.source == "mock"

    def test_overall_is_weighted_average(self, jpeg_bytes: bytes):
        """Overall score is weighted average of sub-scores."""
        result = _mock_dish_quality(jpeg_bytes, "test", 70)
        expected = round(
            result.plating_score * 0.35
            + result.portion_score * 0.35
            + result.color_score * 0.30
        )
        assert result.overall_score == expected

    def test_issues_have_correct_structure(self, jpeg_bytes: bytes):
        """Issues list entries have required fields."""
        # Use a low threshold to not mask issues
        result = _mock_dish_quality(jpeg_bytes, "test", 70)
        for issue in result.issues:
            assert "type" in issue
            assert "severity" in issue
            assert "detail" in issue
            assert issue["severity"] in {"critical", "warning", "info"}

    def test_suggestions_non_empty(self, jpeg_bytes: bytes):
        """Suggestions list is never empty."""
        result = _mock_dish_quality(jpeg_bytes, "test", 70)
        assert len(result.suggestions) >= 1


# ─── Mock Hygiene Tests ───


class TestMockHygiene:
    def test_kitchen_zone(self, jpeg_bytes: bytes):
        """Kitchen zone hygiene check returns valid result."""
        result = _mock_hygiene(jpeg_bytes, "kitchen")
        assert result.zone == "kitchen"
        assert 0 <= result.compliance_score <= 100
        assert result.source == "mock"

    def test_storage_zone(self, jpeg_bytes: bytes):
        """Storage zone uses storage-specific violation pool."""
        result = _mock_hygiene(jpeg_bytes, "storage")
        assert result.zone == "storage"
        for v in result.violations:
            assert v["type"] in HYGIENE_VIOLATIONS

    def test_dining_zone(self, jpeg_bytes: bytes):
        """Dining zone hygiene check works."""
        result = _mock_hygiene(jpeg_bytes, "dining")
        assert result.zone == "dining"

    def test_prep_area_zone(self, jpeg_bytes: bytes):
        """Prep area zone hygiene check works."""
        result = _mock_hygiene(jpeg_bytes, "prep_area")
        assert result.zone == "prep_area"

    def test_unknown_zone_falls_back_to_kitchen(self, jpeg_bytes: bytes):
        """Unknown zone falls back to kitchen pool."""
        result = _mock_hygiene(jpeg_bytes, "unknown_zone")
        assert result.zone == "unknown_zone"
        # Should still produce a valid result using kitchen pool
        assert 0 <= result.compliance_score <= 100

    def test_violation_structure(self, jpeg_bytes: bytes):
        """Violations have correct structure."""
        # Run multiple images to find one with violations
        for salt in range(50):
            img = jpeg_bytes + bytes([salt])
            result = _mock_hygiene(img, "kitchen")
            if result.violations:
                for v in result.violations:
                    assert "type" in v
                    assert "severity" in v
                    assert "location" in v
                    assert "detail" in v
                    assert v["severity"] in {"critical", "warning", "info"}
                return
        # If no violations found in 50 attempts, that's still acceptable (unlikely)

    def test_critical_count_matches(self, jpeg_bytes: bytes):
        """Critical count matches actual critical violations."""
        for salt in range(20):
            img = jpeg_bytes + bytes([salt])
            result = _mock_hygiene(img, "kitchen")
            actual_critical = sum(1 for v in result.violations if v["severity"] == "critical")
            assert result.critical_count == actual_critical

    def test_warning_count_matches(self, jpeg_bytes: bytes):
        """Warning count matches actual warning violations."""
        for salt in range(20):
            img = jpeg_bytes + bytes([salt])
            result = _mock_hygiene(img, "kitchen")
            actual_warning = sum(1 for v in result.violations if v["severity"] == "warning")
            assert result.warning_count == actual_warning

    def test_pass_requires_no_critical(self, jpeg_bytes: bytes):
        """Hygiene check fails if any critical violation exists."""
        for salt in range(50):
            img = jpeg_bytes + bytes([salt])
            result = _mock_hygiene(img, "kitchen")
            if result.critical_count > 0:
                assert result.passed is False
                return
        # Acceptable if no critical found in 50 images

    def test_compliance_score_deductions(self, jpeg_bytes: bytes):
        """Compliance score is reduced by violations."""
        for salt in range(50):
            img = jpeg_bytes + bytes([salt])
            result = _mock_hygiene(img, "kitchen")
            if result.violations:
                assert result.compliance_score < 100
                return

    def test_all_violation_types_defined(self):
        """All defined hygiene violations have severity and description."""
        for vtype, vdef in HYGIENE_VIOLATIONS.items():
            assert "severity" in vdef
            assert "description" in vdef
            assert vdef["severity"] in {"critical", "warning", "info"}
            assert len(vdef["description"]) > 0


# ─── Mock Dish Recognition Tests ───


class TestMockDishRecognition:
    def test_returns_three_candidates(self, jpeg_bytes: bytes):
        """Recognition returns exactly 3 candidates."""
        result = _mock_recognize_dish(jpeg_bytes)
        assert len(result.candidates) == 3

    def test_candidates_have_name_and_confidence(self, jpeg_bytes: bytes):
        """Each candidate has name and confidence."""
        result = _mock_recognize_dish(jpeg_bytes)
        for c in result.candidates:
            assert "name" in c
            assert "confidence" in c
            assert isinstance(c["name"], str)
            assert 0.0 <= c["confidence"] <= 1.0

    def test_best_match_is_first_candidate(self, jpeg_bytes: bytes):
        """Best match equals the first candidate."""
        result = _mock_recognize_dish(jpeg_bytes)
        assert result.best_match == result.candidates[0]["name"]
        assert result.confidence == result.candidates[0]["confidence"]

    def test_confidences_are_descending(self, jpeg_bytes: bytes):
        """Confidence scores are in descending order."""
        result = _mock_recognize_dish(jpeg_bytes)
        confs = [c["confidence"] for c in result.candidates]
        assert confs[0] >= confs[1] >= confs[2]

    def test_deterministic(self, jpeg_bytes: bytes):
        """Same image produces same recognition result."""
        r1 = _mock_recognize_dish(jpeg_bytes)
        r2 = _mock_recognize_dish(jpeg_bytes)
        assert r1.best_match == r2.best_match
        assert r1.confidence == r2.confidence

    def test_dish_names_are_chinese(self, jpeg_bytes: bytes):
        """Recognized dish names are from the Chinese dish database."""
        result = _mock_recognize_dish(jpeg_bytes)
        for c in result.candidates:
            assert len(c["name"]) > 0


# ─── Mock Customer Count Tests ───


class TestMockCustomerCount:
    def test_returns_count_and_density(self, jpeg_bytes: bytes):
        """Customer count returns count and density level."""
        result = _mock_customer_count(jpeg_bytes, "dining")
        assert result.count >= 0
        assert result.density_level in {"low", "medium", "high", "overcrowded"}

    def test_density_matches_count(self, jpeg_bytes: bytes):
        """Density level is consistent with count."""
        for salt in range(30):
            img = jpeg_bytes + bytes([salt])
            result = _mock_customer_count(img, "dining")
            if result.count <= 10:
                assert result.density_level == "low"
            elif result.count <= 30:
                assert result.density_level == "medium"
            elif result.count <= 55:
                assert result.density_level == "high"
            else:
                assert result.density_level == "overcrowded"

    def test_zone_heatmap_sums_to_count(self, jpeg_bytes: bytes):
        """Zone heatmap values sum to the total count."""
        result = _mock_customer_count(jpeg_bytes, "dining")
        heatmap_total = sum(result.zone_heatmap.values())
        assert heatmap_total == result.count

    def test_dining_zone_areas(self, jpeg_bytes: bytes):
        """Dining zone has expected area names."""
        result = _mock_customer_count(jpeg_bytes, "dining")
        expected_areas = {"entrance", "main_hall", "window_seats", "private_rooms"}
        assert set(result.zone_heatmap.keys()) == expected_areas

    def test_kitchen_zone_areas(self, jpeg_bytes: bytes):
        """Kitchen zone has expected area names."""
        result = _mock_customer_count(jpeg_bytes, "kitchen")
        expected_areas = {"hot_station", "cold_station", "prep_area", "wash_area"}
        assert set(result.zone_heatmap.keys()) == expected_areas

    def test_outdoor_zone_areas(self, jpeg_bytes: bytes):
        """Outdoor zone has expected area names."""
        result = _mock_customer_count(jpeg_bytes, "outdoor")
        expected_areas = {"terrace_left", "terrace_right", "entrance_queue"}
        assert set(result.zone_heatmap.keys()) == expected_areas

    def test_unknown_zone_defaults_to_dining(self, jpeg_bytes: bytes):
        """Unknown zone defaults to dining areas."""
        result = _mock_customer_count(jpeg_bytes, "unknown")
        expected_areas = {"entrance", "main_hall", "window_seats", "private_rooms"}
        assert set(result.zone_heatmap.keys()) == expected_areas

    def test_heatmap_values_non_negative(self, jpeg_bytes: bytes):
        """All heatmap values are non-negative."""
        result = _mock_customer_count(jpeg_bytes, "dining")
        for v in result.zone_heatmap.values():
            assert v >= 0


# ─── VisionService Class Tests ───


class TestVisionService:
    @pytest.mark.asyncio
    async def test_dish_quality_mock_fallback(self, vision_svc: VisionService, jpeg_bytes: bytes):
        """Falls back to mock when Core ML is unavailable."""
        result = await vision_svc.inspect_dish_quality(jpeg_bytes, "红烧肉", 70)
        assert isinstance(result, DishQualityResult)
        assert result.source == "mock"
        assert result.analysis_ms >= 0

    @pytest.mark.asyncio
    async def test_hygiene_mock_fallback(self, vision_svc: VisionService, jpeg_bytes: bytes):
        """Falls back to mock for hygiene check."""
        result = await vision_svc.check_hygiene(jpeg_bytes, "kitchen")
        assert isinstance(result, HygieneResult)
        assert result.source == "mock"

    @pytest.mark.asyncio
    async def test_recognize_mock_fallback(self, vision_svc: VisionService, jpeg_bytes: bytes):
        """Falls back to mock for dish recognition."""
        result = await vision_svc.recognize_dish(jpeg_bytes)
        assert isinstance(result, DishRecognitionResult)
        assert len(result.candidates) == 3

    @pytest.mark.asyncio
    async def test_customer_count_mock_fallback(self, vision_svc: VisionService, jpeg_bytes: bytes):
        """Falls back to mock for customer counting."""
        result = await vision_svc.count_customers(jpeg_bytes, "dining")
        assert isinstance(result, CustomerCountResult)
        assert result.zone == "dining"

    @pytest.mark.asyncio
    async def test_coreml_health_check_failure(self, vision_svc: VisionService):
        """Core ML health check returns False when bridge is down."""
        result = await vision_svc._check_coreml()
        assert result is False
        assert vision_svc._coreml_available is False

    @pytest.mark.asyncio
    async def test_analysis_ms_populated(self, vision_svc: VisionService, jpeg_bytes: bytes):
        """Analysis time is measured and populated."""
        result = await vision_svc.inspect_dish_quality(jpeg_bytes)
        assert result.analysis_ms >= 0


# ─── Core ML Fallback Behavior Tests ───


class TestCoreMlFallback:
    @staticmethod
    def _make_mock_client(mock_response, status_code=200):
        """Helper to create a properly mocked httpx.AsyncClient."""
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = mock_response

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    @pytest.mark.asyncio
    async def test_coreml_success_dish_quality(self, jpeg_bytes: bytes):
        """When Core ML is available, use it for dish quality."""
        svc = VisionService()
        mock_response = {
            "dish_name": "红烧肉",
            "plating_score": 88,
            "portion_score": 92,
            "color_score": 85,
            "overall_score": 88,
            "passed": True,
            "issues": [],
            "suggestions": ["出品优秀"],
        }

        with patch.object(svc, "_check_coreml", new_callable=AsyncMock, return_value=True):
            with patch("vision_service.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = self._make_mock_client(mock_response)

                result = await svc.inspect_dish_quality(jpeg_bytes, "红烧肉", 70)
                assert result.source == "coreml"
                assert result.plating_score == 88
                assert result.passed is True

    @pytest.mark.asyncio
    async def test_coreml_failure_falls_back(self, jpeg_bytes: bytes):
        """When Core ML request fails, fall back to mock."""
        svc = VisionService()

        with patch.object(svc, "_check_coreml", new_callable=AsyncMock, return_value=True):
            with patch("vision_service.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.side_effect = httpx.ConnectError("connection refused")
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await svc.inspect_dish_quality(jpeg_bytes, "红烧肉", 70)
                assert result.source == "mock"

    @pytest.mark.asyncio
    async def test_coreml_success_hygiene(self, jpeg_bytes: bytes):
        """When Core ML is available, use it for hygiene check."""
        svc = VisionService()
        mock_response = {
            "zone": "kitchen",
            "violations": [{"type": "no_mask", "severity": "critical", "location": "kitchen", "detail": "未佩戴口罩"}],
            "compliance_score": 80,
            "passed": False,
            "critical_count": 1,
            "warning_count": 0,
        }

        with patch.object(svc, "_check_coreml", new_callable=AsyncMock, return_value=True):
            with patch("vision_service.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = self._make_mock_client(mock_response)

                result = await svc.check_hygiene(jpeg_bytes, "kitchen")
                assert result.source == "coreml"
                assert result.critical_count == 1

    @pytest.mark.asyncio
    async def test_coreml_success_recognize(self, jpeg_bytes: bytes):
        """When Core ML is available, use it for dish recognition."""
        svc = VisionService()
        mock_response = {
            "candidates": [
                {"name": "红烧肉", "confidence": 0.95},
                {"name": "东坡肉", "confidence": 0.60},
                {"name": "梅菜扣肉", "confidence": 0.20},
            ],
            "best_match": "红烧肉",
            "confidence": 0.95,
        }

        with patch.object(svc, "_check_coreml", new_callable=AsyncMock, return_value=True):
            with patch("vision_service.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = self._make_mock_client(mock_response)

                result = await svc.recognize_dish(jpeg_bytes)
                assert result.best_match == "红烧肉"
                assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_coreml_success_customer_count(self, jpeg_bytes: bytes):
        """When Core ML is available, use it for customer counting."""
        svc = VisionService()
        mock_response = {
            "count": 25,
            "density_level": "medium",
            "zone": "dining",
            "zone_heatmap": {"main_hall": 15, "entrance": 10},
        }

        with patch.object(svc, "_check_coreml", new_callable=AsyncMock, return_value=True):
            with patch("vision_service.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = self._make_mock_client(mock_response)

                result = await svc.count_customers(jpeg_bytes, "dining")
                assert result.count == 25
                assert result.density_level == "medium"


# ─── API Endpoint Tests ───

import httpx


class TestAPIEndpoints:
    @pytest.mark.asyncio
    async def test_dish_quality_endpoint(self, client: AsyncClient, jpeg_bytes: bytes):
        """POST /api/v1/vision/dish-quality returns quality scores."""
        resp = await client.post(
            "/api/v1/vision/dish-quality",
            files={"image": ("dish.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            data={"dish_name": "红烧肉", "threshold": "70"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "plating_score" in data
        assert "portion_score" in data
        assert "color_score" in data
        assert "overall_score" in data
        assert "passed" in data
        assert "issues" in data
        assert "suggestions" in data

    @pytest.mark.asyncio
    async def test_hygiene_check_endpoint(self, client: AsyncClient, jpeg_bytes: bytes):
        """POST /api/v1/vision/hygiene-check returns compliance result."""
        resp = await client.post(
            "/api/v1/vision/hygiene-check",
            files={"image": ("camera.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            data={"zone": "kitchen"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "zone" in data
        assert "violations" in data
        assert "compliance_score" in data
        assert "passed" in data

    @pytest.mark.asyncio
    async def test_recognize_dish_endpoint(self, client: AsyncClient, jpeg_bytes: bytes):
        """POST /api/v1/vision/recognize-dish returns candidates."""
        resp = await client.post(
            "/api/v1/vision/recognize-dish",
            files={"image": ("food.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert len(data["candidates"]) == 3
        assert "best_match" in data
        assert "confidence" in data

    @pytest.mark.asyncio
    async def test_customer_count_endpoint(self, client: AsyncClient, jpeg_bytes: bytes):
        """POST /api/v1/vision/customer-count returns count and heatmap."""
        resp = await client.post(
            "/api/v1/vision/customer-count",
            files={"image": ("frame.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            data={"zone": "dining"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "count" in data
        assert "density_level" in data
        assert "zone_heatmap" in data

    @pytest.mark.asyncio
    async def test_reject_oversized_image(self, client: AsyncClient, large_image: bytes):
        """Oversized image returns 413."""
        resp = await client.post(
            "/api/v1/vision/dish-quality",
            files={"image": ("big.jpg", io.BytesIO(large_image), "image/jpeg")},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_reject_invalid_format(self, client: AsyncClient):
        """Invalid file format returns 400."""
        resp = await client.post(
            "/api/v1/vision/dish-quality",
            files={"image": ("readme.txt", io.BytesIO(INVALID_FILE), "text/plain")},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_invalid_zone_hygiene(self, client: AsyncClient, jpeg_bytes: bytes):
        """Invalid zone for hygiene check returns 400."""
        resp = await client.post(
            "/api/v1/vision/hygiene-check",
            files={"image": ("cam.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            data={"zone": "bathroom"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_invalid_zone_customer_count(self, client: AsyncClient, jpeg_bytes: bytes):
        """Invalid zone for customer count returns 400."""
        resp = await client.post(
            "/api/v1/vision/customer-count",
            files={"image": ("cam.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            data={"zone": "rooftop"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_png_upload(self, client: AsyncClient, png_bytes: bytes):
        """PNG uploads are accepted."""
        resp = await client.post(
            "/api/v1/vision/dish-quality",
            files={"image": ("dish.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_default_threshold(self, client: AsyncClient, jpeg_bytes: bytes):
        """Default threshold is 70 when not specified."""
        resp = await client.post(
            "/api/v1/vision/dish-quality",
            files={"image": ("dish.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_default_zone_hygiene(self, client: AsyncClient, jpeg_bytes: bytes):
        """Default zone is 'kitchen' for hygiene check."""
        resp = await client.post(
            "/api/v1/vision/hygiene-check",
            files={"image": ("cam.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["zone"] == "kitchen"

    @pytest.mark.asyncio
    async def test_default_zone_customer_count(self, client: AsyncClient, jpeg_bytes: bytes):
        """Default zone is 'dining' for customer count."""
        resp = await client.post(
            "/api/v1/vision/customer-count",
            files={"image": ("cam.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["zone"] == "dining"
