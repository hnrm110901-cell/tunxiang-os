---
name: pptx
description: "PowerPoint演示文稿(.pptx)生成技能。当用户要求制作PPT、演示文稿、路演材料、投资人汇报、客户演示、产品介绍、培训课件、季度汇报、商业计划演示时触发。内置屯象OS品牌主题模板、中文排版、数据可视化图表嵌入、动画建议。关键词：pptx、ppt、演示、路演、汇报、课件、slides、presentation、deck。"
---

# PowerPoint 演示文稿专业生成技能

## 概述

基于 `python-pptx` 库生成专业演示文稿，内置屯象OS品牌模板。
支持封面、目录、内容页、数据页、对比页、总结页等标准版式。

## 第一步：识别演示类型

| 类型 | 触发词 | 风格 | 页数参考 |
|------|--------|------|---------|
| **投资路演** | 路演、融资、投资人 | 数据驱动+愿景 | 15-20页 |
| **客户演示** | 客户、提案、售前 | 痛点→方案→案例 | 10-15页 |
| **产品介绍** | 产品、功能、demo | 功能展示+截图 | 8-12页 |
| **季度汇报** | 季度、月度、汇报、总结 | 数据+趋势+计划 | 12-18页 |
| **培训课件** | 培训、教程、课件 | 步骤分解+示例 | 15-25页 |
| **招商加盟** | 招商、加盟、合作 | 品牌+收益+支持 | 12-16页 |

## 第二步：读取参考

- `references/slide-templates.md` — 幻灯片版式模板库
- 同时参考 docx 技能的 `references/brand-style.md` 保持品牌一致

## 第三步：内容规划

### 演示结构公式

**投资路演（Guy Kawasaki 10-20-30法则改良）：**
```
1. 封面（公司名+一句话定位）
2. 痛点（连锁餐饮行业的痛）
3. 解决方案（屯象OS一句话）
4. 商业模式（怎么赚钱）
5. 底层技术（AI+Ontology壁垒）
6. 市场规模（TAM/SAM/SOM）
7. 竞争格局（vs传统系统）
8. 产品演示（核心截图/流程）
9. 牵引力（客户数据/增长）
10. 团队
11. 财务预测
12. 融资计划
```

**客户演示（SPIN结构）：**
```
1. 封面
2. 您的现状（Situation）
3. 您面临的问题（Problem）
4. 问题带来的影响（Implication）
5. 屯象OS如何解决（Need-Payoff）
6-8. 核心功能展示
9. 客户案例
10. 实施方案+报价
11. 下一步
```

## 第四步：生成 Python 脚本

### 品牌主题（强制）
```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# 屯象品牌色
TX_PRIMARY = RGBColor(0xFF, 0x6B, 0x35)
TX_NAVY = RGBColor(0x1E, 0x2A, 0x3A)
TX_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TX_LIGHT_BG = RGBColor(0xF8, 0xF9, 0xFA)
TX_TEXT = RGBColor(0x33, 0x33, 0x33)
TX_TEXT_LIGHT = RGBColor(0x66, 0x66, 0x66)

# 幻灯片尺寸：16:9
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# 字体
FONT_TITLE = '微软雅黑'
FONT_BODY = '微软雅黑'

# 字号
SIZE_SLIDE_TITLE = Pt(36)
SIZE_SLIDE_SUBTITLE = Pt(20)
SIZE_HEADING = Pt(28)
SIZE_BODY = Pt(18)
SIZE_CAPTION = Pt(12)
SIZE_PAGE_NUM = Pt(10)
```

### 标准版式

**封面页：** 深色背景（TX_NAVY），居中大标题，副标题，底部日期+公司
**内容页：** 白底，左上标题栏（橙色下划线），正文区域
**数据页：** 白底，标题+大数字突出+图表区域
**对比页：** 左右分栏，Before/After 或 竞品对比
**引用页：** 深色背景，居中大字引言
**总结页：** 关键要点列表，CTA按钮

### 代码结构
```python
def generate_pptx(output_path: str):
    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    _add_cover_slide(prs, title, subtitle, date)
    _add_agenda_slide(prs, sections)

    for section in sections:
        _add_section_divider(prs, section.title)
        for content in section.contents:
            _add_content_slide(prs, content)

    _add_summary_slide(prs, key_points)
    _add_contact_slide(prs)
    _add_page_numbers(prs)

    prs.save(output_path)
```

## 核心铁律

1. **16:9 比例** — 不用 4:3
2. **每页一个核心信息** — 不堆砌内容
3. **文字最少化** — 标题 ≤ 8字，要点 ≤ 6行，每行 ≤ 15字
4. **数据要可视化** — 有数据就用图表，不用纯文字表格
5. **品牌色一致** — 主色 #FF6B35，辅色 #1E2A3A
6. **有页码** — 除封面外所有页右下角标页码

## 设计审查清单

- [ ] python-pptx 已安装？
- [ ] 16:9 比例？
- [ ] 封面页有公司名+日期？
- [ ] 每页核心信息不超过1个？
- [ ] 字体使用微软雅黑？
- [ ] 品牌色从常量引用？
- [ ] 有页码？
- [ ] 总页数在合理范围（8-25页）？
