/**
 * 桌台地图视图
 * 使用 Canvas/SVG 渲染餐厅平面图
 * Spin/Tag 已替换为原生实现
 * @module pages/TableManagement/TableMapView
 */

import React, { useEffect, useRef, useCallback, useMemo } from 'react';
import {
  TableCardData,
  TableStatus,
  TableLayout,
  CardField,
} from '../../types/table-card';
import { useTableStore } from '../../stores/tableStore';
import { getStatusText, getStatusColor } from './tableStatusUtils';
import styles from './TableManagement.module.css';

/**
 * 地图视图Props
 */
export interface TableMapViewProps {
  /** 桌台列表 */
  tables: TableCardData[];
  /** 门店ID */
  storeId: string;
  /** 加载中状态 */
  loading?: boolean;
}

/**
 * 地图表格组件
 * 使用Canvas绘制餐厅平面图
 */
const MapCanvas: React.FC<{
  tables: TableCardData[];
  storeId: string;
  width: number;
  height: number;
  onTableClick: (table: TableCardData, field: CardField) => void;
}> = ({ tables, storeId: _storeId, width, height, onTableClick }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  // 鼠标悬停的桌台
  const [hoveredTableNo, setHoveredTableNo] = React.useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = React.useState<{ x: number; y: number } | null>(null);

  // 计算缩放因子（将百分比坐标转换为像素）
  const scale = {
    x: width / 100,
    y: height / 100,
  };

  const padding = 40;
  const drawableWidth = width - padding * 2;
  const drawableHeight = height - padding * 2;

  // 绘制Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // 清空画布
    ctx.fillStyle = '#0B1A20';
    ctx.fillRect(0, 0, width, height);

    // 绘制边框和网格背景
    ctx.strokeStyle = 'rgba(255,255,255,0.10)';
    ctx.lineWidth = 1;
    ctx.strokeRect(padding, padding, drawableWidth, drawableHeight);

    // 绘制网格线（可选）
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    const gridSpacing = 50;
    for (let x = padding; x <= padding + drawableWidth; x += gridSpacing) {
      ctx.beginPath();
      ctx.moveTo(x, padding);
      ctx.lineTo(x, padding + drawableHeight);
      ctx.stroke();
    }
    for (let y = padding; y <= padding + drawableHeight; y += gridSpacing) {
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + drawableWidth, y);
      ctx.stroke();
    }

    // 绘制每张桌台
    tables.forEach((table) => {
      const layout = table.layout;
      const x = padding + (layout.pos_x / 100) * drawableWidth;
      const y = padding + (layout.pos_y / 100) * drawableHeight;
      const tableWidth = (layout.width / 100) * drawableWidth;
      const tableHeight = (layout.height / 100) * drawableHeight;

      const isHovered = hoveredTableNo === table.table_no;
      const statusColor = getStatusColor(table.status);

      // 绘制桌台形状
      ctx.fillStyle = statusColor;
      ctx.globalAlpha = isHovered ? 0.9 : 0.7;
      ctx.strokeStyle = isHovered ? '#FF6B35' : statusColor;
      ctx.lineWidth = isHovered ? 3 : 2;

      if (layout.shape === 'rect') {
        ctx.fillRect(x - tableWidth / 2, y - tableHeight / 2, tableWidth, tableHeight);
        ctx.strokeRect(x - tableWidth / 2, y - tableHeight / 2, tableWidth, tableHeight);
      } else if (layout.shape === 'circle') {
        const radius = Math.min(tableWidth, tableHeight) / 2;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }

      ctx.globalAlpha = 1;

      // 绘制桌号
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 14px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(table.table_no, x, y - 8);

      // 绘制座位数
      ctx.fillStyle = '#ffffff';
      ctx.font = '12px Arial';
      ctx.fillText(`${table.seats}座`, x, y + 8);
    });
  }, [tables, width, height, hoveredTableNo, drawableWidth, drawableHeight]);

  // 处理鼠标移动
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!canvasRef.current) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      let hovered: TableCardData | null = null;

      // 检测鼠标是否悬停在某张桌台上
      for (const table of tables) {
        const layout = table.layout;
        const tableX = padding + (layout.pos_x / 100) * drawableWidth;
        const tableY = padding + (layout.pos_y / 100) * drawableHeight;
        const tableWidth = (layout.width / 100) * drawableWidth;
        const tableHeight = (layout.height / 100) * drawableHeight;

        if (layout.shape === 'rect') {
          const left = tableX - tableWidth / 2;
          const right = tableX + tableWidth / 2;
          const top = tableY - tableHeight / 2;
          const bottom = tableY + tableHeight / 2;

          if (x >= left && x <= right && y >= top && y <= bottom) {
            hovered = table;
            break;
          }
        } else if (layout.shape === 'circle') {
          const radius = Math.min(tableWidth, tableHeight) / 2;
          const distance = Math.sqrt((x - tableX) ** 2 + (y - tableY) ** 2);

          if (distance <= radius) {
            hovered = table;
            break;
          }
        }
      }

      setHoveredTableNo(hovered?.table_no ?? null);
      if (hovered) {
        setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      }
    },
    [tables, drawableWidth, drawableHeight]
  );

  // 处理点击
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!canvasRef.current) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // 查找被点击的桌台
      for (const table of tables) {
        const layout = table.layout;
        const tableX = padding + (layout.pos_x / 100) * drawableWidth;
        const tableY = padding + (layout.pos_y / 100) * drawableHeight;
        const tableWidth = (layout.width / 100) * drawableWidth;
        const tableHeight = (layout.height / 100) * drawableHeight;

        let isClicked = false;

        if (layout.shape === 'rect') {
          const left = tableX - tableWidth / 2;
          const right = tableX + tableWidth / 2;
          const top = tableY - tableHeight / 2;
          const bottom = tableY + tableHeight / 2;
          isClicked = x >= left && x <= right && y >= top && y <= bottom;
        } else if (layout.shape === 'circle') {
          const radius = Math.min(tableWidth, tableHeight) / 2;
          const distance = Math.sqrt((x - tableX) ** 2 + (y - tableY) ** 2);
          isClicked = distance <= radius;
        }

        if (isClicked && table.card_fields.length > 0) {
          // 点击桌台，触发第一个字段的点击事件
          const topField = table.card_fields.sort((a, b) => b.priority - a.priority)[0];
          onTableClick(table, topField);
          break;
        }
      }
    },
    [tables, drawableWidth, drawableHeight, onTableClick]
  );

  // 获取悬停桌台的信息
  const hoveredTable = useMemo(
    () => tables.find((t) => t.table_no === hoveredTableNo),
    [tables, hoveredTableNo]
  );

  return (
    <>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className={styles.mapCanvas}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredTableNo(null)}
        onClick={handleCanvasClick}
        style={{ cursor: hoveredTableNo ? 'pointer' : 'crosshair' }}
      />
      {/* Tooltip（替代 antd Tag 悬停提示） */}
      {hoveredTable && tooltipPos && (
        <div
          ref={tooltipRef}
          style={{
            position: 'absolute',
            left: `${tooltipPos.x + 10}px`,
            top: `${tooltipPos.y + 10}px`,
            background: '#1E2A3A',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 8,
            padding: '8px 12px',
            zIndex: 1000,
            fontSize: 14,
            whiteSpace: 'nowrap',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            pointerEvents: 'none',
            color: '#fff',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 16 }}>
            {hoveredTable.table_no}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.65)', marginBottom: 4 }}>
            {hoveredTable.area} · {hoveredTable.seats} 座
          </div>
          <div>
            {/* 状态标签（替代 antd Tag） */}
            <span style={{
              display: 'inline-block',
              padding: '3px 8px',
              borderRadius: 6,
              background: getStatusColor(hoveredTable.status),
              color: '#fff',
              fontSize: 13,
              fontWeight: 600,
            }}>
              {getStatusText(hoveredTable.status)}
            </span>
          </div>
        </div>
      )}
    </>
  );
};

