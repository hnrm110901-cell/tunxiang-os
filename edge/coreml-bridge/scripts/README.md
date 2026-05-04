# CoreML Bridge Training Scripts

Model training pipelines for TunxiangOS edge inference (Mac mini M4). Each script produces `.mlpackage` files consumed by `edge/coreml-bridge` (Swift, port 8100).

## Prerequisites

```bash
# Core (always required)
pip install numpy scikit-learn

# For CoreML export (recommended)
pip install coremltools

# For XGBoost (better accuracy on dish_time)
pip install xgboost

# For dish_classifier
pip install torch torchvision Pillow
```

## Scripts

### train_dish_time.py

Trains a GBDT regressor to predict dish preparation time (seconds).

**Features**: dish_category (cold/stir-fry/stew/soup/noodle/rice), order_hour (sin/cos encoding), queue_depth, party_size, prep_complexity (1-5), day_type (weekday/weekend).

**Target**: prep_seconds.

**Quick start** (synthetic data, pipeline validation):

```bash
python train_dish_time.py --samples 5000 --output ../models/dish_time_v1.mlpackage
```

**With real historical data**:

```bash
python train_dish_time.py --data ./historical_dish_times.csv --output ../models/dish_time_v2.mlpackage
```

**Fallback to JSON** (when coremltools unavailable):

```bash
python train_dish_time.py --samples 5000 --format json --output ../models/dish_time_v1.json
```

**CSV format** (when using `--data`):

```csv
dish_category,order_hour,queue_depth,party_size,prep_complexity,day_type,prep_seconds
stir-fry,12,8,4,3,weekday,420.5
stew,19,15,6,4,weekend,1080.0
```

### train_dish_classifier.py

Trains a ResNet-18 image classifier to recognize Chinese dishes from photos.

**Output classes**: 30 common Chinese dishes (see `COMMON_DISHES` dict in source).

**Quick start** (synthetic data, pipeline validation):

```bash
python train_dish_classifier.py --synthetic --output ../models/dish_classifier_v1.mlpackage
```

**With real labeled images** (directory structure):

```bash
python train_dish_classifier.py \
  --data-dir ./data/dish_images \
  --epochs 20 \
  --batch-size 32 \
  --output ../models/dish_classifier_v1.mlpackage
```

Expected directory structure:

```
data/dish_images/
  ├── 宫保鸡丁/
  │     ├── img001.jpg
  │     ├── img002.jpg
  │     └── ...
  ├── 红烧肉/
  │     └── ...
  └── ...
```

**With CSV annotations**:

```bash
python train_dish_classifier.py \
  --csv ./annotations.csv \
  --output ../models/dish_classifier_v1.mlpackage
```

CSV format:

```csv
image_path,dish_name
/path/to/img001.jpg,宫保鸡丁
/path/to/img002.jpg,红烧肉
```

**Fine-tune full network** (more data needed):

```bash
python train_dish_classifier.py --data-dir ./data/ --unfreeze-backbone --epochs 30
```

**Fallback to TorchScript** (when coremltools unavailable):

```bash
python train_dish_classifier.py --synthetic --format torchscript --output ../models/dish_classifier_v1.pt
```

## Output Files

| Script | Primary Output | Fallback Output | Consumer |
|--------|---------------|-----------------|----------|
| train_dish_time.py | `dish_time_v1.mlpackage` | `dish_time_v1.json` | `ModelManager.predictDishTime()` (Swift) |
| train_dish_classifier.py | `dish_classifier_v1.mlpackage` | `dish_classifier_v1.pt` + `_labels.json` | `/vision/recognize` (Swift) endpoint |

## Model Deployment

After training, deploy models to Mac mini using:

```bash
bash edge/mac-mini/scripts/deploy_models.sh
```

See that script for SCP + launchd registration + health check steps.

## Retraining Cadence

| Model | Recommended Cadence | Trigger |
|-------|-------------------|---------|
| dish_time | Monthly | New menu items, kitchen layout changes |
| dish_classifier | Quarterly | New dishes added to menu, significant photo quality changes |

## Notes

- Synthetic data is for pipeline validation only. Real models MUST be trained on actual restaurant data before production use.
- `coremltools` requires macOS. Train on a Mac or use the JSON/TorchScript fallback for cross-platform CI.
- The exported `.mlpackage` is loaded by the Swift `ModelManager` in `edge/coreml-bridge/Sources/`.
