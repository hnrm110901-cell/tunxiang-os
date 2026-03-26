"""Vision Service — 门店视觉AI服务

提供菜品质检、卫生巡检、菜品识别、客流统计等视觉分析能力。
当 Core ML Bridge 可用时转发请求，否则使用内置 mock 分析器。
"""

import hashlib
import os
import struct
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

logger = structlog.get_logger()

COREML_BRIDGE_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
SUPPORTED_FORMATS = {"image/jpeg", "image/png", "image/webp"}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# ─── Hygiene violation definitions ───

HYGIENE_VIOLATIONS = {
    "no_mask": {"severity": "critical", "description": "未佩戴口罩"},
    "no_hat": {"severity": "critical", "description": "未佩戴厨师帽"},
    "no_gloves": {"severity": "warning", "description": "未佩戴手套"},
    "dirty_uniform": {"severity": "warning", "description": "工服不洁"},
    "no_uniform": {"severity": "critical", "description": "未穿工服"},
    "floor_dirty": {"severity": "warning", "description": "地面不洁"},
    "raw_cooked_mix": {"severity": "critical", "description": "生熟混放"},
    "temp_violation": {"severity": "critical", "description": "温度不达标"},
    "expired_food": {"severity": "critical", "description": "过期食材"},
    "pest_detected": {"severity": "critical", "description": "发现虫害"},
    "improper_storage": {"severity": "warning", "description": "食材存放不当"},
    "cluttered_workspace": {"severity": "info", "description": "工作台面杂乱"},
}

# ─── Data Models ───


@dataclass
class DishQualityResult:
    dish_name: str
    plating_score: int
    portion_score: int
    color_score: int
    overall_score: int
    passed: bool
    issues: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    analysis_ms: int = 0
    source: str = "mock"


@dataclass
class HygieneResult:
    zone: str
    violations: list[dict] = field(default_factory=list)
    compliance_score: int = 100
    passed: bool = True
    critical_count: int = 0
    warning_count: int = 0
    analysis_ms: int = 0
    source: str = "mock"


@dataclass
class DishRecognitionResult:
    candidates: list[dict] = field(default_factory=list)
    best_match: str = ""
    confidence: float = 0.0
    analysis_ms: int = 0


@dataclass
class CustomerCountResult:
    count: int = 0
    density_level: str = "low"
    zone: str = "dining"
    zone_heatmap: dict = field(default_factory=dict)
    analysis_ms: int = 0


# ─── Image Validation ───


def _validate_image(image_bytes: bytes, content_type: Optional[str], filename: Optional[str]) -> None:
    """Validate image size and format. Raises HTTPException on failure."""
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large: {len(image_bytes)} bytes. Max allowed: {MAX_IMAGE_SIZE} bytes (10MB).",
        )

    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty image file.")

    # Check by content type
    format_ok = False
    if content_type and content_type in SUPPORTED_FORMATS:
        format_ok = True

    # Check by file extension
    if not format_ok and filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            format_ok = True

    # Check by magic bytes
    if not format_ok:
        if image_bytes[:2] == b"\xff\xd8":
            format_ok = True  # JPEG
        elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            format_ok = True  # PNG
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            format_ok = True  # WebP

    if not format_ok:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format. Supported: JPEG, PNG, WebP.",
        )


def _image_hash_seed(image_bytes: bytes) -> int:
    """Derive a deterministic seed from image content for consistent mock results."""
    digest = hashlib.md5(image_bytes).digest()
    return struct.unpack("<I", digest[:4])[0]


# ─── Mock Analyzer (deterministic based on image content) ───


def _seeded_score(seed: int, salt: str, low: int = 55, high: int = 98) -> int:
    """Generate a deterministic score in [low, high] from seed + salt."""
    h = hashlib.md5(f"{seed}:{salt}".encode()).digest()
    val = struct.unpack("<H", h[:2])[0]
    return low + (val % (high - low + 1))


def _seeded_float(seed: int, salt: str) -> float:
    """Generate a deterministic float in [0.0, 1.0) from seed + salt."""
    h = hashlib.md5(f"{seed}:{salt}".encode()).digest()
    val = struct.unpack("<I", h[:4])[0]
    return val / 0xFFFFFFFF


