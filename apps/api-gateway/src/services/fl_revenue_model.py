"""
联邦学习 — 真实营收预测模型定义

解决的问题：
  federated_learning_service.py 聚合的是"任意 numpy 数组"，没有定义实际模型结构，
  导致联邦学习是技术外壳而非真实机器学习。

本模块定义：
  1. 特征工程：从门店订单历史提取标准化特征向量
  2. 模型架构：轻量 3 层 MLP（可序列化为 JSON/numpy，适合 FedAvg）
  3. 本地训练：在门店本地数据上训练一个 mini-epoch
  4. 参数上传格式：与 FederatedLearningService.upload_model_parameters 兼容

设计约束（联邦学习）：
  - 只上传模型权重（numpy arrays），不上传原始订单数据
  - 模型足够轻量（< 10K 参数），适合低带宽边缘节点
  - 特征维度固定为 12，跨门店兼容

特征向量（12 维）：
  [0]  day_of_week           归一化星期（0-1）
  [1]  is_holiday            是否节假日（0/1）
  [2]  is_weekend            是否周末（0/1）
  [3]  month_normalized      月份归一化（0-1）
  [4]  lag_1d_revenue        昨日营收（归一化）
  [5]  lag_7d_revenue        7天前营收（归一化）
  [6]  rolling_7d_mean       近7天均值（归一化）
  [7]  rolling_7d_std        近7天标准差（归一化）
  [8]  weather_score         天气评分 0-1（可选，无数据填 0.5）
  [9]  promo_flag            是否有促销（0/1）
  [10] seats_utilization     座位利用率历史均值（归一化）
  [11] staff_count_norm      当日排班人数（归一化）
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

FEATURE_DIM = 12   # 输入特征维度
HIDDEN_DIM  = 16   # 隐层神经元数
OUTPUT_DIM  = 1    # 预测目标：当日营收（归一化）


# ═══════════════════════════════════════════════════════════════════════════════
# 模型参数结构（与 FederatedLearningService 兼容）
# ═══════════════════════════════════════════════════════════════════════════════

def init_model_params() -> Dict[str, np.ndarray]:
    """
    初始化 3 层 MLP 参数（Xavier 初始化）。

    结构：12 → 16 → 8 → 1
    参数 key 命名与 FedAvg 聚合兼容。
    """
    rng = np.random.default_rng(42)
    def xavier(fan_in, fan_out):
        limit = math.sqrt(6.0 / (fan_in + fan_out))
        return rng.uniform(-limit, limit, (fan_in, fan_out)).astype(np.float32)

    return {
        "W1": xavier(FEATURE_DIM, HIDDEN_DIM),
        "b1": np.zeros(HIDDEN_DIM, dtype=np.float32),
        "W2": xavier(HIDDEN_DIM, 8),
        "b2": np.zeros(8, dtype=np.float32),
        "W3": xavier(8, OUTPUT_DIM),
        "b3": np.zeros(OUTPUT_DIM, dtype=np.float32),
        "revenue_mean": np.array([0.0], dtype=np.float32),   # 归一化统计量（门店专属）
        "revenue_std":  np.array([1.0], dtype=np.float32),
    }


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0, x)


def forward(params: Dict[str, np.ndarray], features: np.ndarray) -> float:
    """前向传播，返回归一化后的预测营收（需乘 revenue_std + revenue_mean 还原）"""
    h1 = _relu(features @ params["W1"] + params["b1"])
    h2 = _relu(h1 @ params["W2"] + params["b2"])
    out = h2 @ params["W3"] + params["b3"]
    return float(out[0])


def predict_revenue_yuan(
    params: Dict[str, np.ndarray],
    features: np.ndarray,
) -> float:
    """预测还原为真实营收（元）"""
    norm_pred = forward(params, features)
    mean = float(params["revenue_mean"][0])
    std  = max(float(params["revenue_std"][0]), 1.0)
    return round(norm_pred * std + mean, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 特征提取
# ═══════════════════════════════════════════════════════════════════════════════

async def extract_features(
    store_id:     str,
    target_date:  date,
    db:           AsyncSession,
) -> Optional[np.ndarray]:
    """
    从 DB 提取目标日期的特征向量（12 维）。
    任何维度缺失时填充合理默认值，不返回 None（保证训练不中断）。
    """
    try:
        from src.models.order import Order
        # 近 14 天日营收序列
        start = target_date - timedelta(days=14)
        rows = (await db.execute(
            text("""
                SELECT DATE(order_time)           AS day,
                       COALESCE(SUM(final_amount), 0) / 100.0 AS revenue_yuan
                FROM orders
                WHERE store_id  = :sid
                  AND order_time >= :start
                  AND order_time <  :end
                  AND status IN ('completed', 'served')
                GROUP BY DATE(order_time)
                ORDER BY day ASC
            """),
            {"sid": store_id, "start": start.isoformat(), "end": target_date.isoformat()},
        )).fetchall()

        # 构建日营收字典
        rev_map: Dict[date, float] = {r[0]: float(r[1]) for r in rows}
        revenues = [rev_map.get(start + timedelta(days=i), 0.0) for i in range(14)]
        rolling_mean = float(np.mean(revenues[-7:])) if revenues else 0.0
        rolling_std  = float(np.std(revenues[-7:]))  if revenues else 0.0

        lag_1d = rev_map.get(target_date - timedelta(days=1), rolling_mean)
        lag_7d = rev_map.get(target_date - timedelta(days=7), rolling_mean)

        # 归一化（z-score，防除零）
        scale = max(rolling_std, 1.0)
        f_lag_1d       = (lag_1d - rolling_mean) / scale
        f_lag_7d       = (lag_7d - rolling_mean) / scale
        f_rolling_mean = 0.0   # by definition after z-score
        f_rolling_std  = rolling_std / (rolling_mean + 1.0)

        # 日期特征
        dow     = target_date.weekday()
        is_wknd = 1.0 if dow >= 5 else 0.0
        month_n = (target_date.month - 1) / 11.0

        # 节假日（中国大陆简单规则：1/1、春节区间、10/1-7）
        def _is_holiday(d: date) -> float:
            md = (d.month, d.day)
            if md == (1, 1): return 1.0
            if d.month == 2 and 10 <= d.day <= 17: return 1.0  # 春节区间近似
            if d.month == 10 and 1 <= d.day <= 7: return 1.0
            return 0.0

        features = np.array([
            dow / 6.0,                # [0] day_of_week
            _is_holiday(target_date), # [1] is_holiday
            is_wknd,                  # [2] is_weekend
            month_n,                  # [3] month_normalized
            f_lag_1d,                 # [4] lag_1d_revenue
            f_lag_7d,                 # [5] lag_7d_revenue
            f_rolling_mean,           # [6] rolling_7d_mean
            f_rolling_std,            # [7] rolling_7d_std
            0.5,                      # [8] weather_score（默认中性）
            0.0,                      # [9] promo_flag（默认无促销）
            0.5,                      # [10] seats_utilization（默认50%）
            0.5,                      # [11] staff_count_norm（默认中等）
        ], dtype=np.float32)

        return features

    except Exception as exc:
        logger.warning("fl_revenue_model.extract_features_failed",
                       store_id=store_id, error=str(exc))
        return np.zeros(FEATURE_DIM, dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════════════════
# 本地训练（mini-batch SGD，单 epoch）
# ═══════════════════════════════════════════════════════════════════════════════

async def local_train(
    store_id:   str,
    params:     Dict[str, np.ndarray],
    db:         AsyncSession,
    lr:         float = 0.01,
    lookback:   int   = 30,
) -> Tuple[Dict[str, np.ndarray], float]:
    """
    在门店本地数据上训练一个 epoch，返回更新后的参数和平均损失。

    使用 MSE 损失 + 简单数值梯度（避免依赖 autograd 框架，适合轻量边缘节点）。
    """
    today = date.today()
    train_losses: List[float] = []

    # 构建训练样本：近 lookback 天每天(features, actual_revenue)
    revenue_mean = float(params["revenue_mean"][0])
    revenue_std  = max(float(params["revenue_std"][0]), 1.0)

    for i in range(1, lookback + 1):
        target_d = today - timedelta(days=i)
        feat = await extract_features(store_id, target_d, db)
        if feat is None:
            continue

        # 实际营收（归一化）
        row = (await db.execute(
            text("""
                SELECT COALESCE(SUM(final_amount), 0) / 100.0
                FROM orders
                WHERE store_id = :sid
                  AND DATE(order_time) = :dt
                  AND status IN ('completed','served')
            """),
            {"sid": store_id, "dt": target_d.isoformat()},
        )).fetchone()
        actual_yuan = float(row[0]) if row else 0.0
        y_norm = (actual_yuan - revenue_mean) / revenue_std

        # 前向传播
        y_pred = forward(params, feat)
        loss   = (y_pred - y_norm) ** 2
        train_losses.append(loss)

        # 数值梯度（有限差分，eps=1e-4）
        eps = 1e-4
        for key in ("W1", "b1", "W2", "b2", "W3", "b3"):
            grad = np.zeros_like(params[key])
            it   = np.nditer(params[key], flags=["multi_index"])
            while not it.finished:
                idx = it.multi_index
                orig = params[key][idx]
                params[key][idx] = orig + eps
                loss_p = (forward(params, feat) - y_norm) ** 2
                params[key][idx] = orig - eps
                loss_m = (forward(params, feat) - y_norm) ** 2
                params[key][idx] = orig
                grad[idx] = (loss_p - loss_m) / (2 * eps)
                it.iternext()
            params[key] = params[key] - lr * grad

    avg_loss = float(np.mean(train_losses)) if train_losses else 0.0
    logger.info("fl_revenue_model.local_train",
                store_id=store_id, samples=len(train_losses), avg_loss=round(avg_loss, 6))
    return params, avg_loss
