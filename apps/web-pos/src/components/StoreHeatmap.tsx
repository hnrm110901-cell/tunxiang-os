/**
 * StoreHeatmap — 门店数字孪生仪表盘（2D 鸟瞰 + 热力图）
 *
 * Phase 3: Canvas 渲染门店桌台平面图，支持：
 *   - 状态视图（空闲/就餐/超时/预订/VIP 颜色编码）
 *   - 热力图视图（就餐时长/消费金额/翻台率 渐变映射）
 *   - 悬停 tooltip + 点击选择
 *   - 区域标注 + 图例
 */
import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { txColors } from '@tx/tokens';

// ─── Types ──────────────────────────────────────────────────────────────────────

export interface TableInfo {
  tableNo: string;
  area: string;
  seats: number;
  status: 'free' | 'occupied' | 'overtime' | 'reserved' | 'vip';
  guestCount: number;
  orderId?: string;
  revenueFen?: number;       // 消费金额（分）
  diningMinutes?: number;    // 就餐时长（分钟）
  waiterName?: string;
  turnoverCount?: number;    // 今日翻台次数
}

type HeatmapMetric = 'duration' | 'revenue' | 'turnover';

interface StoreHeatmapProps {
  tables: TableInfo[];
  /** 选中桌台回调 */
  onSelectTable?: (table: TableInfo) => void;
  /** 默认视图模式 */
  defaultMode?: 'status' | 'heatmap';
}

// ─── Design Tokens ──────────────────────────────────────────────────────────────

const COLORS = {
  free: txColors.success,
  occupied: txColors.info,
  overtime: txColors.danger,
  reserved: txColors.warning,
  vip: '#722ed1',
  bg: '#0B1A20',
  zoneFill: 'rgba(255,255,255,0.02)',
  zoneBorder: 'rgba(255,255,255,0.06)',
  text: '#E0E0E0',
  text2: 'rgba(255,255,255,0.55)',
  text3: 'rgba(255,255,255,0.3)',
  accent: txColors.primary,
  heatLow: '#10B981',
  heatMid: '#F59E0B',
  heatHigh: '#EF4444',
};

const STATUS_COLORS: Record<string, string> = {
  free: COLORS.free,
  occupied: COLORS.occupied,
  overtime: COLORS.overtime,
  reserved: COLORS.reserved,
  vip: COLORS.vip,
};

const STATUS_LABELS: Record<string, string> = {
  free: '空闲',
  occupied: '就餐中',
  overtime: '超时',
  reserved: '预订',
  vip: 'VIP',
};

// ─── Canvas 布局常量 ────────────────────────────────────────────────────────────

const CELL_W = 90;
const CELL_H = 60;
const CELL_GAP = 8;
const CELL_RADIUS = 8;
const ZONE_HEADER_H = 36;
const ZONE_PADDING = 24;

// ─── 工具函数 ────────────────────────────────────────────────────────────────────