def _mock_dish_quality(image_bytes: bytes, dish_name: str, threshold: int) -> DishQualityResult:
    """Mock dish quality inspection with realistic, deterministic scores."""
    seed = _image_hash_seed(image_bytes)

    plating = _seeded_score(seed, "plating", 50, 98)
    portion = _seeded_score(seed, "portion", 45, 99)
    color = _seeded_score(seed, "color", 55, 97)
    overall = round(plating * 0.35 + portion * 0.35 + color * 0.30)

    issues: list[dict] = []
    suggestions: list[str] = []

    if portion < 65:
        issues.append({
            "type": "portion_too_small",
            "severity": "warning",
            "detail": f"分量评分 {portion} 低于标准，建议检查配料称重。",
        })
        suggestions.append("请确认出品份量是否符合SOP标准。")

    if plating < 60:
        issues.append({
            "type": "uneven_plating",
            "severity": "warning",
            "detail": f"摆盘评分 {plating}，摆盘不够整齐美观。",
        })
        suggestions.append("注意摆盘对称性和装饰点缀。")

    if color < 60:
        issues.append({
            "type": "color_abnormal",
            "severity": "warning",
            "detail": f"色泽评分 {color}，菜品颜色偏离标准。",
        })
        suggestions.append("检查烹饪火候和调味是否符合标准。")

    # Occasionally flag garnish issue
    if _seeded_float(seed, "garnish") < 0.15:
        issues.append({
            "type": "wrong_garnish",
            "severity": "info",
            "detail": "装饰配料可能与标准不符。",
        })
        suggestions.append("请对照标准菜品图片核对装饰。")

    if not suggestions:
        suggestions.append("出品质量良好，继续保持。")

    name = dish_name if dish_name else "未指定菜品"

    return DishQualityResult(
        dish_name=name,
        plating_score=plating,
        portion_score=portion,
        color_score=color,
        overall_score=overall,
        passed=overall >= threshold,
        issues=issues,
        suggestions=suggestions,
        source="mock",
    )


# Zone-specific violation pools
_ZONE_VIOLATION_POOLS: dict[str, list[str]] = {
    "kitchen": [
        "no_mask", "no_hat", "no_gloves", "dirty_uniform", "no_uniform",
        "floor_dirty", "raw_cooked_mix", "cluttered_workspace",
    ],
    "storage": [
        "temp_violation", "expired_food", "improper_storage",
        "raw_cooked_mix", "pest_detected", "floor_dirty",
    ],
    "dining": [
        "floor_dirty", "cluttered_workspace", "pest_detected",
    ],
    "prep_area": [
        "no_mask", "no_hat", "no_gloves", "dirty_uniform",
        "raw_cooked_mix", "cluttered_workspace", "floor_dirty",
    ],
}


def _mock_hygiene(image_bytes: bytes, zone: str) -> HygieneResult:
    """Mock hygiene inspection with zone-aware violation detection."""
    seed = _image_hash_seed(image_bytes)

    pool = _ZONE_VIOLATION_POOLS.get(zone, _ZONE_VIOLATION_POOLS["kitchen"])

    violations: list[dict] = []
    for vtype in pool:
        prob = _seeded_float(seed, f"hygiene_{vtype}")
        # Each violation has roughly 20% chance of appearing
        if prob < 0.20:
            vdef = HYGIENE_VIOLATIONS[vtype]
            violations.append({
                "type": vtype,
                "severity": vdef["severity"],
                "location": zone,
                "detail": vdef["description"],
            })

    critical_count = sum(1 for v in violations if v["severity"] == "critical")
    warning_count = sum(1 for v in violations if v["severity"] == "warning")
    info_count = sum(1 for v in violations if v["severity"] == "info")

    # Score: start at 100, deduct per violation
    score = 100 - critical_count * 20 - warning_count * 10 - info_count * 3
    score = max(0, min(100, score))

    passed = critical_count == 0 and score >= 70

    return HygieneResult(
        zone=zone,
        violations=violations,
        compliance_score=score,
        passed=passed,
        critical_count=critical_count,
        warning_count=warning_count,
        source="mock",
    )


# Common Chinese dish names for recognition mock
_DISH_DATABASE = [
    "红烧肉", "宫保鸡丁", "麻婆豆腐", "鱼香肉丝", "糖醋排骨",
    "回锅肉", "水煮鱼", "剁椒鱼头", "小炒黄牛肉", "辣椒炒肉",
    "蒜蓉西兰花", "清蒸鲈鱼", "东坡肘子", "毛氏红烧肉", "口味虾",
    "酸菜鱼", "干锅花菜", "农家小炒肉", "蛋炒饭", "酸辣土豆丝",
    "番茄炒蛋", "可乐鸡翅", "烤鱼", "水煮肉片", "京酱肉丝",
    "啤酒鸭", "铁板牛肉", "松鼠桂鱼", "蒜香排骨", "香辣蟹",
]


