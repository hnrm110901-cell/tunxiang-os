---
name: pdf-reading
description: "PDF文件解析与数据提取技能。当用户要求读取PDF文件、从PDF中提取数据、解析PDF表格、分析PDF内容、将PDF转换为结构化数据时触发。支持文本提取、表格识别、图片提取、多页处理。关键词：读取PDF、解析PDF、PDF提取、PDF转换、PDF分析。"
---

# PDF 文件解析与数据提取技能

## 概述

从 PDF 文件中提取文本、表格、元数据等结构化信息。
适用场景：分析竞品文档、提取合同条款、解析供应商报价单、导入历史报表数据。

## 第一步：识别提取需求

| 需求 | 方法 | 库 |
|------|------|-----|
| **纯文本提取** | 逐页提取文本 | `pymupdf` (fitz) |
| **表格提取** | 识别表格结构→DataFrame | `pymupdf` + `pandas` |
| **元数据** | 标题/作者/日期 | `pymupdf` |
| **图片提取** | 提取嵌入图片 | `pymupdf` |
| **扫描件OCR** | OCR识别文字 | `pymupdf` + `pytesseract`（需额外安装） |

## 第二步：选择工具链

### 优先使用 pymupdf（速度快，功能全）
```python
import fitz  # pymupdf

def extract_text(pdf_path: str) -> list[dict]:
    """提取所有页面的文本"""
    doc = fitz.open(pdf_path)
    pages = []
    for page_num, page in enumerate(doc):
        pages.append({
            'page': page_num + 1,
            'text': page.get_text('text'),
            'blocks': page.get_text('dict')['blocks']  # 结构化块
        })
    doc.close()
    return pages

def extract_tables(pdf_path: str) -> list[list[list[str]]]:
    """提取表格数据"""
    doc = fitz.open(pdf_path)
    all_tables = []
    for page in doc:
        tables = page.find_tables()
        for table in tables:
            all_tables.append(table.extract())
    doc.close()
    return all_tables
```

### 备选：Claude Read 工具
对于简单 PDF，直接使用 Claude Code 的 Read 工具读取：
```
Read(file_path="path/to/file.pdf", pages="1-5")
```
适用于快速浏览内容，不适合精确数据提取。

## 第三步：数据清洗

提取后的数据通常需要清洗：
```python
def clean_extracted_text(text: str) -> str:
    """清洗PDF提取的文本"""
    import re
    # 合并被分割的行
    text = re.sub(r'(?<=[^\n])\n(?=[^\n])', ' ', text)
    # 移除多余空格
    text = re.sub(r' +', ' ', text)
    # 移除页眉页脚（按模式识别）
    text = re.sub(r'第\s*\d+\s*页.*?\n', '', text)
    return text.strip()

def table_to_dataframe(table_data: list[list[str]]):
    """表格数据转DataFrame"""
    import pandas as pd
    if not table_data or len(table_data) < 2:
        return pd.DataFrame()
    headers = [str(h).strip() for h in table_data[0]]
    rows = [[str(c).strip() for c in row] for row in table_data[1:]]
    return pd.DataFrame(rows, columns=headers)
```

## 核心铁律

1. **优先用 pymupdf** — 速度比 pdfplumber/tabula 快 10x
2. **大文件逐页处理** — 不一次性加载全部页面到内存
3. **表格提取后必须验证** — 检查行列数是否合理
4. **编码处理** — 中文 PDF 注意编码，乱码时尝试不同提取模式
5. **扫描件单独处理** — 纯图片PDF需要OCR，先检测是否有文本层

## 设计审查清单

- [ ] pymupdf (PyMuPDF) 已安装？
- [ ] 文件路径验证存在？
- [ ] 大文件逐页处理？
- [ ] 表格数据有验证？
- [ ] 中文内容不乱码？
