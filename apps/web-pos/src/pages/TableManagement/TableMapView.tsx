/**
 * æºè½æ¡å°å°å¾è§å¾
 * ä½¿ç¨Canvas/SVGæ¸²æé¤åå¹³é¢å¾
 * @module pages/TableManagement/TableMapView
 */

import React, { useEffect, useRef, useCallback, useMemo } from 'react';
import { Spin, Tag } from 'antd';
import {
  TableCardData,
  TableStatus,
  TableLayout,
  CardField,
} from '../../types/table-card';
import { useTableStore } from '../../stores/tableStore';
import styles from './TableManagement.module.css';

/**
 * å°å¾è§å¾Props
 */
export interface TableMapViewProps {
  /** æ¡å°åè¡¨ */
  tables: TableCardData[];
  /** é¨åºID */
  storeId: string;
  /** å è½½ä¸­ç¶æ */
  loading?: boolean;
}

/**
 * è·åç¶æå¯¹åºçå¡«åè²
 */
const getStatusColor = (status: TableStatus): string => {
  const colorMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: '#52c41a',
    [TableStatus.Dining]: '#1890ff',
    [TableStatus.Reserved]: '#faad14',
    [TableStatus.PendingCheckout]: '#ff4d4f',
    [TableStatus.PendingCleanup]: '#d9d9d9',
  };
  return colorMap[status];
};

/**
 * è·åç¶ææ¾ç¤ºææ¬
 */
const getStatusText = (status: TableStatus): string => {
  const statusMap: Record<TableStatus, string> = {
    [TableStatus.Empty]: 'ç©ºå°',
    [TableStatus.Dining]: 'ç¨é¤ä¸­',
    [TableStatus.Reserved]: 'å·²é¢è®¢',
    [TableStatus.PendingCheckout]: 'å¾ç»è´¦',
    [TableStatus.PendingCleanup]: 'å¾æ¸å°',
  };
  return statusMap[status];
};

/**
 * å°å¾è¡¨æ ¼ç»ä»¶
 * ä½¿ç¨Canvasç»å¶é¤åå¹³é¢å¾
 */