def _mock_recognize_dish(image_bytes: bytes) -> DishRecognitionResult:
    """Mock dish recognition returning top-3 candidates."""
    seed = _image_hash_seed(image_bytes)

    # Pick 3 distinct dishes deterministically
    indices: list[int] = []
    for i in range(10):
        idx = _seeded_score(seed, f"dish_idx_{i}", 0, len(_DISH_DATABASE) - 1)
        if idx not in indices:
            indices.append(idx)
        if len(indices) == 3:
            break

    # Ensure we have 3
    while len(indices) < 3:
        indices.append((indices[-1] + 7) % len(_DISH_DATABASE))

    # Generate descending confidence scores
    conf1 = 0.70 + _seeded_float(seed, "conf1") * 0.25  # 0.70-0.95
    conf2 = 0.30 + _seeded_float(seed, "conf2") * 0.30  # 0.30-0.60
    conf3 = 0.05 + _seeded_float(seed, "conf3") * 0.20  # 0.05-0.25

    candidates = [
        {"name": _DISH_DATABASE[indices[0]], "confidence": round(conf1, 3)},
        {"name": _DISH_DATABASE[indices[1]], "confidence": round(conf2, 3)},
        {"name": _DISH_DATABASE[indices[2]], "confidence": round(conf3, 3)},
    ]

    return DishRecognitionResult(
        candidates=candidates,
        best_match=candidates[0]["name"],
        confidence=candidates[0]["confidence"],
    )


def _mock_customer_count(image_bytes: bytes, zone: str) -> CustomerCountResult:
    """Mock customer counting with zone heatmap."""
    seed = _image_hash_seed(image_bytes)

    count = _seeded_score(seed, "count", 0, 80)

    if count <= 10:
        density = "low"
    elif count <= 30:
        density = "medium"
    elif count <= 55:
        density = "high"
    else:
        density = "overcrowded"

    # Generate sub-zone counts that sum to total
    zone_areas = {
        "dining": ["entrance", "main_hall", "window_seats", "private_rooms"],
        "kitchen": ["hot_station", "cold_station", "prep_area", "wash_area"],
        "outdoor": ["terrace_left", "terrace_right", "entrance_queue"],
    }

    areas = zone_areas.get(zone, zone_areas["dining"])
    heatmap: dict[str, int] = {}
    remaining = count
    for i, area in enumerate(areas):
        if i == len(areas) - 1:
            heatmap[area] = remaining
        else:
            portion_f = _seeded_float(seed, f"zone_{area}")
            portion = int(remaining * portion_f * 0.6)
            portion = max(0, min(remaining, portion))
            heatmap[area] = portion
            remaining -= portion

    return CustomerCountResult(
        count=count,
        density_level=density,
        zone=zone,
        zone_heatmap=heatmap,
    )


# ─── VisionService Class ───


class VisionService:
    """Vision analysis service with Core ML fallback to mock."""

    def __init__(self) -> None:
        self.model_loaded = False
        self.coreml_url = COREML_BRIDGE_URL
        self._coreml_available: Optional[bool] = None

    async def _check_coreml(self) -> bool:
        """Check if Core ML bridge is reachable."""
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"{self.coreml_url}/health")
                if resp.status_code == 200:
                    self._coreml_available = True
                    self.model_loaded = True
                    return True
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError):
            pass
        except OSError:
            pass
        self._coreml_available = False
        return False

    async def inspect_dish_quality(
        self, image_bytes: bytes, dish_name: str = "", threshold: int = 70
    ) -> DishQualityResult:
        """Inspect dish presentation quality."""
        start = time.monotonic()

        if await self._check_coreml():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{self.coreml_url}/vision/dish-quality",
                        content=image_bytes,
                        headers={"Content-Type": "application/octet-stream"},
                        params={"dish_name": dish_name, "threshold": threshold},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        elapsed = int((time.monotonic() - start) * 1000)
                        return DishQualityResult(
                            dish_name=data.get("dish_name", dish_name),
                            plating_score=data.get("plating_score", 0),
                            portion_score=data.get("portion_score", 0),
                            color_score=data.get("color_score", 0),
                            overall_score=data.get("overall_score", 0),
                            passed=data.get("passed", False),
                            issues=data.get("issues", []),
                            suggestions=data.get("suggestions", []),
                            analysis_ms=elapsed,
                            source="coreml",
                        )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("coreml_dish_quality_failed", error=str(exc))

        # Fallback to mock
        result = _mock_dish_quality(image_bytes, dish_name, threshold)
        result.analysis_ms = int((time.monotonic() - start) * 1000)
        return result

    async def check_hygiene(
        self, image_bytes: bytes, zone: str = "kitchen"
    ) -> HygieneResult:
        """Check hygiene compliance from camera image."""
        start = time.monotonic()

        if await self._check_coreml():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{self.coreml_url}/vision/hygiene-check",
                        content=image_bytes,
                        headers={"Content-Type": "application/octet-stream"},
                        params={"zone": zone},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        elapsed = int((time.monotonic() - start) * 1000)
                        return HygieneResult(
                            zone=data.get("zone", zone),
                            violations=data.get("violations", []),
                            compliance_score=data.get("compliance_score", 0),
                            passed=data.get("passed", False),
                            critical_count=data.get("critical_count", 0),
                            warning_count=data.get("warning_count", 0),
                            analysis_ms=elapsed,
                            source="coreml",
                        )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("coreml_hygiene_check_failed", error=str(exc))

        result = _mock_hygiene(image_bytes, zone)
        result.analysis_ms = int((time.monotonic() - start) * 1000)
        return result

    async def recognize_dish(self, image_bytes: bytes) -> DishRecognitionResult:
        """Recognize dish from photo, returning top-3 candidates."""
        start = time.monotonic()

        if await self._check_coreml():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{self.coreml_url}/vision/recognize-dish",
                        content=image_bytes,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        elapsed = int((time.monotonic() - start) * 1000)
                        return DishRecognitionResult(
                            candidates=data.get("candidates", []),
                            best_match=data.get("best_match", ""),
                            confidence=data.get("confidence", 0.0),
                            analysis_ms=elapsed,
                        )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("coreml_recognize_dish_failed", error=str(exc))

        result = _mock_recognize_dish(image_bytes)
        result.analysis_ms = int((time.monotonic() - start) * 1000)
        return result

    async def count_customers(
        self, image_bytes: bytes, zone: str = "dining"
    ) -> CustomerCountResult:
        """Count customers in camera frame."""
        start = time.monotonic()

        if await self._check_coreml():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{self.coreml_url}/vision/customer-count",
                        content=image_bytes,
                        headers={"Content-Type": "application/octet-stream"},
                        params={"zone": zone},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        elapsed = int((time.monotonic() - start) * 1000)
                        return CustomerCountResult(
                            count=data.get("count", 0),
                            density_level=data.get("density_level", "low"),
                            zone=data.get("zone", zone),
                            zone_heatmap=data.get("zone_heatmap", {}),
                            analysis_ms=elapsed,
                        )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("coreml_customer_count_failed", error=str(exc))

        result = _mock_customer_count(image_bytes, zone)
        result.analysis_ms = int((time.monotonic() - start) * 1000)
        return result