/**
 * 地图视图组件
 */
export const TableMapView: React.FC<TableMapViewProps> = ({
  tables,
  storeId,
  loading = false,
}) => {
  const { trackFieldClick } = useTableStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = React.useState({ width: 800, height: 500 });

  // 监听容器大小变化
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        setDimensions({
          width: Math.max(clientWidth - 20, 600),
          height: Math.max(clientHeight - 100, 400),
        });
      }
    };

    updateDimensions();
    const resizeObserver = new ResizeObserver(updateDimensions);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => resizeObserver.disconnect();
  }, []);

  const handleTableClick = useCallback(
    (table: TableCardData, field: CardField) => {
      trackFieldClick(storeId, table.table_no, field.key, field.label);
    },
    [storeId, trackFieldClick]
  );

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100%',
          gap: '16px',
          color: 'rgba(255,255,255,0.65)',
          fontSize: 16,
        }}
      >
        <span style={{ fontSize: 24 }}>⟳</span>
        <span>加载中...</span>
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          gap: '16px',
          color: 'rgba(255,255,255,0.45)',
          fontSize: 16,
        }}
      >
        <div style={{ fontSize: '48px', opacity: 0.4 }}>🗺️</div>
        <div>暂无桌台数据</div>
      </div>
    );
  }

  return (
    <div className={styles.mapViewContainer} ref={containerRef}>
      <div className={styles.mapTable}>
        <div className={styles.mapTableCanvas} style={{ position: 'relative' }}>
          <MapCanvas
            tables={tables}
            storeId={storeId}
            width={dimensions.width}
            height={dimensions.height}
            onTableClick={handleTableClick}
          />
        </div>

        {/* 图例（替代 antd Tag 色块） */}
        <div className={styles.mapTableLegend}>
          {[
            { color: '#0F6E56', label: '空台' },
            { color: '#185FA5', label: '用餐中' },
            { color: '#BA7517', label: '已预订' },
            { color: '#A32D2D', label: '待结账' },
            { color: '#555', label: '待清台' },
          ].map(({ color, label }) => (
            <div key={label} className={styles.legendItem}>
              <div
                className={styles.legendColor}
                style={{ backgroundColor: color }}
              />
              <span style={{ color: 'rgba(255,255,255,0.65)', fontSize: 14 }}>{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default TableMapView;
