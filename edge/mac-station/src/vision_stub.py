"""
图片识菜 Vision 服务 — Core ML Bridge 集成版

从纯 stub（返回固定 mock 数据）升级为调用 coreml-bridge (Swift, port 8100) 的真实
Core ML Vision 推理。

三层策略：
  1. 优先：coreml-bridge /vision/recognize 推理（M4 Neural Engine）
  2. 降级：确定性 mock 引擎（bridge 不可用时，基于图片内容的 hash 做确定性输出）
  3. 兜底：静态 mock（同原 stub，保证接口不中断）

路由注册方式（在 mac-station main.py 中添加）：
  from .vision_stub import router as vision_stub_router
  app.include_router(vision_stub_router)

注意：当前 Swift bridge (PredictHandlers.swift) 尚未实现 /vision/* 端点。
本模块在调用 bridge 失败时优雅降级到确定性 mock，当 bridge 实现 vision 端点后无需修改本文件。
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# ─── Edge API 认证 ───────────────────────────────────────────────────────────
_EDGE_TOKEN: str | None = os.getenv("EDGE_API_TOKEN")


async def _verify_edge_token(
    x_edge_token: str | None = Header(None, alias="X-Edge-Token"),
) -> None:
    if _EDGE_TOKEN is None:
        return
    if not x_edge_token or x_edge_token != _EDGE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Edge-Token",
        )


router = APIRouter(
    prefix="/vision",
    tags=["vision"],
    dependencies=[Depends(_verify_edge_token)],
)

# ─── 配置 ────────────────────────────────────────────────────────────────────

COREML_BRIDGE_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")
BRIDGE_TIMEOUT = float(os.getenv("COREML_BRIDGE_TIMEOUT", "5.0"))

# ─── 常见菜品数据库（用于确定性 mock 和 store menu 匹配） ─────────────────

_DISH_DATABASE = [
    {"dish_id": "dish_001", "dish_name": "红烧肉", "price": 68.0, "thumbnail_url": ""},
    {"dish_id": "dish_002", "dish_name": "宫保鸡丁", "price": 48.0, "thumbnail_url": ""},
    {"dish_id": "dish_003", "dish_name": "麻婆豆腐", "price": 32.0, "thumbnail_url": ""},
    {"dish_id": "dish_004", "dish_name": "鱼香肉丝", "price": 38.0, "thumbnail_url": ""},
    {"dish_id": "dish_005", "dish_name": "糖醋排骨", "price": 58.0, "thumbnail_url": ""},
    {"dish_id": "dish_006", "dish_name": "回锅肉", "price": 42.0, "thumbnail_url": ""},
    {"dish_id": "dish_007", "dish_name": "水煮鱼", "price": 78.0, "thumbnail_url": ""},
    {"dish_id": "dish_008", "dish_name": "剁椒鱼头", "price": 88.0, "thumbnail_url": ""},
    {"dish_id": "dish_009", "dish_name": "小炒黄牛肉", "price": 52.0, "thumbnail_url": ""},
    {"dish_id": "dish_010", "dish_name": "辣椒炒肉", "price": 36.0, "thumbnail_url": ""},
    {"dish_id": "dish_011", "dish_name": "蒜蓉西兰花", "price": 28.0, "thumbnail_url": ""},
    {"dish_id": "dish_012", "dish_name": "清蒸鲈鱼", "price": 88.0, "thumbnail_url": ""},
    {"dish_id": "dish_013", "dish_name": "东坡肘子", "price": 98.0, "thumbnail_url": ""},
    {"dish_id": "dish_014", "dish_name": "毛氏红烧肉", "price": 78.0, "thumbnail_url": ""},
    {"dish_id": "dish_015", "dish_name": "口味虾", "price": 88.0, "thumbnail_url": ""},
    {"dish_id": "dish_016", "dish_name": "酸菜鱼", "price": 68.0, "thumbnail_url": ""},
    {"dish_id": "dish_017", "dish_name": "干锅花菜", "price": 32.0, "thumbnail_url": ""},
    {"dish_id": "dish_018", "dish_name": "农家小炒肉", "price": 38.0, "thumbnail_url": ""},
    {"dish_id": "dish_019", "dish_name": "蛋炒饭", "price": 18.0, "thumbnail_url": ""},
    {"dish_id": "dish_020", "dish_name": "酸辣土豆丝", "price": 22.0, "thumbnail_url": ""},
]


# ─── 请求模型 ────────────────────────────────────────────────────────────────


class VisionRecognizeRequest(BaseModel):
    image_base64: str
    store_id: str


# ─── Image 解码 ──────────────────────────────────────────────────────────────


# 图片大小上限（10MB base64 编码后 ≈ 7.5MB 原始图片）
_MAX_IMAGE_BASE64_BYTES = 10 * 1024 * 1024


def _decode_image(image_base64: str) -> Optional[bytes]:
    """解码 base64 图片。

    支持 data URI (data:image/jpeg;base64,...) 和纯 base64 字符串。
    返回原始图片字节，失败返回 None。
    超过 10MB 的请求直接拒绝，防止内存耗尽攻击。
    """
    if len(image_base64) > _MAX_IMAGE_BASE64_BYTES:
        logger.warning(
            "vision.image_too_large",
            size_bytes=len(image_base64),
            max_bytes=_MAX_IMAGE_BASE64_BYTES,
        )
        return None
    try:
        # 处理 data URI 前缀
        if "," in image_base64 and image_base64.startswith("data:"):
            image_base64 = image_base64.split(",", 1)[1]
        return base64.b64decode(image_base64)
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        logger.warning("vision_decode_failed", error=str(exc))
        return None


def _image_hash_seed(image_bytes: bytes) -> int:
    """从图片字节生成确定性种子（用于 mock 一致性）"""
    digest = hashlib.md5(image_bytes).digest()  # noqa: S324 — non-security hash for deterministic mock
    return struct.unpack("<I", digest[:4])[0]


def _seeded_int(seed: int, salt: str, low: int, high: int) -> int:
    """从 seed + salt 生成 [low, high] 范围内的确定性整数"""
    h = hashlib.md5(f"{seed}:{salt}".encode()).digest()  # noqa: S324 — non-security hash for deterministic mock
    val = struct.unpack("<H", h[:2])[0]
    return low + (val % (high - low + 1))


# ─── CoreML Bridge Client ────────────────────────────────────────────────────


class VisionBridgeClient:
    """与 coreml-bridge (Swift, port 8100) 视觉端点通信的异步 HTTP 客户端。"""

    def __init__(self, base_url: str = COREML_BRIDGE_URL, timeout: float = BRIDGE_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._available: Optional[bool] = None

    async def check_health(self) -> bool:
        """快速检查 bridge 是否可达"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                self._available = resp.status_code == 200
                return self._available
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError):
            self._available = False
            return False

    async def recognize_dish(
        self, image_bytes: bytes, store_id: str, top_k: int = 5
    ) -> Optional[dict]:
        """POST /vision/recognize → 调用 Swift bridge 视觉推理。

        Args:
            image_bytes: 原始图片字节（JPEG/PNG）
            store_id: 门店 ID
            top_k: 返回 Top-K 候选

        Returns:
            成功: {"candidates": [{name, confidence}, ...], "model": str, "inference_ms": int}
            失败: None
        """
        try:
            # 将图片字节编码为 base64 发送（兼容 bridge 的 JSON 接口）
            img_b64 = base64.b64encode(image_bytes).decode("ascii")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/vision/recognize",
                    json={
                        "image_base64": img_b64,
                        "store_id": store_id,
                        "top_k": top_k,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._available = True
                    return data
                elif resp.status_code == 501:
                    # bridge 明确返回未实现
                    logger.info("vision_endpoint_not_implemented_in_bridge")
                    self._available = True  # bridge 可达但 vision 端点未就绪
                    return None
                else:
                    logger.warning(
                        "vision_bridge_error",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return None
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            self._available = False
            logger.info("vision_bridge_unreachable", error=type(e).__name__)
            return None
        except OSError as e:
            self._available = False
            logger.warning("vision_bridge_os_error", error=str(e))
            return None

    @property
    def is_available(self) -> bool:
        return self._available is True


_vision_bridge: Optional[VisionBridgeClient] = None


def _get_vision_bridge() -> VisionBridgeClient:
    global _vision_bridge
    if _vision_bridge is None:
        _vision_bridge = VisionBridgeClient()
    return _vision_bridge


# ─── 确定性 Mock（基于图片 hash） ────────────────────────────────────────────


def _deterministic_mock_recognize(image_bytes: bytes, store_id: str, top_k: int = 3) -> list[dict]:
    """基于图片内容的确定性 mock 识别。

    同一张图片多次传入返回相同结果（基于 MD5 hash 种子）。
    """
    seed = _image_hash_seed(image_bytes)
    n_dishes = len(_DISH_DATABASE)

    # 选 top_k 个不同菜品
    used_indices: set[int] = set()
    candidates: list[dict] = []

    for i in range(min(top_k + 5, n_dishes)):
        idx = _seeded_int(seed, f"dish_idx_{i}", 0, n_dishes - 1)
        if idx not in used_indices:
            used_indices.add(idx)
            # 置信度递减
            base_conf = 0.92 - len(used_indices) * 0.12
            noise = (_seeded_int(seed, f"conf_noise_{idx}", 0, 100) - 50) / 500.0
            conf = round(max(0.01, min(0.99, base_conf + noise)), 3)

            dish = _DISH_DATABASE[idx]
            candidates.append({
                "dish_id": dish["dish_id"],
                "dish_name": dish["dish_name"],
                "price": dish["price"],
                "confidence": conf,
                "thumbnail_url": dish["thumbnail_url"],
            })

        if len(candidates) >= top_k:
            break

    # 确保有 top_k 个
    while len(candidates) < top_k:
        idx = (len(candidates) * 7 + seed) % n_dishes
        if idx not in used_indices:
            used_indices.add(idx)
            dish = _DISH_DATABASE[idx]
            candidates.append({
                "dish_id": dish["dish_id"],
                "dish_name": dish["dish_name"],
                "price": dish["price"],
                "confidence": 0.05,
                "thumbnail_url": dish["thumbnail_url"],
            })
        else:
            break

    return candidates


# ─── 门店菜单匹配 ────────────────────────────────────────────────────────────


def _match_to_store_menu(
    candidates: list[dict],
    store_id: str,
) -> list[dict]:
    """将识别候选与门店菜单做匹配，过滤不在菜单中的菜品。

    Args:
        candidates: 识别候选列表 [{dish_name, confidence, ...}, ...]
        store_id: 门店 ID

    Returns:
        过滤后的候选列表。如果门店菜单不可用，返回原始候选。
    """
    # TODO: 在真实部署时，调用 tx-menu 服务的 /api/v1/menus/{store_id}/dishes 获取门店菜单
    # 目前返回原始候选，不做过滤
    logger.debug("store_menu_match_skipped", store_id=store_id, reason="menu_service_not_called_in_stub")
    return candidates


# ─── 静态 Mock（最低兜底） ──────────────────────────────────────────────────

_MOCK_MATCHES = [
    {"dish_id": "dish_002", "dish_name": "宫保鸡丁", "price": 48.0, "confidence": 0.92, "thumbnail_url": ""},
    {"dish_id": "dish_001", "dish_name": "红烧肉", "price": 68.0, "confidence": 0.75, "thumbnail_url": ""},
    {"dish_id": "dish_004", "dish_name": "鱼香茄子", "price": 38.0, "confidence": 0.68, "thumbnail_url": ""},
]


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/recognize")
async def recognize_dish(body: VisionRecognizeRequest) -> dict:
    """菜品图片识别 — CoreML Bridge 集成版。

    输入：
      image_base64: str  — JPEG/PNG base64 编码图片（支持 data URI 前缀）
      store_id: str      — 门店 ID（用于菜单匹配）

    返回：
      matches: list  — [{dish_id, dish_name, price, confidence, thumbnail_url}, ...]
      source: str    — "coreml_bridge" | "deterministic_mock" | "static_fallback"
      decoded_bytes: int — 解码后的图片字节数（仅用于日志）

    当 CoreML bridge 的 /vision/recognize 端点就绪后，自动切换为真实推理。
    """
    store_id = body.store_id

    # ── 步骤 1: 解码图片 ──
    image_bytes = _decode_image(body.image_base64)
    if image_bytes is None:
        return {
            "ok": False,
            "error": {"code": "INVALID_IMAGE", "message": "无法解码 base64 图片"},
            "matches": [],
            "source": "error",
        }

    if len(image_bytes) == 0:
        return {
            "ok": False,
            "error": {"code": "EMPTY_IMAGE", "message": "图片内容为空"},
            "matches": [],
            "source": "error",
        }

    logger.info(
        "vision_recognize_request",
        store_id=store_id,
        image_bytes=len(image_bytes),
    )

    # ── 步骤 2: 尝试 CoreML Bridge 推理 ──
    bridge = _get_vision_bridge()
    bridge_result = await bridge.recognize_dish(image_bytes, store_id, top_k=5)

    if bridge_result is not None and bridge_result.get("candidates"):
        raw_candidates = bridge_result.get("candidates", [])
        # 映射 bridge 返回字段到标准格式
        matches = []
        for c in raw_candidates[:5]:
            match = {
                "dish_id": c.get("dish_id", ""),
                "dish_name": c.get("dish_name", c.get("name", c.get("label", ""))),
                "price": c.get("price", 0.0),
                "confidence": c.get("confidence", 0.0),
                "thumbnail_url": c.get("thumbnail_url", ""),
            }
            matches.append(match)

        # 与门店菜单匹配
        matches = _match_to_store_menu(matches, store_id)

        logger.info(
            "vision_recognize_coreml",
            store_id=store_id,
            top_match=matches[0]["dish_name"] if matches else "none",
            top_confidence=matches[0]["confidence"] if matches else 0,
            source="coreml_bridge",
        )

        return {
            "ok": True,
            "matches": matches,
            "model": bridge_result.get("model", "unknown"),
            "inference_ms": bridge_result.get("inference_ms", 0),
            "source": "coreml_bridge",
        }

    # ── 步骤 3: 确定性 Mock（基于图片 hash） ──
    try:
        mock_candidates = _deterministic_mock_recognize(image_bytes, store_id, top_k=3)
        mock_candidates = _match_to_store_menu(mock_candidates, store_id)

        logger.info(
            "vision_recognize_mock",
            store_id=store_id,
            top_match=mock_candidates[0]["dish_name"] if mock_candidates else "none",
            source="deterministic_mock",
        )

        return {
            "ok": True,
            "matches": mock_candidates,
            "source": "deterministic_mock",
        }
    except (ValueError, TypeError, KeyError, struct.error) as exc:
        logger.error("deterministic_mock_failed", error=str(exc), exc_info=True)

    # ── 步骤 4: 静态 Mock（最低保证） ──
    logger.warning(
        "vision_recognize_static_fallback",
        store_id=store_id,
        image_size=len(image_bytes),
    )

    return {
        "ok": True,
        "matches": _MOCK_MATCHES,
        "source": "static_fallback",
    }


@router.get("/health")
async def vision_health() -> dict:
    """Vision 服务健康检查 — 含 CoreML bridge 可达性与模型信息。"""
    bridge = _get_vision_bridge()
    bridge_reachable = await bridge.check_health()

    return {
        "ok": True,
        "data": {
            "service": "vision",
            "mode": "coreml_bridge_integrated",
            "bridge_url": COREML_BRIDGE_URL,
            "bridge_reachable": bridge_reachable,
            "dish_database_size": len(_DISH_DATABASE),
            "note": (
                "Vision endpoint (/vision/recognize) on bridge is not yet implemented. "
                "Using deterministic mock. Will auto-switch when bridge endpoint is ready."
            ),
        },
    }
