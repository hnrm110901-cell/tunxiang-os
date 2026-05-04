#!/usr/bin/env python3
"""
train_dish_classifier.py — 菜品图像分类模型训练管线

基于 ResNet-18 微调，将菜品照片分类为中文菜名。
导出为 CoreML .mlpackage 供 edge/coreml-bridge (Swift, port 8100) 的 /vision/recognize 端点加载。

训练数据要求：
  目录结构: data/dish_images/
              ├── 宫保鸡丁/
              │     ├── img001.jpg
              │     └── img002.jpg
              ├── 红烧肉/
              │     └── ...
              └── ...

或 CSV 标注文件：
  image_path,dish_name
  /path/to/img001.jpg,宫保鸡丁
  /path/to/img002.jpg,红烧肉

模型架构：
  torchvision.models.resnet18(pretrained=True)
  → 替换最后一层 FC 为 num_classes
  → 训练 10 epochs
  → 导出 CoreML via coremltools

用法 (真实数据):
  python train_dish_classifier.py \
    --data-dir ./data/dish_images \
    --output ./models/dish_classifier_v1.mlpackage

用法 (合成占位 — 无真实图片时验证管线):
  python train_dish_classifier.py \
    --synthetic \
    --output ./models/dish_classifier_v1.mlpackage
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── 1. 菜品标签定义 ──────────────────────────────────────────────────────────

# 屯象OS 常见菜品标签（训练时使用此字典做 label→index 映射）
COMMON_DISHES: dict[str, int] = {
    "红烧肉": 0,
    "宫保鸡丁": 1,
    "麻婆豆腐": 2,
    "鱼香肉丝": 3,
    "糖醋排骨": 4,
    "回锅肉": 5,
    "水煮鱼": 6,
    "剁椒鱼头": 7,
    "小炒黄牛肉": 8,
    "辣椒炒肉": 9,
    "蒜蓉西兰花": 10,
    "清蒸鲈鱼": 11,
    "东坡肘子": 12,
    "毛氏红烧肉": 13,
    "口味虾": 14,
    "酸菜鱼": 15,
    "干锅花菜": 16,
    "农家小炒肉": 17,
    "蛋炒饭": 18,
    "酸辣土豆丝": 19,
    "番茄炒蛋": 20,
    "可乐鸡翅": 21,
    "烤鱼": 22,
    "水煮肉片": 23,
    "京酱肉丝": 24,
    "啤酒鸭": 25,
    "铁板牛肉": 26,
    "松鼠桂鱼": 27,
    "蒜香排骨": 28,
    "香辣蟹": 29,
}

IDX_TO_DISH: dict[int, str] = {v: k for k, v in COMMON_DISHES.items()}
NUM_CLASSES = len(COMMON_DISHES)


# ─── 2. 数据加载 ──────────────────────────────────────────────────────────────

def discover_from_directory(data_dir: str) -> list[tuple[str, str]]:
    """从目录结构发现图片和标签。

    返回 [(image_path, dish_name), ...]
    """
    samples: list[tuple[str, str]] = []
    data_path = Path(data_dir)

    if not data_path.exists():
        print(f"[train_dish_classifier] data directory not found: {data_dir}")
        return samples

    for dish_dir in sorted(data_path.iterdir()):
        if not dish_dir.is_dir():
            continue
        dish_name = dish_dir.name
        if dish_name not in COMMON_DISHES:
            print(f"[train_dish_classifier] WARNING: unknown dish '{dish_name}', skipping")
            continue
        for img_file in dish_dir.iterdir():
            if img_file.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                samples.append((str(img_file), dish_name))

    print(f"[train_dish_classifier] discovered {len(samples)} images across {len(set(d for _, d in samples))} dishes in {data_dir}")
    return samples


def discover_from_csv(csv_path: str) -> list[tuple[str, str]]:
    """从 CSV 标注文件加载图片路径和标签。

    CSV 列: image_path, dish_name
    """
    samples: list[tuple[str, str]] = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_path = row.get("image_path", "").strip()
            dish_name = row.get("dish_name", "").strip()
            if img_path and dish_name and dish_name in COMMON_DISHES:
                samples.append((img_path, dish_name))
    print(f"[train_dish_classifier] loaded {len(samples)} samples from {csv_path}")
    return samples


# ─── 3. 模型定义 ──────────────────────────────────────────────────────────────

def build_model(num_classes: int = NUM_CLASSES, freeze_backbone: bool = True):
    """构建 ResNet-18 分类模型。

    Args:
        num_classes: 输出类别数
        freeze_backbone: 是否冻结 backbone（仅训练最后一层，适合少量数据）
    """
    import torch
    import torch.nn as nn
    import torchvision.models as models

    model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)

    if freeze_backbone:
        for param in model.parameters():
            param.requires_grad = False

    # 替换分类头
    in_features = model.fc.in_features
    model.fc = nn.Sequential(
        nn.Dropout(0.3),
        nn.Linear(in_features, 256),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(256, num_classes),
    )

    return model


# ─── 4. 训练 ──────────────────────────────────────────────────────────────────

def train_model(
    model,
    train_loader,
    val_loader,
    epochs: int = 10,
    lr: float = 1e-3,
    device: str = "cpu",
) -> dict:
    """训练分类模型。返回训练统计信息。"""
    import torch
    import torch.nn as nn

    model = model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    stats: dict = {"train_loss": [], "val_acc": [], "epochs": epochs}

    for epoch in range(epochs):
        # 训练
        model.train()
        total_loss = 0.0
        batches = 0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            batches += 1

        avg_loss = total_loss / max(batches, 1)
        stats["train_loss"].append(avg_loss)

        # 验证
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                outputs = model(images)
                _, predicted = torch.max(outputs, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()

        val_acc = correct / max(total, 1)
        stats["val_acc"].append(val_acc)
        scheduler.step()

        print(f"[train_dish_classifier] epoch {epoch + 1}/{epochs}  loss={avg_loss:.4f}  val_acc={val_acc:.3f}")

    return stats


# ─── 5. 合成数据（管道验证）──────────────────────────────────────────────────

def create_synthetic_dataloaders(
    num_samples: int = 300,
    batch_size: int = 16,
    img_size: int = 224,
) -> tuple:
    """用随机张量创建合成 DataLoader，验证训练管道可运行。

    每个类别 ~10 张随机图。
    """
    import torch
    from torch.utils.data import DataLoader, TensorDataset

    samples_per_class = max(1, num_samples // NUM_CLASSES)
    images_list: list = []
    labels_list: list = []

    for label_idx in range(NUM_CLASSES):
        for _ in range(samples_per_class):
            img = torch.randn(3, img_size, img_size)  # 随机噪声
            images_list.append(img)
            labels_list.append(label_idx)

    images = torch.stack(images_list)
    labels = torch.tensor(labels_list, dtype=torch.long)

    # 简单拆分 train/val
    n = len(images)
    perm = torch.randperm(n)
    split = int(n * 0.8)

    train_dataset = TensorDataset(images[perm[:split]], labels[perm[:split]])
    val_dataset = TensorDataset(images[perm[split:]], labels[perm[split:]])

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    print(f"[train_dish_classifier] synthetic: {len(train_dataset)} train + {len(val_dataset)} val ({NUM_CLASSES} classes)")
    return train_loader, val_loader


def create_real_dataloaders(
    samples: list[tuple[str, str]],
    batch_size: int = 16,
    img_size: int = 224,
) -> tuple:
    """从真实图片路径创建 DataLoader。"""
    import torch
    from PIL import Image
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms

    class DishImageDataset(Dataset):
        def __init__(self, samples, transform, idx_to_label):
            self.samples = samples
            self.transform = transform
            self.idx_to_label = idx_to_label

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, idx):
            img_path, dish_name = self.samples[idx]
            image = Image.open(img_path).convert("RGB")
            image = self.transform(image)
            label = COMMON_DISHES[dish_name]
            return image, label

    transform = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    # 按 80/20 split
    rng = random.Random(42)
    shuffled = list(samples)
    rng.shuffle(shuffled)
    split = int(len(shuffled) * 0.8)

    train_dataset = DishImageDataset(shuffled[:split], transform, COMMON_DISHES)
    val_dataset = DishImageDataset(shuffled[split:], transform, COMMON_DISHES)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=2)

    return train_loader, val_loader


# ─── 6. 导出 CoreML ────────────────────────────────────────────────────────────

def export_to_coreml(model, output_path: str, img_size: int = 224) -> None:
    """将 PyTorch 模型导出为 CoreML .mlpackage。

    使用 coremltools 的 torch 转换器。
    """
    import torch

    try:
        import coremltools as ct
    except ImportError:
        print("[train_dish_classifier] coremltools not installed, falling back to TorchScript + JSON metadata")
        export_torchscript(model, output_path, img_size)
        return

    model.eval()
    model.cpu()

    # Trace the model
    example_input = torch.rand(1, 3, img_size, img_size)
    traced = torch.jit.trace(model, example_input)

    # Convert to CoreML
    coreml_model = ct.convert(
        traced,
        inputs=[ct.ImageType(name="image", shape=(1, 3, img_size, img_size), scale=1 / 255.0)],
        classifier_config=ct.ClassifierConfig(list(COMMON_DISHES.keys())),
    )

    coreml_model.short_description = "TunxiangOS Dish Image Classifier — recognizes Chinese dishes from photos"
    coreml_model.version = "1.0.0"
    coreml_model.author = "TunxiangOS CoreML Bridge"
    coreml_model.license = "Proprietary"

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    coreml_model.save(output_path)
    print(f"[train_dish_classifier] CoreML model exported: {output_path}")


def export_torchscript(model, output_path: str, img_size: int = 224) -> None:
    """兜底：导出 TorchScript + JSON 元数据。

    当 coremltools 不可用时使用。
    """
    import torch

    model.eval()
    model.cpu()

    example_input = torch.rand(1, 3, img_size, img_size)
    traced = torch.jit.trace(model, example_input)

    # 保存 TorchScript
    ts_path = output_path.replace(".mlpackage", ".pt")
    os.makedirs(os.path.dirname(ts_path) if os.path.dirname(ts_path) else ".", exist_ok=True)
    traced.save(ts_path)
    print(f"[train_dish_classifier] TorchScript exported: {ts_path}")

    # 保存标签映射
    meta_path = output_path.replace(".mlpackage", "_labels.json")
    meta = {
        "model_type": "resnet18_torchscript",
        "input_size": [3, img_size, img_size],
        "num_classes": NUM_CLASSES,
        "labels": COMMON_DISHES,
        "idx_to_label": IDX_TO_DISH,
        "exported_at": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[train_dish_classifier] labels metadata exported: {meta_path}")


# ─── 7. CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train dish image classifier")
    parser.add_argument("--data-dir", type=str, default="", help="Directory of dish images organized by class name")
    parser.add_argument("--csv", type=str, default="", help="CSV file with image_path, dish_name columns")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic random data (pipeline validation)")
    parser.add_argument("--output", type=str, default="models/dish_classifier_v1.mlpackage", help="Output .mlpackage path")
    parser.add_argument("--epochs", type=int, default=10, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--img-size", type=int, default=224, help="Input image size")
    parser.add_argument("--freeze-backbone", action="store_true", default=True, help="Freeze ResNet backbone (default: True)")
    parser.add_argument("--unfreeze-backbone", dest="freeze_backbone", action="store_false", help="Fine-tune full network")
    parser.add_argument("--format", type=str, choices=["coreml", "torchscript"], default="coreml", help="Export format")
    args = parser.parse_args()

    # 检查依赖
    try:
        import torch
        import torchvision  # noqa: F401
    except ImportError:
        print("[train_dish_classifier] ERROR: PyTorch and torchvision required. Install: pip install torch torchvision")
        sys.exit(1)

    # 数据加载
    if args.synthetic:
        print("[train_dish_classifier] using synthetic data for pipeline validation")
        train_loader, val_loader = create_synthetic_dataloaders(
            batch_size=args.batch_size, img_size=args.img_size
        )
    elif args.data_dir:
        samples = discover_from_directory(args.data_dir)
        if not samples:
            print("[train_dish_classifier] ERROR: no images found, use --synthetic for pipeline test")
            sys.exit(1)
        train_loader, val_loader = create_real_dataloaders(samples, batch_size=args.batch_size, img_size=args.img_size)
    elif args.csv:
        samples = discover_from_csv(args.csv)
        if not samples:
            print("[train_dish_classifier] ERROR: no samples in CSV, use --synthetic for pipeline test")
            sys.exit(1)
        train_loader, val_loader = create_real_dataloaders(samples, batch_size=args.batch_size, img_size=args.img_size)
    else:
        print("[train_dish_classifier] no data source specified, falling back to --synthetic")
        train_loader, val_loader = create_synthetic_dataloaders(
            batch_size=args.batch_size, img_size=args.img_size
        )

    # 设备
    device = "cuda" if __import__("torch").cuda.is_available() else "cpu"
    print(f"[train_dish_classifier] using device: {device}")

    # 构建模型
    model = build_model(num_classes=NUM_CLASSES, freeze_backbone=args.freeze_backbone)
    print(f"[train_dish_classifier] model: ResNet-18, {NUM_CLASSES} classes, backbone {'frozen' if args.freeze_backbone else 'trainable'}")

    # 训练
    stats = train_model(
        model, train_loader, val_loader,
        epochs=args.epochs, lr=args.lr, device=device,
    )

    final_acc = stats["val_acc"][-1] if stats["val_acc"] else 0.0
    print(f"[train_dish_classifier] final val_acc={final_acc:.3f}")

    # 导出
    if args.format == "torchscript":
        export_torchscript(model, args.output, args.img_size)
    else:
        export_to_coreml(model, args.output, args.img_size)

    print("[train_dish_classifier] done.")


if __name__ == "__main__":
    main()