const MapCanvas: React.FC<{
  tables: TableCardData[];
  storeId: string;
  width: number;
  height: number;
  onTableClick: (table: TableCardData, field: CardField) => void;
}> = ({ tables, storeId, width, height, onTableClick }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  // é¼ æ æ¬åçæ¡å°
  const [hoveredTableNo, setHoveredTableNo] = React.useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = React.useState<{ x: number; y: number } | null>(null);

  // è®¡ç®ç¼©æ¾å å­ï¼å°ç¾åæ¯åæ è½¬æ¢ä¸ºåç´ ï¼
  const scale = {
    x: width / 100,
    y: height / 100,
  };

  const padding = 40;
  const drawableWidth = width - padding * 2;
  const drawableHeight = height - padding * 2;

  // ç»å¶Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // æ¸ç©ºç»å¸
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    // ç»å¶è¾¹æ¡åç½æ ¼èæ¯
    ctx.strokeStyle = '#d9d9d9';
    ctx.lineWidth = 1;
    ctx.strokeRect(padding, padding, drawableWidth, drawableHeight);

    // ç»å¶ç½æ ¼çº¿ï¼å¯éï¼
    ctx.strokeStyle = '#f0f0f0';
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

    // ç»å¶æ¯å¼ æ¡å°
    tables.forEach((table) => {
      const layout = table.layout;
      const x = padding + (layout.pos_x / 100) * drawableWidth;
      const y = padding + (layout.pos_y / 100) * drawableHeight;
      const tableWidth = (layout.width / 100) * drawableWidth;
      const tableHeight = (layout.height / 100) * drawableHeight;

      const isHovered = hoveredTableNo === table.table_no;
      const statusColor = getStatusColor(table.status);

      // ç»å¶æ¡å°å½¢ç¶
      ctx.fillStyle = statusColor;
      ctx.globalAlpha = isHovered ? 0.9 : 0.7;
      ctx.strokeStyle = statusColor;
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

      // ç»å¶æ¡å·
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 14px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(table.table_no, x, y - 8);

      // ç»å¶åº§ä½æ°
      ctx.fillStyle = '#ffffff';
      ctx.font = '12px Arial';
      ctx.fillText(`${table.seats}åº§`, x, y + 8);
    });
  }, [tables, width, height, hoveredTableNo, drawableWidth, drawableHeight]);

  // å¤çé¼ æ ç§»å¨
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!canvasRef.current) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      let hovered: TableCardData | null = null;

      // æ£æµé¼ æ æ¯å¦æ¬åå¨æå¼ æ¡å°ä¸
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

  // å¤çç¹å»
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!canvasRef.current) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // æ¥æ¾è¢«ç¹å»çæ¡å°
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
          // ç¹å»æ¡å°ï¼è§¦åç¬¬ä¸ä¸ªå­æ®µçç¹å»äºä»¶
          const topField = table.card_fields.sort((a, b) => b.priority - a.priority)[0];
          onTableClick(table, topField);
          break;
        }
      }
    },
    [tables, drawableWidth, drawableHeight, onTableClick]
  );

  // è·åæ¬åæ¡å°çä¿¡æ¯
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
      {hoveredTable && tooltipPos && (
        <div
          ref={tooltipRef}
          style={{
            position: 'absolute',
            left: `${tooltipPos.x + 10}px`,
            top: `${tooltipPos.y + 10}px`,
            background: 'white',
            border: '1px solid #d9d9d9',
            borderRadius: '4px',
            padding: '8px 12px',
            zIndex: 1000,
            fontSize: '12px',
            whiteSpace: 'nowrap',
            boxShadow: '0 3px 6px rgba(0, 0, 0, 0.15)',
            pointerEvents: 'none',
          }}
        >
          <div style={{ fontWeight: '600', marginBottom: '4px' }}>
            {hoveredTable.table_no}
          </div>
          <div style={{ color: '#595959', marginBottom: '4px' }}>
            {hoveredTable.area} Â· {hoveredTable.seats} åº§
          </div>
          <div>
            <Tag color={getStatusColor(hoveredTable.status)}>
              {getStatusText(hoveredTable.status)}
            </Tag>
          </div>
        </div>
      )}
    </>
  );
};

/**
 * å°å¾è§å¾ç»ä»¶
 */
export const TableMapView: React.FC<TableMapViewProps> = ({
  tables,
  storeId,
  loading = false,
}) => {
  const { trackFieldClick } = useTableStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = React.useState({ width: 800, height: 500 });

  // çå¬å®¹å¨å¤§å°åå
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
        }}
      >
        <Spin />
        <span>å è½½ä¸­...</span>
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
          color: '#595959',
        }}
      >
        <div style={{ fontSize: '48px', opacity: 0.4 }}>ðºï¸</div>
        <div>ææ æ¡å°æ°æ®</div>
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

        {/* å¾ä¾ */}
        <div className={styles.mapTableLegend}>
          <div className={styles.legendItem}>
            <div
              className={styles.legendColor}
              style={{ backgroundColor: '#52c41a' }}
            />
            <span>ç©ºå°</span>
          </div>
          <div className={styles.legendItem}>
            <div
              className={styles.legendColor}
              style={{ backgroundColor: '#1890ff' }}
            />
            <span>ç¨é¤ä¸­</span>
          </div>
          <div className={styles.legendItem}>
            <div
              className={styles.legendColor}
              style={{ backgroundColor: '#faad14' }}
            />
            <span>å·²é¢è®¢</span>
          </div>
          <div className={styles.legendItem}>
            <div
              className={styles.legendColor}
              style={{ backgroundColor: '#ff4d4f' }}
            />
            <span>å¾ç»è´¦</span>
          </div>
          <div className={styles.legendItem}>
            <div
              className={styles.legendColor}
              style={{ backgroundColor: '#d9d9d9' }}
            />
            <span>å¾æ¸å°</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TableMapView;
