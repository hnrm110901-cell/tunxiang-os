---
name: file-reading
description: "多格式文件解析技能。当用户要求读取、解析、导入CSV、JSON、XML、YAML、Excel(.xls/.xlsx)、图片、音频等非标准文本文件时触发。也适用于：数据迁移、旧系统数据导入、批量文件处理、格式转换。关键词：读取文件、解析文件、导入数据、CSV、JSON、XML、数据迁移、格式转换、批量处理。"
---

# 多格式文件解析技能

## 概述

处理各种格式的文件读取、解析和数据提取。
核心场景：旧系统数据迁移（品智POS/微生活/G10/金蝶/润典）、供应商数据导入、批量文件处理。

## 第一步：识别文件格式

| 格式 | 库 | 适用场景 |
|------|-----|---------|
| **CSV/TSV** | `pandas` / `csv` | 数据导出/导入，最常见 |
| **Excel (.xlsx)** | `openpyxl` / `pandas` | 供应商报价、财务数据 |
| **Excel (.xls)** | `xlrd` + `pandas` | 旧系统导出（品智/金蝶） |
| **JSON** | `json` / `orjson` | API数据、配置文件 |
| **XML** | `lxml` / `xml.etree` | 税控数据、银联对账 |
| **YAML** | `pyyaml` | 配置文件 |
| **SQLite** | `sqlite3` + `pandas` | 旧系统本地数据库 |
| **图片** | `Pillow` | 菜品图片、证照扫描 |
| **ZIP/RAR** | `zipfile` / `rarfile` | 批量文件包 |

## 第二步：选择处理策略

### 小文件（< 100MB）
直接加载到内存：
```python
import pandas as pd

# CSV
df = pd.read_csv(path, encoding='utf-8-sig')  # utf-8-sig处理BOM

# Excel
df = pd.read_excel(path, sheet_name=0, engine='openpyxl')

# JSON
df = pd.read_json(path, orient='records')
```

### 大文件（> 100MB）
分块读取：
```python
# CSV 分块
for chunk in pd.read_csv(path, chunksize=10000, encoding='utf-8-sig'):
    process(chunk)

# Excel 分块（openpyxl read_only模式）
from openpyxl import load_workbook
wb = load_workbook(path, read_only=True)
ws = wb.active
for row in ws.iter_rows(min_row=2, values_only=True):
    process(row)
wb.close()

# JSON Lines（大JSON文件）
import json
with open(path, 'r', encoding='utf-8') as f:
    for line in f:
        record = json.loads(line)
        process(record)
```

### 编码检测
```python
def detect_encoding(file_path: str) -> str:
    """检测文件编码"""
    import chardet
    with open(file_path, 'rb') as f:
        raw = f.read(10000)  # 读前10KB
    result = chardet.detect(raw)
    return result['encoding'] or 'utf-8'
```

## 第三步：数据验证

读取后必须验证：
```python
def validate_dataframe(df: pd.DataFrame, expected_columns: list[str]) -> dict:
    """验证DataFrame数据质量"""
    report = {
        'total_rows': len(df),
        'columns_found': list(df.columns),
        'missing_columns': [c for c in expected_columns if c not in df.columns],
        'null_counts': df.isnull().sum().to_dict(),
        'duplicate_rows': df.duplicated().sum(),
        'sample': df.head(3).to_dict('records')
    }
    return report
```

## 旧系统数据迁移映射

### 品智POS数据格式
```python
PINZHI_COLUMN_MAP = {
    '订单号': 'order_no',
    '桌台': 'table_name',
    '菜品名称': 'dish_name',
    '数量': 'quantity',
    '金额': 'amount_yuan',
    '折扣': 'discount_rate',
    '下单时间': 'created_at',
    '操作员': 'operator_name',
}
```

### 金蝶财务数据格式
```python
KINGDEE_COLUMN_MAP = {
    '凭证日期': 'voucher_date',
    '摘要': 'summary',
    '科目编码': 'account_code',
    '科目名称': 'account_name',
    '借方金额': 'debit_amount',
    '贷方金额': 'credit_amount',
}
```

## 核心铁律

1. **编码优先检测** — 中文文件常见 GBK/GB2312/UTF-8-BOM，不要默认 UTF-8
2. **大文件分块读** — 超过 100MB 必须分块，避免内存溢出
3. **读后必验证** — 检查列名、空值、重复行、数据类型
4. **旧系统字段映射** — 使用预定义的字段映射表，不硬编码在处理逻辑中
5. **保留原始文件** — 处理后的数据另存，不覆盖原文件

## 设计审查清单

- [ ] 文件存在性检查？
- [ ] 编码检测/指定？
- [ ] 大文件分块处理？
- [ ] 读取后有数据验证？
- [ ] 字段映射使用常量表？
- [ ] 原始文件未被修改？
