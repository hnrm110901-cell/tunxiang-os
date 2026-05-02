/**
 * SankeyChart -- Pure SVG Sankey (flow) diagram.
 *
 * Renders a horizontal flow diagram where links between nodes
 * are shown as curved paths whose width is proportional to value.
 * Ideal for: category-to-channel sales flows, member-to-consumption
 * distribution, store-to-dish revenue attribution.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

export interface SankeyLink {
  source: string;
  target: string;
  value: number;
}

export interface SankeyChartProps {
  data: SankeyLink[];
  title?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
}

const NODE_COLORS = [
  '#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D',
  '#8B5CF6', '#0891B2', '#BE185D', '#4D7C0F', '#B45309',
];

interface SankeyNode {
  id: string; label: string; x: number; y: number;
  height: number; totalIn: number; totalOut: number; color: string;
}

interface SankeyFlow {
  source: SankeyNode; target: SankeyNode; value: number;
  sourceOffset: number; targetOffset: number;
}

function computeSankeyLayout(
  links: SankeyLink[], w: number, h: number
): { nodes: SankeyNode[]; flows: SankeyFlow[] } | null {
  const nodeMap = new Map<string, { inVal: number; outVal: number }>();
  for (const l of links) {
    if (\!nodeMap.has(l.source)) nodeMap.set(l.source, { inVal: 0, outVal: 0 });
    if (\!nodeMap.has(l.target)) nodeMap.set(l.target, { inVal: 0, outVal: 0 });
    nodeMap.get(l.source)\!.outVal += l.value;
    nodeMap.get(l.target)\!.inVal += l.value;
  }

  const sources: string[] = [];
  const sinks: string[] = [];
  const intermediates: string[] = [];
  for (const [id, vals] of nodeMap) {
    if (vals.inVal === 0 && vals.outVal > 0) sources.push(id);
    else if (vals.outVal === 0 && vals.inVal > 0) sinks.push(id);
    else intermediates.push(id);
  }

  const levels: string[][] = [];
  if (sources.length) levels.push(sources);
  if (intermediates.length) levels.push(intermediates);
  if (sinks.length) levels.push(sinks);
  if (levels.length === 0) levels.push([...nodeMap.keys()]);

  const numLevels = levels.length;
  const marginX = 80;
  const marginY = 40;
  const plotW = w - marginX * 2;
  const plotH = h - marginY * 2;
  const levelXSpacing = numLevels > 1 ? plotW / (numLevels - 1) : plotW / 2;

  const nodes: SankeyNode[] = [];
  const nodeIndex = new Map<string, SankeyNode>();

  for (let li = 0; li < levels.length; li++) {
    const levelNodes = levels[li];
    const x = marginX + li * levelXSpacing;
    const nodeGap = 12;
    const totalH = plotH - (levelNodes.length - 1) * nodeGap;
    const flows = levelNodes.map((id) => {
      const vals = nodeMap.get(id)\!;
      return Math.max(vals.inVal, vals.outVal);
    });
    const flowSum = flows.reduce((a, b) => a + b, 0) || 1;

    let y = marginY;
    for (let ni = 0; ni < levelNodes.length; ni++) {
      const id = levelNodes[ni];
      const vals = nodeMap.get(id)\!;
      const nodeH = Math.max(20, (flows[ni] / flowSum) * totalH);
      const node: SankeyNode = {
        id, label: id, x, y, height: nodeH,
        totalIn: vals.inVal, totalOut: vals.outVal,
        color: NODE_COLORS[li % NODE_COLORS.length],
      };
      nodes.push(node);
      nodeIndex.set(id, node);
      y += nodeH + nodeGap;
    }
  }

  const flows: SankeyFlow[] = [];
  const sourceOffsets = new Map<string, number>();
  const targetOffsets = new Map<string, number>();

  for (const link of links) {
    const src = nodeIndex.get(link.source);
    const tgt = nodeIndex.get(link.target);
    if (\!src || \!tgt) continue;
    const srcOff = sourceOffsets.get(link.source) || 0;
    const tgtOff = targetOffsets.get(link.target) || 0;
    flows.push({ source: src, target: tgt, value: link.value, sourceOffset: srcOff, targetOffset: tgtOff });
    sourceOffsets.set(link.source, srcOff + link.value);
    targetOffsets.set(link.target, tgtOff + link.value);
  }

  return { nodes, flows };
}

function fmtLarge(v: number): string {
  if (v >= 10000) return (v / 10000).toFixed(1) + '万';
  return v.toLocaleString();
}

export const SankeyChart: React.FC<SankeyChartProps> = ({
  data, title, width = 700, height = 400, className = '', darkMode = false,
}) => {
  const [hoverFlow, setHoverFlow] = useState<number | null>(null);
  const [hoverNode, setHoverNode] = useState<string | null>(null);

  const layout = useMemo(
    () => computeSankeyLayout(data, width, height),
    [data, width, height],
  );

  if (\!layout || \!layout.nodes.length) {
    return (
      <div className={className} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: darkMode ? '#9CA3AF' : '#666' }} role="img" aria-label="Sankey chart: no data">
        No data
      </div>
    );
  }

  const { nodes, flows } = layout;
  const textColor = darkMode ? '#D1D5DB' : '#374151';

  return (
    <div className={'relative ' + className} role="img" aria-label={title || 'Sankey chart'}>
      {title && (
        <h3 className={'text-sm font-medium mb-2 ' + (darkMode ? 'text-gray-300' : 'text-gray-700')}>{title}</h3>
      )}
      <svg viewBox={'0 0 ' + width + ' ' + height} className="w-full h-auto" style={{ overflow: 'visible' }}>
        {flows.map((flow, fi) => {
          const isHover = hoverFlow === fi || hoverNode === flow.source.id || hoverNode === flow.target.id;
          const srcNode = flow.source;
          const tgtNode = flow.target;
          const srcMax = Math.max(srcNode.totalOut, 1);
          const tgtMax = Math.max(tgtNode.totalIn, 1);
          const srcThickness = Math.max((flow.value / srcMax) * srcNode.height, 2);
          const tgtThickness = Math.max((flow.value / tgtMax) * tgtNode.height, 2);
          const srcY = srcNode.y + (flow.sourceOffset / srcMax) * srcNode.height;
          const tgtY = tgtNode.y + (flow.targetOffset / tgtMax) * tgtNode.height;
          const srcX = srcNode.x;
          const tgtX = tgtNode.x;
          const midX = (srcX + tgtX) / 2;

          const pathD = [
            'M ' + srcX + ' ' + srcY,
            'C ' + midX + ' ' + srcY + ' ' + midX + ' ' + tgtY + ' ' + tgtX + ' ' + tgtY,
            'L ' + tgtX + ' ' + (tgtY + tgtThickness),
            'C ' + midX + ' ' + (tgtY + tgtThickness) + ' ' + midX + ' ' + (srcY + srcThickness) + ' ' + srcX + ' ' + (srcY + srcThickness),
            'Z',
          ].join(' ');

          const alpha = isHover ? 0.85 : 0.35;

          return (
            <g key={fi}>
              <path d={pathD} fill={srcNode.color} fillOpacity={alpha} stroke="none"
                style={{ transition: 'fill-opacity 0.2s ease' }}
                onMouseEnter={() => setHoverFlow(fi)}
                onMouseLeave={() => setHoverFlow(null)}
              />
              {isHover && (
                <text x={midX} y={(srcY + tgtY) / 2 + 4} textAnchor="middle" fill={textColor} fontSize={12} fontWeight={600}>
                  {fmtLarge(flow.value)}
                </text>
              )}
            </g>
          );
        })}
        {nodes.map((node) => {
          const isHover = hoverNode === node.id;
          const displayW = 20;
          return (
            <g key={node.id} onMouseEnter={() => setHoverNode(node.id)} onMouseLeave={() => setHoverNode(null)} style={{ cursor: 'pointer' }}>
              <rect x={node.x - displayW / 2} y={node.y} width={displayW} height={Math.max(node.height, 4)}
                rx={3} fill={node.color} fillOpacity={isHover ? 1 : 0.85}
                stroke={isHover ? '#FFFFFF' : 'none'} strokeWidth={isHover ? 2 : 0}
                style={{ transition: 'fill-opacity 0.2s ease' }}
              />
              <text x={node.x - displayW / 2 - 8} y={node.y + node.height / 2 + 4}
                textAnchor="end" fill={isHover ? node.color : textColor}
                fontSize={11} fontWeight={isHover ? 600 : 400}>
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export default SankeyChart;
