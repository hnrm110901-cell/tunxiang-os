/**
 * TableMap — POS端桌位图组件
 *
 * Props:
 *   storeId      — 门店ID
 *   floorNo      — 楼层号（默认 1）
 *   onTableClick — 桌台点击回调 (tableId, status)
 *
 * 功能：
 *   1. 加载布局 GET /api/v1/tables/layout/{storeId}/floor/{floorNo}
 *   2. 加载实时状态 GET /api/v1/tables/status/{storeId}
 *   3. WebSocket 订阅 /api/v1/tables/ws/layout/{storeId}，实时更新桌台颜色
 *   4. SVG 渲染桌位图，颜色编码状态
 *   5. 点击桌台触发回调
 */

import { useEffect, useRef, useState, useCallback } from 'react';

// ─── 类型定义 ───

interface TableNode {
  id: string;
  table_db_id: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  shape: 'rect' | 'circle' | 'oval';
  seats: number;
  label: string;
  rotation: number;
}

interface WallSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface AreaAnnotation {
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  color: string;
}

interface LayoutJson {
  tables: TableNode[];
  walls: WallSegment[];
  areas: AreaAnnotation[];
}

interface TableLayoutData {
  id: string;
  store_id: string;
  floor_no: number;
  floor_name: string;
  canvas_width: number;
  canvas_height: number;
  layout_json: LayoutJson;
  version: number;
}

export interface TableStatus {
  table_db_id: string;
  table_number: string;
  status: 'available' | 'occupied' | 'reserved' | 'cleaning' | 'disabled';
  order_id: string | null;
  order_no: string | null;
  seated_at: string | null;
  seated_duration_min: number | null;
  guest_count: number | null;
  current_amount_fen: number | null;
}

// ─── 状态颜色映射 ───

const STATUS_COLORS: Record<string, { fill: string; stroke: string; text: string }> = {
  available: { fill: '#dcfce7', stroke: '#22c55e', text: '#15803d' },
  occupied:  { fill: '#fee2e2', stroke: '#ef4444', text: '#b91c1c' },
  reserved:  { fill: '#dbeafe', stroke: '#3b82f6', text: '#1d4ed8' },
  cleaning:  { fill: '#fef9c3', stroke: '#eab308', text: '#854d0e' },
  disabled:  { fill: '#f1f5f9', stroke: '#94a3b8', text: '#64748b' },
};

const DEFAULT_COLOR = STATUS_COLORS.available;

// ─── TableMap 组件 ───

interface TableMapProps {
  storeId: string;
  floorNo?: number;
  onTableClick: (tableId: string, status: TableStatus) => void;
  apiBase?: string;
  wsBase?: string;
}

