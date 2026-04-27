"""Activity ROI Prediction Agent (D3b)

营销活动 ROI 预测：Prophet 基线 + Sonnet 中文叙述，目标 MAPE < 20%。
"""

from .schemas import (
    ActivityROIPredictionPoint,
    ActivityROIRequest,
    ActivityROIResponse,
    ActivityType,
    InsufficientHistoricalDataError,
)

__all__ = [
    "ActivityROIPredictionPoint",
    "ActivityROIRequest",
    "ActivityROIResponse",
    "ActivityType",
    "InsufficientHistoricalDataError",
]
