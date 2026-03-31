---
name: docx
description: "Word文档(.docx)生成技能。当用户要求生成Word文档、商业计划书、产品方案书、合同模板、操作手册、培训材料、客户提案、需求文档、技术方案、招商手册时触发。支持屯象OS品牌视觉规范、中文排版、多级标题、表格、图表嵌入、页眉页脚、目录生成等专业文档功能。关键词：docx、word、文档、方案书、计划书、手册、提案、合同。"
---

# Word 文档专业生成技能

## 概述

基于 `python-docx` 库生成专业级 Word 文档，内置屯象OS品牌规范和中文餐饮行业文档模板。
所有文档自动应用品牌色、统一排版、专业页眉页脚。

## 第一步：识别文档类型

| 关键词 | 文档类型 | 模板 |
|--------|---------|------|
| 方案书、提案、pitch | **商业提案** | `references/templates.md#商业提案` |
| 计划书、规划、roadmap | **计划文档** | `references/templates.md#计划文档` |
| 合同、协议、条款 | **合同模板** | `references/templates.md#合同模板` |
| 手册、教程、培训 | **操作手册** | `references/templates.md#操作手册` |
| 报告、分析、总结 | **分析报告** | `references/templates.md#分析报告` |
| 需求、PRD、产品文档 | **需求文档** | `references/templates.md#需求文档` |
| 招商、加盟、宣传 | **招商手册** | `references/templates.md#招商手册` |
| 不确定 | → 询问用户 | — |

## 第二步：读取参考文件

生成文档前**必须读取**：
- `references/templates.md` — 文档模板结构定义
- `references/brand-style.md` — 屯象品牌视觉规范（色彩、字体、间距）

## 第三步：内容规划

在生成代码前确认：
1. **文档受众是谁？** 投资人？客户？内部团队？加盟商？
2. **核心信息点是什么？** 不超过5个核心信息
3. **需要嵌入什么数据？** 图表？截图？表格？
4. **输出路径？** 默认 `output/docs/`

## 第四步：生成 Python 脚本

使用 `python-docx` 生成文档，规则：

### 品牌规范（强制）
```python
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

# 屯象品牌色
TX_PRIMARY = RGBColor(0xFF, 0x6B, 0x35)    # #FF6B35
TX_NAVY = RGBColor(0x1E, 0x2A, 0x3A)       # #1E2A3A
TX_TEXT = RGBColor(0x33, 0x33, 0x33)        # #333333
TX_TEXT_LIGHT = RGBColor(0x66, 0x66, 0x66)  # #666666
TX_BG_LIGHT = RGBColor(0xF8, 0xF9, 0xFA)   # #F8F9FA

# 中文字体
FONT_TITLE = '微软雅黑'       # 标题
FONT_BODY = '微软雅黑'        # 正文（macOS用'PingFang SC'）
FONT_MONO = 'Cascadia Code'   # 代码

# 字号规范
SIZE_H1 = Pt(24)
SIZE_H2 = Pt(18)
SIZE_H3 = Pt(14)
SIZE_BODY = Pt(11)
SIZE_CAPTION = Pt(9)
```

### 排版规则
- 页边距：上下2.54cm，左右3.17cm（标准A4）
- 行距：1.5倍
- 段前段后间距：H1=24pt/12pt，H2=18pt/6pt，正文=6pt/6pt
- 表格：首行深色背景（TX_NAVY），交替行浅灰底
- 页眉：左侧"屯象科技 | 文档标题"，右侧页码
- 页脚：居中"机密文档 — 仅供[受众]阅读"

### 代码结构
```python
def generate_docx(output_path: str):
    doc = Document()

    # 1. 设置页面
    _setup_page(doc)

    # 2. 添加封面
    _add_cover_page(doc, title, subtitle, date)

    # 3. 添加目录占位
    _add_toc_placeholder(doc)

    # 4. 添加正文章节
    for section in sections:
        _add_section(doc, section)

    # 5. 设置页眉页脚
    _setup_header_footer(doc, title)

    # 6. 保存
    doc.save(output_path)
```

### 表格样式
```python
def _style_table(table):
    """屯象标准表格样式"""
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # 首行深色
    for cell in table.rows[0].cells:
        cell._element.get_or_add_tcPr().append(
            parse_xml(f'<w:shd {nsdecls("w")} w:fill="1E2A3A"/>')
        )
        for p in cell.paragraphs:
            for run in p.runs:
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                run.font.bold = True
    # 交替行
    for i, row in enumerate(table.rows[1:], 1):
        if i % 2 == 0:
            for cell in row.cells:
                cell._element.get_or_add_tcPr().append(
                    parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8F9FA"/>')
                )
```

## 核心铁律

1. **品牌色必须从常量引用** — 不硬编码 RGB 值
2. **中文字体必须指定** — 不依赖默认字体（英文环境下会乱码）
3. **所有文档必须有封面页** — 包含：标题、副标题、日期、公司名、机密等级
4. **表格不能空** — 没有数据时用"暂无数据"占位，不留空行
5. **输出前必须确认路径** — 默认 `output/docs/`，用户指定时用用户路径
6. **脚本可重复执行** — 不依赖外部状态，运行即生成

## 设计审查清单

- [ ] python-docx 已安装或脚本头部有 pip install？
- [ ] 使用了屯象品牌色常量？
- [ ] 中文字体已指定（微软雅黑/PingFang SC）？
- [ ] 有封面页？
- [ ] 有页眉页脚？
- [ ] 表格有首行样式？
- [ ] 行距1.5倍？
- [ ] 输出路径存在或自动创建？
- [ ] 文件名包含日期？