# ─── Singleton ───

vision_service = VisionService()

# ─── FastAPI Router ───

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])


@router.post("/dish-quality")
async def api_dish_quality(
    image: UploadFile = File(...),
    dish_name: str = Form(default=""),
    threshold: int = Form(default=70),
) -> dict:
    """菜品出品质量检测

    上传菜品照片，返回摆盘、分量、色泽评分及综合质量判定。
    """
    image_bytes = await image.read()
    _validate_image(image_bytes, image.content_type, image.filename)

    if threshold < 0 or threshold > 100:
        raise HTTPException(status_code=400, detail="Threshold must be between 0 and 100.")

    result = await vision_service.inspect_dish_quality(image_bytes, dish_name, threshold)
    return {"ok": True, "data": asdict(result)}


@router.post("/hygiene-check")
async def api_hygiene_check(
    image: UploadFile = File(...),
    zone: str = Form(default="kitchen"),
) -> dict:
    """卫生合规巡检

    上传门店摄像头画面，检测卫生违规项（口罩、帽子、整洁度等）。
    """
    image_bytes = await image.read()
    _validate_image(image_bytes, image.content_type, image.filename)

    valid_zones = {"kitchen", "storage", "dining", "prep_area"}
    if zone not in valid_zones:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid zone '{zone}'. Valid zones: {', '.join(sorted(valid_zones))}.",
        )

    result = await vision_service.check_hygiene(image_bytes, zone)
    return {"ok": True, "data": asdict(result)}


@router.post("/recognize-dish")
async def api_recognize_dish(
    image: UploadFile = File(...),
) -> dict:
    """菜品识别

    上传菜品照片，返回 Top-3 候选菜名及置信度。
    用于菜单数字化、订单核验、餐厨废弃物分类。
    """
    image_bytes = await image.read()
    _validate_image(image_bytes, image.content_type, image.filename)

    result = await vision_service.recognize_dish(image_bytes)
    return {"ok": True, "data": asdict(result)}


@router.post("/customer-count")
async def api_customer_count(
    image: UploadFile = File(...),
    zone: str = Form(default="dining"),
) -> dict:
    """客流统计

    上传摄像头画面，统计画面中的顾客人数及密度。
    用于 serve_dispatch Agent 的桌位分配优化。
    """
    image_bytes = await image.read()
    _validate_image(image_bytes, image.content_type, image.filename)

    valid_zones = {"dining", "kitchen", "outdoor"}
    if zone not in valid_zones:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid zone '{zone}'. Valid zones: {', '.join(sorted(valid_zones))}.",
        )

    result = await vision_service.count_customers(image_bytes, zone)
    return {"ok": True, "data": asdict(result)}