export function TableMap({
  storeId,
  floorNo = 1,
  onTableClick,
  apiBase = '',
  wsBase = '',
}: TableMapProps) {
  const [layout, setLayout] = useState<TableLayoutData | null>(null);
  const [statusMap, setStatusMap] = useState<Map<string, TableStatus>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // ── 加载布局 ──
  const loadLayout = useCallback(async () => {
    try {
      const res = await fetch(
        `${apiBase}/api/v1/tables/layout/${storeId}/floor/${floorNo}`,
        { headers: { 'X-Tenant-ID': '' } }
      );
      if (!res.ok) throw new Error(`布局加载失败 ${res.status}`);
      const json = await res.json();
      if (json.ok) setLayout(json.data as TableLayoutData);
    } catch (err) {
      setError(err instanceof Error ? err.message : '布局加载失败');
    }
  }, [storeId, floorNo, apiBase]);

  // ── 加载实时状态 ──
  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch(
        `${apiBase}/api/v1/tables/status/${storeId}`,
        { headers: { 'X-Tenant-ID': '' } }
      );
      if (!res.ok) throw new Error(`状态加载失败 ${res.status}`);
      const json = await res.json();
      if (json.ok) {
        const map = new Map<string, TableStatus>();
        for (const s of json.data as TableStatus[]) {
          map.set(s.table_db_id, s);
        }
        setStatusMap(map);
      }
    } catch (err) {
      console.warn('桌台状态加载失败:', err);
    }
  }, [storeId, apiBase]);

  // ── 初始加载 ──
  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([loadLayout(), loadStatus()]).finally(() => setLoading(false));
  }, [loadLayout, loadStatus]);

  // ── WebSocket 实时订阅 ──
  useEffect(() => {
    const wsUrl = `${wsBase.replace(/^http/, 'ws')}/api/v1/tables/ws/layout/${storeId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as {
          type: string;
          table_id: string;
          new_status: string;
          table_number?: string;
          order_no?: string;
          guest_count?: number;
          timestamp?: string;
        };

        if (msg.type === 'table_status_update') {
          setStatusMap((prev) => {
            const next = new Map(prev);
            const existing = next.get(msg.table_id);
            if (existing) {
              next.set(msg.table_id, {
                ...existing,
                status: msg.new_status as TableStatus['status'],
                order_no: msg.order_no ?? existing.order_no,
                guest_count: msg.guest_count ?? existing.guest_count,
              });
            } else {
              next.set(msg.table_id, {
                table_db_id: msg.table_id,
                table_number: msg.table_number ?? '',
                status: msg.new_status as TableStatus['status'],
                order_id: null,
                order_no: msg.order_no ?? null,
                seated_at: null,
                seated_duration_min: null,
                guest_count: msg.guest_count ?? null,
                current_amount_fen: null,
              });
            }
            return next;
          });
        }
      } catch {
        // 忽略格式错误的消息
      }
    };

    // 心跳
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 30_000);

    ws.onerror = () => console.warn('桌位图 WebSocket 连接异常');

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [storeId, wsBase]);

  // ── 渲染单个桌子 ──
  const renderTable = (node: TableNode) => {
    const dbId = node.table_db_id ?? node.id;
    const status = statusMap.get(dbId);
    const colors = status ? (STATUS_COLORS[status.status] ?? DEFAULT_COLOR) : DEFAULT_COLOR;
    const statusLabel = status?.status === 'occupied' ? '就餐中' :
                        status?.status === 'reserved' ? '预订' :
                        status?.status === 'cleaning' ? '清台' :
                        status?.status === 'disabled' ? '停用' : '空闲';

    const durationText = status?.seated_duration_min != null
      ? `${status.seated_duration_min}分钟`
      : null;

    const cx = node.x + node.width / 2;
    const cy = node.y + node.height / 2;

    const handleClick = () => {
      if (status) onTableClick(dbId, status);
    };

    const shapeEl =
      node.shape === 'circle' ? (
        <ellipse
          cx={cx}
          cy={cy}
          rx={node.width / 2}
          ry={node.height / 2}
          fill={colors.fill}
          stroke={colors.stroke}
          strokeWidth={2}
        />
      ) : (
        <rect
          x={node.x}
          y={node.y}
          width={node.width}
          height={node.height}
          rx={node.shape === 'oval' ? node.height / 2 : 6}
          fill={colors.fill}
          stroke={colors.stroke}
          strokeWidth={2}
        />
      );

    return (
      <g
        key={node.id}
        transform={node.rotation ? `rotate(${node.rotation} ${cx} ${cy})` : undefined}
        onClick={handleClick}
        className="cursor-pointer"
        style={{ userSelect: 'none' }}
      >
        {shapeEl}
        {/* 桌号 */}
        <text
          x={cx}
          y={node.shape === 'circle' ? cy - 8 : cy - 8}
          textAnchor="middle"
          fontSize={12}
          fontWeight="600"
          fill={colors.text}
        >
          {node.label}
        </text>
        {/* 状态 */}
        <text
          x={cx}
          y={node.shape === 'circle' ? cy + 8 : cy + 8}
          textAnchor="middle"
          fontSize={10}
          fill={colors.text}
        >
          {statusLabel}
        </text>
        {/* 就餐时长（occupied 时显示） */}
        {durationText && (
          <text
            x={cx}
            y={cy + 22}
            textAnchor="middle"
            fontSize={9}
            fill={colors.text}
          >
            {durationText}
          </text>
        )}
      </g>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        加载桌位图中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        {error}
      </div>
    );
  }

  if (!layout) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        暂无楼层布局，请先在总部后台配置
      </div>
    );
  }

  const { canvas_width: cw, canvas_height: ch, layout_json: lj } = layout;

  return (
    <div className="w-full overflow-auto bg-white rounded-lg border border-gray-200 shadow-sm">
      {/* 楼层标题 */}
      <div className="px-4 py-2 border-b border-gray-100 flex items-center gap-3">
        <span className="font-semibold text-gray-700">{layout.floor_name || `${floorNo}楼`}</span>
        <span className="text-sm text-gray-400">v{layout.version}</span>
        {/* 图例 */}
        <div className="ml-auto flex items-center gap-4 text-xs">
          {Object.entries(STATUS_COLORS).map(([key, c]) => (
            <span key={key} className="flex items-center gap-1">
              <span
                className="inline-block w-3 h-3 rounded-sm border"
                style={{ background: c.fill, borderColor: c.stroke }}
              />
              {key === 'available' ? '空闲' :
               key === 'occupied'  ? '就餐中' :
               key === 'reserved'  ? '预订' :
               key === 'cleaning'  ? '清台' : '停用'}
            </span>
          ))}
        </div>
      </div>

      {/* SVG 画布 */}
      <svg
        viewBox={`0 0 ${cw} ${ch}`}
        width="100%"
        style={{ maxHeight: '70vh' }}
        className="block"
      >
        <rect width={cw} height={ch} fill="#f8fafc" />

        {/* 区域标注 */}
        {lj.areas.map((area, i) => (
          <g key={`area-${i}`}>
            <rect
              x={area.x}
              y={area.y}
              width={area.width}
              height={area.height}
              fill={area.color || '#e2e8f0'}
              fillOpacity={0.3}
              stroke={area.color || '#cbd5e1'}
              strokeWidth={1}
              strokeDasharray="6 3"
              rx={4}
            />
            <text
              x={area.x + 8}
              y={area.y + 18}
              fontSize={13}
              fill={area.color || '#64748b'}
              fontWeight="500"
            >
              {area.label}
            </text>
          </g>
        ))}

        {/* 墙体 */}
        {lj.walls.map((wall, i) => (
          <line
            key={`wall-${i}`}
            x1={wall.x1}
            y1={wall.y1}
            x2={wall.x2}
            y2={wall.y2}
            stroke="#334155"
            strokeWidth={4}
            strokeLinecap="round"
          />
        ))}

        {/* 桌台 */}
        {lj.tables.map(renderTable)}
      </svg>
    </div>
  );
}

export default TableMap;
