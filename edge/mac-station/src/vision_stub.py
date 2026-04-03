"""
图片识菜 Vision Stub — Core ML Vision 接口占位实现

此文件是 Core ML Vision 推理接口的占位实现，返回合理的模拟数据。
当 coreml-bridge (Swift, port 8100) 的 /vision/recognize 接口尚未就绪时，
本 stub 可挂载到 mac-station FastAPI，作为过渡方案。

TODO: 真正集成 Core ML Vision 后，替换推理逻辑为以下步骤：
  1. 将 base64 图片解码为 PIL Image / CVPixelBuffer
  2. 加载 Core ML Vision 模型：
       import coremltools as ct
       model = ct.models.MLModel("DishClassifier.mlpackage")
  3. 预处理图片（resize to model input size, normalize）：
       import numpy as np
       from PIL import Image
       img = Image.open(...).resize((224, 224))
       arr = np.array(img).astype(np.float32) / 255.0
  4. 调用推理：
       pred = model.predict({"image": arr})
       # pred 返回 {"classLabel": "宫保鸡丁", "classLabelProbs": {...}}
  5. 将 classLabelProbs topK 结果与门店菜单 ID 做匹配，构造 matches 列表
  6. 也可使用 Apple Vision Framework (VNClassifyImageRequest) 通过 Swift 侧封装后暴露

路由注册方式（在 mac-station main.py 中添加）：
  from .vision_stub import router as vision_stub_router
  app.include_router(vision_stub_router)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/vision", tags=["vision-stub"])

# ─── Mock 识别结果（Core ML 集成后替换） ───
_MOCK_MATCHES = [
    {"dish_id": "mock_1", "dish_name": "宫保鸡丁", "price": 48.0, "confidence": 92, "thumbnail_url": ""},
    {"dish_id": "mock_2", "dish_name": "红烧肉",   "price": 68.0, "confidence": 75, "thumbnail_url": ""},
    {"dish_id": "mock_3", "dish_name": "鱼香茄子", "price": 38.0, "confidence": 68, "thumbnail_url": ""},
]


class VisionRecognizeRequest(BaseModel):
    image_base64: str
    store_id: str


@router.post("/recognize")
async def recognize_dish_stub(body: VisionRecognizeRequest) -> dict:
    """
    图片识菜 Stub。

    输入：
      image_base64: str  — JPEG/PNG base64 编码图片
      store_id: str      — 门店 ID（用于菜单匹配）

    返回：
      matches: list — [{dish_id, dish_name, price, confidence, thumbnail_url}, ...]
      source: 'stub'

    TODO: 替换为 Core ML Vision 模型推理
      - 模型文件放置路径：edge/mac-station/models/DishClassifier.mlpackage
      - 使用 VNClassifyImageRequest 进行图像分类
      - 将分类结果 label 与门店 dishes 表做字符串匹配（或向量相似度）
      - confidence 从模型 classLabelProbs 中取对应类别的概率 × 100
    """
    logger.info(
        "vision_stub_recognize",
        store_id=body.store_id,
        image_size=len(body.image_base64),
        source="stub",
    )

    return {
        "ok": True,
        "matches": _MOCK_MATCHES,
        "source": "stub",
    }


@router.get("/health")
async def vision_stub_health() -> dict:
    """Vision stub 健康检查"""
    return {
        "ok": True,
        "data": {
            "service": "vision-stub",
            "mode": "stub",
            "note": "Replace with Core ML Vision model (DishClassifier.mlpackage) when available",
        },
    }
