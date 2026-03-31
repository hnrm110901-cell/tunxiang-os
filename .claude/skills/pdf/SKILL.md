---
name: pdf
description: "PDF文档生成技能。当用户要求生成PDF报告、分析报表、合同PDF、菜单PDF、营业报告、数据导出PDF时触发。基于ReportLab库，支持中文排版、表格、图表（Matplotlib集成）、页眉页脚、多页布局、水印。与docx技能的区别：PDF用于最终交付物（不可编辑），docx用于协作文档（可编辑）。关键词：pdf、报告、报表、导出PDF、打印版。"
---

# PDF 文档专业生成技能

## 概述

基于 `reportlab` + `matplotlib` 生成专业 PDF 文档。
适用于最终交付物：营业报告、分析报表、合同、菜单等不可编辑的正式文档。

## 第一步：识别文档类型

| 类型 | 触发词 | 特征 |
|------|--------|------|
| **营业报告** | 日报、周报、月报 | 数据+图表+趋势分析 |
| **分析报表** | 分析、对比、排名 | 多维度图表+表格+结论 |
| **菜单** | 菜单、菜单PDF | 图文排版+价格+分类 |
| **合同/协议** | 合同PDF、协议PDF | 条款+签名区+骑缝章位 |
| **证书/凭证** | 证书、凭证、收据 | 固定版式+流水号 |

## 第二步：读取参考

- `references/pdf-patterns.md` — PDF 排版模式和中文字体配置
- 营业报告类还需参考已有的 `services/tx-analytics/src/reports/weekly_report_pdf.py`

## 第三步：生成 Python 脚本

### 中文字体配置（关键）
```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, PageBreak, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# 注册中文字体（必须）
# Linux: 使用 WenQuanYi 或 Noto Sans CJK
# macOS: 使用 PingFang SC
import platform
if platform.system() == 'Darwin':
    FONT_PATH = '/System/Library/Fonts/PingFang.ttc'
    FONT_NAME = 'PingFang'
else:
    # Linux - 尝试多个路径
    FONT_CANDIDATES = [
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    ]
    FONT_PATH = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
    FONT_NAME = 'WenQuanYi'

if FONT_PATH:
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))

# 屯象品牌色
TX_PRIMARY = HexColor('#FF6B35')
TX_NAVY = HexColor('#1E2A3A')
TX_TEXT = HexColor('#333333')
TX_LIGHT_BG = HexColor('#F8F9FA')
TX_WHITE = HexColor('#FFFFFF')
TX_SUCCESS = HexColor('#28A745')
TX_WARNING = HexColor('#FFC107')
TX_DANGER = HexColor('#DC3545')
```

### 样式定义
```python
def get_tx_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        'TXTitle', fontName=FONT_NAME, fontSize=24,
        textColor=TX_NAVY, alignment=TA_CENTER,
        spaceAfter=12*mm
    ))
    styles.add(ParagraphStyle(
        'TXH1', fontName=FONT_NAME, fontSize=18,
        textColor=TX_NAVY, spaceBefore=8*mm, spaceAfter=4*mm
    ))
    styles.add(ParagraphStyle(
        'TXH2', fontName=FONT_NAME, fontSize=14,
        textColor=TX_PRIMARY, spaceBefore=6*mm, spaceAfter=3*mm
    ))
    styles.add(ParagraphStyle(
        'TXBody', fontName=FONT_NAME, fontSize=10,
        textColor=TX_TEXT, leading=16, spaceAfter=3*mm
    ))
    return styles
```

### 表格样式
```python
TX_TABLE_STYLE = TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), TX_NAVY),
    ('TEXTCOLOR', (0, 0), (-1, 0), TX_WHITE),
    ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ('FONTSIZE', (0, 0), (-1, 0), 11),
    ('FONTSIZE', (0, 1), (-1, -1), 9),
    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#D9D9D9')),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [TX_WHITE, TX_LIGHT_BG]),
    ('TOPPADDING', (0, 0), (-1, -1), 6),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
])
```

### 页眉页脚
```python
def _header_footer(canvas, doc):
    canvas.saveState()
    # 页眉
    canvas.setFont(FONT_NAME, 8)
    canvas.setFillColor(TX_TEXT)
    canvas.drawString(2*cm, A4[1] - 1.5*cm, f'屯象科技 | {doc.title}')
    canvas.drawRightString(A4[0] - 2*cm, A4[1] - 1.5*cm,
                           datetime.now().strftime('%Y-%m-%d'))
    canvas.setStrokeColor(TX_PRIMARY)
    canvas.setLineWidth(0.5)
    canvas.line(2*cm, A4[1] - 1.7*cm, A4[0] - 2*cm, A4[1] - 1.7*cm)

    # 页脚
    canvas.drawCentredString(A4[0]/2, 1.5*cm,
                              f'第 {doc.page} 页')
    canvas.restoreState()
```

## 核心铁律

1. **必须注册中文字体** — 不注册字体中文会显示方块
2. **品牌色从常量引用** — 不硬编码颜色值
3. **有页眉页脚** — 页眉含公司名和文档标题，页脚含页码
4. **表格不溢出** — 长文本自动换行，列宽按内容比例分配
5. **图表嵌入用 Matplotlib** — 先生成临时图片，再嵌入 PDF
6. **输出前确认路径** — 默认 `output/reports/`

## 设计审查清单

- [ ] reportlab 和 matplotlib 已安装？
- [ ] 中文字体已注册？
- [ ] 品牌色从常量引用？
- [ ] 有页眉页脚？
- [ ] 表格内容不溢出？
- [ ] 图表清晰度足够（dpi≥150）？
- [ ] 输出路径存在或自动创建？
