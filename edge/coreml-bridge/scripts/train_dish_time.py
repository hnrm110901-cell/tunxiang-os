#!/usr/bin/env python3
"""
train_dish_time.py — 出餐时间预测模型训练管线

训练一个GBDT回归模型，预测菜品出餐时间（秒），并导出为 CoreML .mlpackage 供
edge/coreml-bridge (Swift, port 8100) 加载推理。

特性工程 (5维)：
  dish_category   — 菜品大类（cold/stir-fry/stew/soup/noodle/rice）
  order_hour      — 下单时段 0-23
  queue_depth     — 当前后厨队列深度（同时待出餐数）
  party_size      — 桌台用餐人数
  prep_complexity — 制作复杂度 1-5

目标变量：prep_seconds (出餐秒数)

模型选择：
  优先 coremltools + xgboost → .mlpackage
  降级 coremltools + sklearn.ensemble.GradientBoostingRegressor → .mlpackage
  兜底 JSON (model_params.json) 供 Python fallback 直接加载

用法：
  python train_dish_time.py \
    --data ./synthetic_dish_times.csv \
    --output ./models/dish_time_v1.mlpackage
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── 1. 合成数据生成 ──────────────────────────────────────────────────────────

CATEGORY_BASE = {
    "cold": 180.0,     # 凉菜：约3分钟
    "stir-fry": 360.0,  # 小炒：约6分钟
    "stew": 900.0,      # 炖菜：约15分钟
    "soup": 540.0,      # 汤类：约9分钟
    "noodle": 300.0,    # 面食：约5分钟
    "rice": 240.0,      # 米饭：约4分钟
}

CATEGORY_COMPLEXITY = {
    "cold": (1, 2),
    "stir-fry": (2, 4),
    "stew": (3, 5),
    "soup": (2, 4),
    "noodle": (1, 3),
    "rice": (1, 2),
}

# 午市 11-13, 晚市 17-20 为高峰期
PEAK_HOURS: set[int] = {11, 12, 13, 17, 18, 19, 20}


def generate_synthetic_data(
    num_samples: int = 5000,
    seed: int = 42,
) -> list[dict]:
    """生成合成训练数据。

    模拟真实餐厅场景：
    - 工作日/周末分布
    - 午市/晚市高峰
    - 队列压力随小时变化 (11:30-13:00, 18:00-20:00 最高)
    - 出餐时间 = 基础时间 * 复杂度系数 + 队列惩罚 + 时段加成 + 噪声
    """
    rng = random.Random(seed)
    categories = list(CATEGORY_BASE.keys())

    rows: list[dict] = []
    for _ in range(num_samples):
        cat = rng.choice(categories)
        hour = rng.randint(6, 22)  # 营业时间 6:00-22:00
        day_type = rng.choices(["weekday", "weekend"], weights=[5, 2], k=1)[0]

        # 队列深度：高峰期最大，其他时段递减
        if hour in PEAK_HOURS:
            queue_depth = rng.randint(2, 20)
        else:
            queue_depth = rng.randint(0, 8)

        party_size = rng.choices([1, 2, 3, 4, 5, 6, 8, 10, 12], weights=[5, 20, 15, 25, 10, 10, 5, 5, 5], k=1)[0]
        # 每道菜为该人数制作，但一批可能做多人份 → 复杂度受 party_size 影响
        comp_min, comp_max = CATEGORY_COMPLEXITY[cat]
        prep_complexity = rng.randint(comp_min, comp_max)

        # ── 真实出餐时间模型 ──
        base = CATEGORY_BASE[cat]
        complexity_mult = 0.5 + prep_complexity * 0.3  # 复杂度1→0.8x, 5→2.0x
        queue_penalty = queue_depth * rng.uniform(10, 25)  # 每单队列加10-25秒
        peak_penalty = rng.uniform(30, 90) if hour in PEAK_HOURS else 0.0
        party_penalty = max(0, (party_size - 2)) * rng.uniform(10, 30)  # 多人加时
        weekend_penalty = rng.uniform(10, 40) if day_type == "weekend" else 0.0
        # 厨房随机波动：高峰期波动大
        noise_std = 60 if hour in PEAK_HOURS else 30
        noise = rng.gauss(0, noise_std)

        prep_seconds = max(60.0, base * complexity_mult + queue_penalty + peak_penalty + party_penalty + weekend_penalty + noise)

        rows.append({
            "dish_category": cat,
            "order_hour": hour,
            "queue_depth": queue_depth,
            "party_size": party_size,
            "prep_complexity": prep_complexity,
            "day_type": day_type,
            "prep_seconds": round(prep_seconds, 1),
        })

    return rows


def save_csv(rows: list[dict], path: str) -> None:
    fieldnames = ["dish_category", "order_hour", "queue_depth", "party_size", "prep_complexity", "day_type", "prep_seconds"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[train_dish_time] synthetic data saved: {path} ({len(rows)} rows)")


# ─── 2. 特征工程 ──────────────────────────────────────────────────────────────

def encode_features(rows: list[dict]) -> tuple[list, list[float]]:
    """将类别特征编码为 one-hot 向量，数值特征标准化。

    返回 (X: list[list[float]], y: list[float])
    """
    import numpy as np

    cat_to_idx = {cat: i for i, cat in enumerate(CATEGORY_BASE.keys())}
    n_cats = len(cat_to_idx)

    X: list[list[float]] = []
    y: list[float] = []

    for r in rows:
        feat: list[float] = []

        # dish_category → one-hot
        one_hot = [0.0] * n_cats
        one_hot[cat_to_idx[r["dish_category"]]] = 1.0
        feat.extend(one_hot)

        # order_hour → sin/cos 循环编码（保留小时循环语义）
        hour_rad = 2 * math.pi * r["order_hour"] / 24.0
        feat.append(math.sin(hour_rad))
        feat.append(math.cos(hour_rad))

        # day_type → 0/1
        feat.append(1.0 if r["day_type"] == "weekend" else 0.0)

        # 数值特征（标准化）
        feat.append(r["queue_depth"] / 20.0)          # [0,1]
        feat.append(r["party_size"] / 12.0)           # [0,1]
        feat.append(r["prep_complexity"] / 5.0)       # [0,1]

        X.append(feat)
        y.append(r["prep_seconds"])

    return X, y


# ─── 3. 训练 ──────────────────────────────────────────────────────────────────

def train_xgboost(X, y) -> tuple:
    """用 XGBoost 训练回归模型，返回 (model, feature_names)"""
    import numpy as np

    try:
        import xgboost as xgb
    except ImportError:
        print("[train_dish_time] xgboost not installed, falling back to sklearn GBR")
        return train_sklearn(X, y)

    X_np = np.array(X, dtype=np.float32)
    y_np = np.array(y, dtype=np.float32)

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_np, y_np)

    feature_names = [
        "cat_cold", "cat_stir_fry", "cat_stew", "cat_soup", "cat_noodle", "cat_rice",
        "hour_sin", "hour_cos",
        "is_weekend",
        "queue_depth_norm",
        "party_size_norm",
        "complexity_norm",
    ]

    # 评估
    preds = model.predict(X_np)
    mae = float(np.mean(np.abs(preds - y_np)))
    rmse = float(np.sqrt(np.mean((preds - y_np) ** 2)))
    print(f"[train_dish_time] XGBoost MAE={mae:.1f}s RMSE={rmse:.1f}s")

    return model, feature_names


def train_sklearn(X, y) -> tuple:
    """用 sklearn GradientBoostingRegressor 训练（兜底）"""
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor

    X_np = np.array(X, dtype=np.float64)
    y_np = np.array(y, dtype=np.float64)

    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )
    model.fit(X_np, y_np)

    feature_names = [
        "cat_cold", "cat_stir_fry", "cat_stew", "cat_soup", "cat_noodle", "cat_rice",
        "hour_sin", "hour_cos",
        "is_weekend",
        "queue_depth_norm",
        "party_size_norm",
        "complexity_norm",
    ]

    preds = model.predict(X_np)
    mae = float(np.mean(np.abs(preds - y_np)))
    rmse = float(np.sqrt(np.mean((preds - y_np) ** 2)))
    print(f"[train_dish_time] sklearn GBR MAE={mae:.1f}s RMSE={rmse:.1f}s")

    return model, feature_names


# ─── 4. 导出 ──────────────────────────────────────────────────────────────────

def export_coreml_sklearn(model, feature_names: list[str], output_path: str) -> None:
    """用 coremltools 将 sklearn model 导出为 .mlpackage"""
    try:
        import coremltools as ct
    except ImportError:
        print("[train_dish_time] coremltools not installed, falling back to JSON export")
        export_json(model, feature_names, output_path)
        return

    # 将 sklearn model 转为 coreml
    coreml_model = ct.converters.sklearn.convert(
        model,
        feature_names=feature_names,
        target="prep_seconds",
    )

    # 设置元数据
    coreml_model.short_description = "TunxiangOS Dish Time Predictor — predicts prep_seconds from dish features"
    coreml_model.version = "1.0.0"
    coreml_model.author = "TunxiangOS CoreML Bridge"
    coreml_model.license = "Proprietary"

    # 保存
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    coreml_model.save(output_path)
    print(f"[train_dish_time] CoreML model exported: {output_path}")


def export_json(model, feature_names: list[str], output_path: str) -> None:
    """导出一个 JSON 描述文件，供 Python fallback 加载。

    当 coremltools 不可用时，将模型参数序列化为 JSON，
    由 edge/coreml-bridge 的 dish_time_predictor.py 加载推理。
    """
    import numpy as np

    json_path = output_path.replace(".mlpackage", ".json")

    if hasattr(model, "get_booster"):
        # XGBoost
        booster = model.get_booster()
        model_dump = booster.save_raw().decode("utf-8") if isinstance(booster.save_raw(), bytes) else str(booster.save_raw())
        export_data = {
            "model_type": "xgboost",
            "feature_names": feature_names,
            "n_features": len(feature_names),
            "model_params": model.get_params(),
            "booster_raw": model_dump,
            "exported_at": datetime.utcnow().isoformat(),
            "version": "1.0.0",
        }
    else:
        # sklearn
        coef = model._raw_predict if hasattr(model, "_raw_predict") else None
        export_data = {
            "model_type": "sklearn.GradientBoostingRegressor",
            "feature_names": feature_names,
            "n_features": len(feature_names),
            "n_estimators": model.n_estimators,
            "max_depth": model.max_depth,
            "learning_rate": model.learning_rate,
            "train_score": float(model.train_score_[-1]) if hasattr(model, "train_score_") and len(model.train_score_) > 0 else None,
            "exported_at": datetime.utcnow().isoformat(),
            "version": "1.0.0",
        }

    os.makedirs(os.path.dirname(json_path) if os.path.dirname(json_path) else ".", exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(export_data, f, indent=2, default=str)
    print(f"[train_dish_time] JSON fallback exported: {json_path}")


# ─── 5. CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train dish time prediction model")
    parser.add_argument("--data", type=str, default="", help="Path to CSV training data (generated if omitted)")
    parser.add_argument("--output", type=str, default="models/dish_time_v1.mlpackage", help="Output .mlpackage path")
    parser.add_argument("--samples", type=int, default=5000, help="Number of synthetic samples to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--format", type=str, choices=["coreml", "json"], default="coreml", help="Export format")
    args = parser.parse_args()

    # 加载或生成数据
    if args.data and os.path.exists(args.data):
        print(f"[train_dish_time] loading data from {args.data}")
        with open(args.data, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # 转换数值字段
        for r in rows:
            r["order_hour"] = int(r["order_hour"])
            r["queue_depth"] = int(r["queue_depth"])
            r["party_size"] = int(r["party_size"])
            r["prep_complexity"] = int(r["prep_complexity"])
            r["prep_seconds"] = float(r["prep_seconds"])
    else:
        rows = generate_synthetic_data(num_samples=args.samples, seed=args.seed)
        csv_path = args.data or "synthetic_dish_times.csv"
        save_csv(rows, csv_path)

    if not rows:
        print("[train_dish_time] ERROR: no training data")
        sys.exit(1)

    print(f"[train_dish_time] training on {len(rows)} samples")

    # 特征编码
    X, y = encode_features(rows)

    # 训练
    model, feature_names = train_xgboost(X, y)

    # 导出
    if args.format == "json":
        export_json(model, feature_names, args.output)
    else:
        export_coreml_sklearn(model, feature_names, args.output)

    print("[train_dish_time] done.")


if __name__ == "__main__":
    main()
