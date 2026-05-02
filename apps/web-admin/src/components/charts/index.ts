/**
 * 屯象OS Chart Component Library -- Unified Export
 *
 * Pure SVG/CSS implementation. No ECharts, D3, or other heavy dependencies.
 * Pattern: BI-2.1 Complex Charts Component Library
 */

// Basic charts (existing)
export { TxLineChart } from './TxLineChart';
export { TxBarChart } from './TxBarChart';
export { TxPieChart } from './TxPieChart';
export { TxHeatmap } from './TxHeatmap';
export { TxRadarChart } from './TxRadarChart';
export { TxScatterChart } from './TxScatterChart';

// Complex charts (BI-2.1)
export { FunnelChart } from './FunnelChart';
export type { FunnelStage, FunnelChartProps } from './FunnelChart';

export { SankeyChart } from './SankeyChart';
export type { SankeyLink, SankeyChartProps } from './SankeyChart';

export { BoxPlotChart } from './BoxPlotChart';
export type { BoxPlotData, BoxPlotChartProps } from './BoxPlotChart';

export { HeatmapChart } from './HeatmapChart';
export type { HeatmapCell, HeatmapChartProps } from './HeatmapChart';

export { BubbleChart } from './BubbleChart';
export type { BubblePoint, BubbleChartProps } from './BubbleChart';

export { WaterfallChart } from './WaterfallChart';
export type { WaterfallBar, WaterfallChartProps } from './WaterfallChart';

export { RadarChart } from './RadarChart';
export type { RadarDimension, RadarSeries, RadarChartProps } from './RadarChart';
