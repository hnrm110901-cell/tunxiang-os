# PDF 排版模式与中文字体配置

## 中文字体安装检测

### 优先级列表
```python
FONT_SEARCH_PATHS = {
    'Darwin': [  # macOS
        ('/System/Library/Fonts/PingFang.ttc', 'PingFang'),
        ('/System/Library/Fonts/STHeiti Light.ttc', 'STHeiti'),
    ],
    'Linux': [
        ('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', 'WenQuanYi'),
        ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 'NotoSansCJK'),
        ('/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc', 'NotoSansCJK'),
        ('/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc', 'NotoSansCJK'),
    ],
    'Windows': [
        ('C:/Windows/Fonts/msyh.ttc', 'MicrosoftYaHei'),
        ('C:/Windows/Fonts/simhei.ttf', 'SimHei'),
    ],
}
```

### 字体注册通用函数
```python
import os
import platform
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_chinese_font() -> str:
    """注册中文字体，返回字体名称"""
    system = platform.system()
    paths = FONT_SEARCH_PATHS.get(system, FONT_SEARCH_PATHS['Linux'])

    for font_path, font_name in paths:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            return font_name

    # 最终后备：使用 reportlab 内置 Helvetica（中文会乱码，但不崩溃）
    return 'Helvetica'
```

## 页面布局模式

### 模式A：报告型（单栏）
```
┌─────────────────────────┐
│ [页眉: 公司名 | 标题]    │
│ ─────────────────────── │
│                         │
│ [章节标题]               │
│                         │
│ [正文段落]               │
│ [正文段落]               │
│                         │
│ [表格/图表]              │
│                         │
│ [正文段落]               │
│                         │
│ ─────────────────────── │
│ [页脚: 页码]             │
└─────────────────────────┘
```

### 模式B：仪表板型（多栏）
```
┌─────────────────────────┐
│ [页眉]                   │
│ ─────                   │
│ ┌─────┐ ┌─────┐ ┌─────┐│
│ │ KPI │ │ KPI │ │ KPI ││
│ └─────┘ └─────┘ └─────┘│
│                         │
│ ┌───────────┐ ┌────────┐│
│ │  图表      │ │ 表格   ││
│ │           │ │        ││
│ └───────────┘ └────────┘│
│                         │
│ [页脚]                   │
└─────────────────────────┘
```

### 模式C：菜单型（图文混排）
```
┌─────────────────────────┐
│ [品牌Banner]             │
│                         │
│ [分类标题]               │
│ ┌──────┐ ┌──────┐      │
│ │ 图片 │ │ 图片 │      │
│ │ 菜名 │ │ 菜名 │      │
│ │ 价格 │ │ 价格 │      │
│ └──────┘ └──────┘      │
│                         │
└─────────────────────────┘
```

## Matplotlib 图表嵌入

### 标准图表样式
```python
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'PingFang SC', 'SimHei']
matplotlib.rcParams['axes.unicode_minus'] = False

def create_chart(data, chart_type, title, output_path):
    fig, ax = plt.subplots(figsize=(8, 4), dpi=200)

    # 屯象配色
    colors = ['#FF6B35', '#1E2A3A', '#4ECDC4', '#45B7D1', '#96CEB4']

    if chart_type == 'bar':
        ax.bar(data.keys(), data.values(), color=colors[:len(data)])
    elif chart_type == 'line':
        ax.plot(list(data.keys()), list(data.values()),
                color='#FF6B35', linewidth=2, marker='o')
    elif chart_type == 'pie':
        ax.pie(data.values(), labels=data.keys(), colors=colors,
               autopct='%1.1f%%', startangle=90)

    ax.set_title(title, fontsize=14, fontweight='bold', color='#1E2A3A')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close()
    return output_path
```

### 嵌入 PDF
```python
from reportlab.platypus import Image
from reportlab.lib.units import cm

# 生成临时图表
chart_path = create_chart(data, 'bar', '月度营业额趋势', '/tmp/chart.png')

# 嵌入到 story
story.append(Image(chart_path, width=16*cm, height=8*cm))
```

## 水印

```python
def add_watermark(canvas, doc, text="机密文档"):
    canvas.saveState()
    canvas.setFont('PingFang', 36)
    canvas.setFillColor(HexColor('#000000'))
    canvas.setFillAlpha(0.05)
    canvas.translate(A4[0]/2, A4[1]/2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, text)
    canvas.restoreState()
```
