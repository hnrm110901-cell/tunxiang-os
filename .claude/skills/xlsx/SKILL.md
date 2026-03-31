---
name: xlsx
description: "Excel电子表格(.xlsx)生成技能。当用户要求生成Excel表格、数据报表、财务报表、库存盘点表、排班表、菜品定价表、成本核算表、门店对比表、KPI看板数据、数据导出模板时触发。支持多Sheet、条件格式、数据验证、公式、图表、冻结窗格、打印设置等专业电子表格功能。关键词：xlsx、excel、表格、报表、数据导出、模板、排班、盘点、核算。"
---

# Excel 电子表格专业生成技能

## 概述

基于 `openpyxl` 库生成专业电子表格，内置餐饮行业常用模板。
支持多 Sheet、条件格式、数据验证、公式计算、图表嵌入、打印优化。

## 第一步：识别表格类型

| 类型 | 触发词 | 特征 |
|------|--------|------|
| **营业报表** | 营业额、日报、月报 | 时间序列+汇总行+图表 |
| **财务报表** | 利润、成本、P&L | 科目层级+公式+交叉验证 |
| **库存盘点** | 盘点、库存、进销存 | 分类汇总+差异列+预警色 |
| **排班表** | 排班、考勤、工时 | 日历格式+颜色区分班次 |
| **菜品定价** | 定价、毛利、BOM | 成本计算公式+毛利率列 |
| **门店对比** | 对比、排名、KPI | 多门店横向+排名+趋势 |
| **数据模板** | 模板、导入、格式 | 数据验证+下拉+说明Sheet |

## 第二步：读取参考

- `references/excel-patterns.md` — 电子表格设计模式和公式模板

## 第三步：设计表格结构

### 通用结构规范
```
Sheet1: 数据主表
  Row 1-2: 标题区（合并单元格，品牌色背景）
  Row 3: 筛选条件/参数区（浅灰背景）
  Row 4: 表头（深色背景，白字，冻结）
  Row 5-N: 数据区（交替行色，条件格式）
  Row N+1: 汇总行（加粗，公式）

Sheet2: 图表（如有需要）
Sheet3: 数据字典/说明
```

## 第四步：生成 Python 脚本

### 品牌样式（强制）
```python
from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Border, Side, Alignment,
    NamedStyle, numbers
)
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule

# 屯象品牌色
TX_PRIMARY_FILL = PatternFill('solid', fgColor='FF6B35')
TX_NAVY_FILL = PatternFill('solid', fgColor='1E2A3A')
TX_LIGHT_FILL = PatternFill('solid', fgColor='F8F9FA')
TX_WHITE_FILL = PatternFill('solid', fgColor='FFFFFF')
TX_WARNING_FILL = PatternFill('solid', fgColor='FFF3CD')
TX_DANGER_FILL = PatternFill('solid', fgColor='F8D7DA')
TX_SUCCESS_FILL = PatternFill('solid', fgColor='D4EDDA')

# 字体
FONT_TITLE = Font(name='微软雅黑', size=16, bold=True, color='1E2A3A')
FONT_HEADER = Font(name='微软雅黑', size=11, bold=True, color='FFFFFF')
FONT_BODY = Font(name='微软雅黑', size=10, color='333333')
FONT_TOTAL = Font(name='微软雅黑', size=11, bold=True, color='1E2A3A')
FONT_LINK = Font(name='微软雅黑', size=10, color='FF6B35', underline='single')

# 边框
THIN_BORDER = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)

# 对齐
ALIGN_CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
ALIGN_LEFT = Alignment(horizontal='left', vertical='center', wrap_text=True)
ALIGN_RIGHT = Alignment(horizontal='right', vertical='center')
```

### 条件格式模板
```python
# 毛利率预警（三条硬约束之一）
def add_margin_conditional(ws, col_letter, start_row, end_row, threshold=0.3):
    """毛利率低于阈值标红"""
    ws.conditional_formatting.add(
        f'{col_letter}{start_row}:{col_letter}{end_row}',
        CellIsRule(operator='lessThan', formula=[str(threshold)],
                   fill=TX_DANGER_FILL,
                   font=Font(color='DC3545', bold=True))
    )

# 库存效期预警（三条硬约束之一）
def add_expiry_conditional(ws, col_letter, start_row, end_row):
    """3天内过期标黄，已过期标红"""
    ws.conditional_formatting.add(
        f'{col_letter}{start_row}:{col_letter}{end_row}',
        CellIsRule(operator='lessThan', formula=['TODAY()'],
                   fill=TX_DANGER_FILL)
    )
    ws.conditional_formatting.add(
        f'{col_letter}{start_row}:{col_letter}{end_row}',
        CellIsRule(operator='lessThan', formula=['TODAY()+3'],
                   fill=TX_WARNING_FILL)
    )
```

### 代码结构
```python
def generate_xlsx(output_path: str, data: list[dict]):
    wb = Workbook()
    ws = wb.active

    # 1. 标题区
    _add_title_section(ws, title, subtitle, date_range)

    # 2. 表头（冻结）
    _add_headers(ws, columns, header_row=4)
    ws.freeze_panes = 'A5'

    # 3. 数据区
    _add_data_rows(ws, data, start_row=5)

    # 4. 汇总行
    _add_summary_row(ws, data_end_row)

    # 5. 条件格式
    _add_conditional_formats(ws)

    # 6. 列宽自适应
    _auto_fit_columns(ws)

    # 7. 打印设置
    _setup_print(ws)

    wb.save(output_path)
```

### 打印设置
```python
def _setup_print(ws):
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = '1:4'  # 每页重复标题+表头
    ws.sheet_properties.pageSetUpPr.fitToPage = True
```

## 核心铁律

1. **表头必须冻结** — `freeze_panes` 在表头下一行
2. **有数据就有汇总** — 最后一行用 SUM/AVERAGE 公式
3. **金额用千分位** — `#,##0.00` 格式
4. **百分比用百分号** — `0.0%` 格式
5. **毛利率低于阈值必须标红** — 三条硬约束可视化
6. **列宽自适应** — 不出现 `###` 截断
7. **有打印设置** — 横向A4，自适应宽度，重复表头

## 设计审查清单

- [ ] openpyxl 已安装？
- [ ] 表头行冻结？
- [ ] 金额列千分位格式？
- [ ] 百分比列百分号格式？
- [ ] 有汇总行和公式？
- [ ] 条件格式有毛利/效期预警？
- [ ] 列宽自适应？
- [ ] 打印设置横向A4？
- [ ] 品牌色从常量引用？
