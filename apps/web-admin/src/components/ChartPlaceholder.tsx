/**
 * ChartPlaceholder -- ECharts / @ant-design/charts 图表占位组件
 * 统一标注图表接入点，后续替换为真实图表库渲染。
 *
 * 用法:
 *   <ChartPlaceholder title="营收趋势" chartType="Line" apiEndpoint="GET /api/v1/dashboard/revenue-trend" />
 */

interface ChartPlaceholderProps {
  /** 图表标题 */
  title: string;
  /** 图表类型（Line / Bar / Pie / Funnel / Radar / Gauge 等） */
  chartType: string;
  /** 数据来源 API */
  apiEndpoint: string;
  /** 容器高度，默认 240 */
  height?: number;
}

const CHART_ICONS: Record<string, string> = {
  Line: '\u{1F4C8}',    // 折线
  Bar: '\u{1F4CA}',     // 柱状
  Pie: '\u{1F967}',     // 饼图
  Funnel: '\u{1F53B}',  // 漏斗
  Radar: '\u{1F578}',   // 雷达
  Gauge: '\u{1F3AF}',   // 仪表盘
  Area: '\u{1F30A}',    // 面积
  Scatter: '\u{2B50}',  // 散点
  Heatmap: '\u{1F525}', // 热力
  Rank: '\u{1F3C6}',    // 排行
};

export function ChartPlaceholder({
  title,
  chartType,
  apiEndpoint,
  height = 240,
}: ChartPlaceholderProps) {
  const icon = CHART_ICONS[chartType] || '\u{1F4C8}';

  return (
    <div
      style={{
        background: '#112228',
        borderRadius: 8,
        padding: 20,
        minHeight: height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: '1px dashed #1a2a33',
      }}
    >
      <div style={{ textAlign: 'center', color: '#666' }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>{icon}</div>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#ccc', marginBottom: 4 }}>
          {title}
        </div>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>
          {chartType} 图表 -- @ant-design/charts 接入点
        </div>
        <div
          style={{
            fontSize: 11,
            color: '#555',
            marginTop: 6,
            padding: '3px 10px',
            borderRadius: 4,
            background: '#0B1A20',
            display: 'inline-block',
          }}
        >
          {apiEndpoint}
        </div>
      </div>
    </div>
  );
}