/** 十六进制颜色插值 */
function lerpColor(a: string, b: string, t: number): string {
  const ah = parseInt(a.slice(1), 16);
  const bh = parseInt(b.slice(1), 16);
  const ar = (ah >> 16) & 0xff, ag = (ah >> 8) & 0xff, ab = ah & 0xff;
  const br = (bh >> 16) & 0xff, bg = (bh >> 8) & 0xff, bb = bh & 0xff;
  const r = Math.round(ar + (br - ar) * t);
  const g = Math.round(ag + (bg - ag) * t);
  const b = Math.round(ab + (bb - ab) * t);
  return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export function StoreHeatmap({ tables, onSelectTable, defaultMode = 'status' }: StoreHeatmapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<'status' | 'heatmap'>(defaultMode);
  const [heatMetric, setHeatMetric] = useState<HeatmapMetric>('duration');
  const [hoveredTable, setHoveredTable] = useState<TableInfo | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);

  // 按区域分组
  const zones = useMemo(() => {
    const map = new Map<string, TableInfo[]>();
    for (const t of tables) {
      const arr = map.get(t.area) || [];
      arr.push(t);
      map.set(t.area, arr);
    }
    return Array.from(map.entries());
  }, [tables]);

  // 计算 Canvas 尺寸
  const totalCols = Math.max(...zones.map(([, ts]) => ts.length), 1);
  const canvasW = Math.max(totalCols * (CELL_W + CELL_GAP) + ZONE_PADDING * 2, 400);
  const canvasH = zones.length * (CELL_H + ZONE_HEADER_H + CELL_GAP * 4) + 120;

  // 热力图颜色映射
  const getHeatColor = useCallback(
    (table: TableInfo): string => {
      if (table.status === 'free') return COLORS.free;
      let value = 0;
      let max = 1;
      switch (heatMetric) {
        case 'duration': value = table.diningMinutes || 0; max = 120; break;
        case 'revenue': value = (table.revenueFen || 0) / 100; max = 500; break;
        case 'turnover': value = table.turnoverCount || 0; max = 5; break;
      }
      const t = Math.min(value / max, 1);
      if (t < 0.5) return lerpColor(COLORS.heatLow, COLORS.heatMid, t * 2);
      return lerpColor(COLORS.heatMid, COLORS.heatHigh, (t - 0.5) * 2);
    },
    [heatMetric],
  );

  // 渲染 Canvas
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasW * dpr * scale;
    canvas.height = canvasH * dpr * scale;
    canvas.style.width = `${canvasW * scale}px`;
    canvas.style.height = `${canvasH * scale}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr * scale, dpr * scale);

    // 清除
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, canvasW, canvasH);

    // 标题
    ctx.fillStyle = COLORS.accent;
    ctx.font = 'bold 16px "Noto Sans SC", sans-serif';
    ctx.fillText('门店数字孪生 · 桌台鸟瞰', ZONE_PADDING, 28);

    let y = 50;

    for (const [area, areaTables] of zones) {
      // 区域标题
      ctx.fillStyle = COLORS.text;
      ctx.font = '600 13px "Noto Sans SC", sans-serif';
      ctx.fillText(`📍 ${area}（${areaTables.length} 桌）`, ZONE_PADDING, y + 16);

      // 区域背景
      const areaW = areaTables.length * (CELL_W + CELL_GAP) + ZONE_PADDING;
      ctx.fillStyle = COLORS.zoneFill;
      ctx.strokeStyle = COLORS.zoneBorder;
      ctx.lineWidth = 1;
      roundRect(ctx, ZONE_PADDING - 4, y + ZONE_HEADER_H - 4, areaW, CELL_H + 24, 12);
      ctx.fill();
      ctx.stroke();

      // 桌台块
      areaTables.forEach((table, i) => {
        const cx = ZONE_PADDING + i * (CELL_W + CELL_GAP);
        const cy = y + ZONE_HEADER_H + 8;

        // 热力图或状态颜色
        const fillColor = mode === 'heatmap' ? getHeatColor(table) : (STATUS_COLORS[table.status] || '#666');

        // 选中/悬停高亮
        const isHovered = hoveredTable?.tableNo === table.tableNo;

        // 桌台矩形
        ctx.fillStyle = fillColor;
        ctx.globalAlpha = isHovered ? 1 : 0.82;
        roundRect(ctx, cx, cy, CELL_W, CELL_H, CELL_RADIUS);
        ctx.fill();
        ctx.globalAlpha = 1;

        // 边框
        ctx.strokeStyle = isHovered ? '#fff' : 'rgba(255,255,255,0.15)';
        ctx.lineWidth = isHovered ? 2 : 1;
        roundRect(ctx, cx, cy, CELL_W, CELL_H, CELL_RADIUS);
        ctx.stroke();

        // 桌号
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 15px "Noto Sans SC", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(table.tableNo, cx + CELL_W / 2, cy + 22);

        // 状态 / 金额
        ctx.font = '11px "Noto Sans SC", sans-serif';
        if (mode === 'heatmap' && table.status !== 'free') {
          const metricLabel =
            heatMetric === 'duration' ? `${table.diningMinutes || 0}min` :
            heatMetric === 'revenue' ? `${((table.revenueFen || 0) / 100).toFixed(0)}元` :
            `翻${table.turnoverCount || 0}次`;
          ctx.fillText(metricLabel, cx + CELL_W / 2, cy + 42);
        } else {
          ctx.fillText(STATUS_LABELS[table.status] || '', cx + CELL_W / 2, cy + 42);
        }

        // 人数
        if (table.guestCount > 0) {
          ctx.fillStyle = 'rgba(255,255,255,0.6)';
          ctx.font = '11px "Noto Sans SC", sans-serif';
          ctx.fillText(`${table.guestCount}/${table.seats}人`, cx + CELL_W / 2, cy + 56);
        }

        ctx.textAlign = 'left';
      });

      y += CELL_H + ZONE_HEADER_H + CELL_GAP * 3;
    }

    // 底部统计
    const freeCount = tables.filter((t) => t.status === 'free').length;
    const occupiedCount = tables.filter((t) => t.status === 'occupied' || t.status === 'overtime').length;
    ctx.fillStyle = COLORS.text2;
    ctx.font = '12px "Noto Sans SC", sans-serif';
    ctx.fillText(
      `总桌数: ${tables.length} | 用餐中: ${occupiedCount} | 空闲: ${freeCount} | 翻台率: ${Math.round((occupiedCount / tables.length) * 100) || 0}%`,
      ZONE_PADDING,
      y + 20,
    );
  }, [tables, zones, mode, heatMetric, hoveredTable, canvasW, canvasH, scale, getHeatColor]);

  useEffect(() => {
    render();
  }, [render]);

  // 鼠标事件
  const getTableAtPos = useCallback(
    (clientX: number, clientY: number): TableInfo | null => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const mx = (clientX - rect.left) / scale;
      const my = (clientY - rect.top) / scale;

      let y = 50;
      for (const [, areaTables] of zones) {
        for (let i = 0; i < areaTables.length; i++) {
          const cx = ZONE_PADDING + i * (CELL_W + CELL_GAP);
          const cy = y + ZONE_HEADER_H + 8;
          if (mx >= cx && mx <= cx + CELL_W && my >= cy && my <= cy + CELL_H) {
            return areaTables[i];
          }
        }
        y += CELL_H + ZONE_HEADER_H + CELL_GAP * 3;
      }
      return null;
    },
    [zones, scale],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const table = getTableAtPos(e.clientX, e.clientY);
      setHoveredTable(table);
      if (table) {
        setTooltipPos({ x: e.clientX + 12, y: e.clientY - 10 });
      }
    },
    [getTableAtPos],
  );

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      const table = getTableAtPos(e.clientX, e.clientY);
      if (table) onSelectTable?.(table);
    },
    [getTableAtPos, onSelectTable],
  );

  const handleMouseLeave = () => setHoveredTable(null);

  return (
    <div ref={containerRef} style={{ fontFamily: 'Noto Sans SC, sans-serif' }}>
      {/* 控制栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 0', borderBottom: '1px solid rgba(255,255,255,0.06)', marginBottom: 12,
        flexWrap: 'wrap', gap: 8,
      }}>
        {/* 视图切换 */}
        <div style={{ display: 'flex', gap: 4, background: '#0D2430', borderRadius: 8, padding: 3 }}>
          <button
            onClick={() => setMode('status')}
            style={{
              padding: '6px 16px', minHeight: 36,
              background: mode === 'status' ? COLORS.accent : 'transparent',
              color: mode === 'status' ? '#fff' : COLORS.text2,
              border: 'none', borderRadius: 6, fontSize: 13, fontWeight: mode === 'status' ? 700 : 400,
              cursor: 'pointer',
            }}
          >
            📋 状态视图
          </button>
          <button
            onClick={() => setMode('heatmap')}
            style={{
              padding: '6px 16px', minHeight: 36,
              background: mode === 'heatmap' ? COLORS.accent : 'transparent',
              color: mode === 'heatmap' ? '#fff' : COLORS.text2,
              border: 'none', borderRadius: 6, fontSize: 13, fontWeight: mode === 'heatmap' ? 700 : 400,
              cursor: 'pointer',
            }}
          >
            🔥 热力视图
          </button>
        </div>

        {/* 热力图指标选择 */}
        {mode === 'heatmap' && (
          <div style={{ display: 'flex', gap: 4, background: '#0D2430', borderRadius: 8, padding: 3 }}>
            {([
              { key: 'duration', label: '⏱ 时长' },
              { key: 'revenue', label: '💰 金额' },
              { key: 'turnover', label: '🔄 翻台' },
            ] as const).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setHeatMetric(key)}
                style={{
                  padding: '6px 12px', minHeight: 32,
                  background: heatMetric === key ? 'rgba(255,107,53,0.15)' : 'transparent',
                  color: heatMetric === key ? COLORS.accent : COLORS.text2,
                  border: 'none', borderRadius: 6, fontSize: 12,
                  fontWeight: heatMetric === key ? 600 : 400, cursor: 'pointer',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {/* 缩放 */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            onClick={() => setScale((s) => Math.max(0.5, s - 0.1))}
            style={{
              width: 32, height: 32, background: '#1A3A48', color: COLORS.text2,
              border: 'none', borderRadius: 6, fontSize: 16, cursor: 'pointer', fontWeight: 700,
            }}
          >
            −
          </button>
          <span style={{ fontSize: 12, color: COLORS.text2, minWidth: 40, textAlign: 'center' }}>
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={() => setScale((s) => Math.min(2, s + 0.1))}
            style={{
              width: 32, height: 32, background: '#1A3A48', color: COLORS.text2,
              border: 'none', borderRadius: 6, fontSize: 16, cursor: 'pointer', fontWeight: 700,
            }}
          >
            +
          </button>
        </div>
      </div>

      {/* 图例 */}
      {mode === 'status' && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          {Object.entries(STATUS_COLORS).map(([key, color]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: color, display: 'inline-block' }} />
              <span style={{ fontSize: 12, color: COLORS.text2 }}>{STATUS_LABELS[key]}</span>
            </div>
          ))}
        </div>
      )}

      {mode === 'heatmap' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 12, color: COLORS.text2 }}>低</span>
          <div style={{
            width: 120, height: 10, borderRadius: 5,
            background: `linear-gradient(90deg, ${COLORS.heatLow}, ${COLORS.heatMid}, ${COLORS.heatHigh})`,
          }} />
          <span style={{ fontSize: 12, color: COLORS.text2 }}>高</span>
        </div>
      )}

      {/* Canvas 画布 */}
      <div style={{
        background: COLORS.bg, borderRadius: 12,
        border: '1px solid rgba(255,255,255,0.06)',
        overflow: 'auto', maxHeight: '70vh',
      }}>
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onClick={handleClick}
          onMouseLeave={handleMouseLeave}
          style={{ cursor: hoveredTable ? 'pointer' : 'default', display: 'block' }}
        />
      </div>

      {/* Tooltip */}
      {hoveredTable && (
        <div
          style={{
            position: 'fixed',
            left: tooltipPos.x,
            top: tooltipPos.y,
            background: '#112B36',
            border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 10,
            padding: '10px 14px',
            boxShadow: '0 6px 24px rgba(0,0,0,0.5)',
            zIndex: 9999,
            pointerEvents: 'none',
            fontSize: 12,
            color: COLORS.text,
            minWidth: 140,
          }}
        >
          <div style={{ fontWeight: 700, fontSize: 14, color: COLORS.accent, marginBottom: 4 }}>
            {hoveredTable.tableNo} · {hoveredTable.area}
          </div>
          <div>{STATUS_LABELS[hoveredTable.status] || hoveredTable.status} · {hoveredTable.guestCount}/{hoveredTable.seats}人</div>
          {hoveredTable.diningMinutes && <div>⏱ 已就餐 {hoveredTable.diningMinutes} 分钟</div>}
          {hoveredTable.revenueFen && hoveredTable.revenueFen > 0 && (
            <div>💰 消费 ¥{(hoveredTable.revenueFen / 100).toFixed(2)}</div>
          )}
          {hoveredTable.waiterName && <div>👤 {hoveredTable.waiterName}</div>}
          {hoveredTable.turnoverCount && <div>🔄 今日翻台 {hoveredTable.turnoverCount} 次</div>}
        </div>
      )}
    </div>
  );
}
