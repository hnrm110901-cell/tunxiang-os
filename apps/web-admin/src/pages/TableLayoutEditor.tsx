/**
 * TableLayoutEditor — 总部后台桌位图形化编辑器
 *
 * 功能：
 *   1. SVG 画布，支持点击添加桌子（选择形状：方/圆）
 *   2. 拖拽移动桌子位置
 *   3. 选中后右侧属性面板：修改桌号/座位数/形状
 *   4. 保存按钮：PUT /api/v1/tables/layout/{storeId}/floor/{floorNo}
 *   5. 纯 SVG onMouseDown/onMouseMove/onMouseUp 实现拖拽，无依赖
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型 ───

type Shape = 'rect' | 'circle' | 'oval';

interface TableNode {
  id: string;
  table_db_id: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  shape: Shape;
  seats: number;
  label: string;
  rotation: number;
}

interface WallSegment { x1: number; y1: number; x2: number; y2: number }
interface AreaAnnotation { x: number; y: number; width: number; height: number; label: string; color: string }

interface LayoutJson {
  tables: TableNode[];
  walls: WallSegment[];
  areas: AreaAnnotation[];
}

// ─── Props ───

interface TableLayoutEditorProps {
  storeId: string;
  tenantId: string;
  operatorId: string;
  floorNo?: number;
  floorName?: string;
  apiBase?: string;
}

// ─── 常量 ───

const CANVAS_W = 1200;
const CANVAS_H = 800;
const DEFAULT_TABLE_W = 80;
const DEFAULT_TABLE_H = 70;

function genId() {
  return `tbl-${Math.random().toString(36).slice(2, 9)}`;
}

// ─── 编辑器主体 ───

export function TableLayoutEditor({
  storeId,
  tenantId,
  operatorId,
  floorNo = 1,
  floorName: initialFloorName = '一楼大厅',
  apiBase = '',
}: TableLayoutEditorProps) {
  const [tables, setTables] = useState<TableNode[]>([]);
  const [walls] = useState<WallSegment[]>([]);
  const [areas] = useState<AreaAnnotation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addShape, setAddShape] = useState<Shape>('rect');
  const [floorName, setFloorName] = useState(initialFloorName);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // 拖拽状态
  const dragRef = useRef<{
    id: string;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
  } | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);

  // ── 加载已有布局 ──
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(
          `${apiBase}/api/v1/tables/layout/${storeId}/floor/${floorNo}`,
          { headers: { 'X-Tenant-ID': tenantId } }
        );
        if (res.ok) {
          const json = await res.json();
          if (json.ok && json.data) {
            const lj: LayoutJson = json.data.layout_json;
            setTables(lj.tables ?? []);
            setFloorName(json.data.floor_name || initialFloorName);
          }
        }
      } catch {
        // 新楼层，无需处理
      } finally {
        setLoading(false);
      }
    })();
  }, [storeId, floorNo, tenantId, apiBase, initialFloorName]);

  // ── SVG 坐标转换 ──
  const getSvgPoint = useCallback((clientX: number, clientY: number): { x: number; y: number } => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    const scaleX = CANVAS_W / rect.width;
    const scaleY = CANVAS_H / rect.height;
    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY,
    };
  }, []);

  // ── 点击画布空白区域：添加桌子 ──
  const handleSvgClick = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (e.target !== svgRef.current && (e.target as Element).tagName === 'rect' && (e.target as Element).getAttribute('data-bg')) {
      // 点击背景矩形
    } else if (e.target !== svgRef.current) {
      return; // 点击了桌子元素，不添加
    }
    const { x, y } = getSvgPoint(e.clientX, e.clientY);
    const newTable: TableNode = {
      id: genId(),
      table_db_id: null,
      x: x - DEFAULT_TABLE_W / 2,
      y: y - DEFAULT_TABLE_H / 2,
      width: DEFAULT_TABLE_W,
      height: addShape === 'rect' ? DEFAULT_TABLE_H : DEFAULT_TABLE_W,
      shape: addShape,
      seats: 4,
      label: `T${tables.length + 1}`,
      rotation: 0,
    };
    setTables((prev) => [...prev, newTable]);
    setSelectedId(newTable.id);
  }, [addShape, tables.length, getSvgPoint]);

  // ── 拖拽开始 ──
  const handleTableMouseDown = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      setSelectedId(id);
      const { x, y } = getSvgPoint(e.clientX, e.clientY);
      const table = tables.find((t) => t.id === id)!;
      dragRef.current = { id, startX: x, startY: y, origX: table.x, origY: table.y };
    },
    [tables, getSvgPoint]
  );

  // ── 拖拽移动 ──
  const handleSvgMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!dragRef.current) return;
      const { id, startX, startY, origX, origY } = dragRef.current;
      const { x, y } = getSvgPoint(e.clientX, e.clientY);
      const dx = x - startX;
      const dy = y - startY;
      setTables((prev) =>
        prev.map((t) =>
          t.id === id
            ? {
                ...t,
                x: Math.max(0, Math.min(CANVAS_W - t.width, origX + dx)),
                y: Math.max(0, Math.min(CANVAS_H - t.height, origY + dy)),
              }
            : t
        )
      );
    },
    [getSvgPoint]
  );

  // ── 拖拽结束 ──
  const handleSvgMouseUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  // ── 删除选中桌子 ──
  const deleteSelected = useCallback(() => {
    if (!selectedId) return;
    setTables((prev) => prev.filter((t) => t.id !== selectedId));
    setSelectedId(null);
  }, [selectedId]);

  // ── 属性面板更新 ──
  const updateSelected = useCallback((patch: Partial<TableNode>) => {
    setTables((prev) =>
      prev.map((t) => (t.id === selectedId ? { ...t, ...patch } : t))
    );
  }, [selectedId]);

  // ── 保存布局 ──
  const saveLayout = useCallback(async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const body = {
        floor_name: floorName,
        layout_json: { tables, walls, areas },
        published_by: operatorId,
      };
      const res = await fetch(
        `${apiBase}/api/v1/tables/layout/${storeId}/floor/${floorNo}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-ID': tenantId,
          },
          body: JSON.stringify(body),
        }
      );
      const json = await res.json();
      if (json.ok) {
        setSaveMsg(`保存成功（版本 v${json.data.version}）`);
      } else {
        setSaveMsg(`保存失败: ${json.error?.message ?? '未知错误'}`);
      }
    } catch (err) {
      setSaveMsg(`保存失败: ${err instanceof Error ? err.message : '网络错误'}`);
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 4000);
    }
  }, [floorName, tables, walls, areas, storeId, floorNo, tenantId, operatorId, apiBase]);

  const selectedTable = tables.find((t) => t.id === selectedId) ?? null;

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-gray-400">加载中…</div>;
  }

  return (
    <div className="flex gap-4 h-full">
      {/* ── 左侧工具栏 + 画布 ── */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* 工具栏 */}
        <div className="flex items-center gap-3 flex-wrap bg-white border border-gray-200 rounded-lg px-4 py-2 shadow-sm">
          <span className="text-sm font-medium text-gray-600">添加桌型：</span>
          {(['rect', 'circle', 'oval'] as Shape[]).map((s) => (
            <button
              key={s}
              onClick={() => setAddShape(s)}
              className={`px-3 py-1 rounded text-sm border transition ${
                addShape === s
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-blue-400'
              }`}
            >
              {s === 'rect' ? '方形' : s === 'circle' ? '圆形' : '椭圆'}
            </button>
          ))}
          <span className="text-xs text-gray-400 ml-2">点击画布空白处添加桌子</span>
          <div className="ml-auto flex items-center gap-2">
            <input
              type="text"
              value={floorName}
              onChange={(e) => setFloorName(e.target.value)}
              placeholder="楼层名称"
              className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
            />
            {saveMsg && (
              <span
                className={`text-xs ${
                  saveMsg.startsWith('保存成功') ? 'text-green-600' : 'text-red-500'
                }`}
              >
                {saveMsg}
              </span>
            )}
            <button
              onClick={saveLayout}
              disabled={saving}
              className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {saving ? '保存中…' : '保存布局'}
            </button>
          </div>
        </div>

        {/* SVG 画布 */}
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-auto">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
            width="100%"
            style={{ maxHeight: '65vh', cursor: 'crosshair' }}
            onClick={handleSvgClick}
            onMouseMove={handleSvgMouseMove}
            onMouseUp={handleSvgMouseUp}
            onMouseLeave={handleSvgMouseUp}
          >
            {/* 背景 */}
            <rect
              data-bg="1"
              width={CANVAS_W}
              height={CANVAS_H}
              fill="#f8fafc"
            />

            {/* 网格 */}
            <defs>
              <pattern id="grid" width={40} height={40} patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" strokeWidth="0.5" />
              </pattern>
            </defs>
            <rect width={CANVAS_W} height={CANVAS_H} fill="url(#grid)" />

            {/* 区域标注 */}
            {areas.map((area, i) => (
              <g key={`area-${i}`}>
                <rect
                  x={area.x} y={area.y}
                  width={area.width} height={area.height}
                  fill={area.color} fillOpacity={0.15}
                  stroke={area.color} strokeWidth={1} strokeDasharray="6 3"
                  rx={4}
                />
                <text x={area.x + 8} y={area.y + 18} fontSize={13} fill={area.color}>
                  {area.label}
                </text>
              </g>
            ))}

            {/* 墙体 */}
            {walls.map((wall, i) => (
              <line
                key={`wall-${i}`}
                x1={wall.x1} y1={wall.y1} x2={wall.x2} y2={wall.y2}
                stroke="#334155" strokeWidth={4} strokeLinecap="round"
              />
            ))}

            {/* 桌台 */}
            {tables.map((node) => {
              const cx = node.x + node.width / 2;
              const cy = node.y + node.height / 2;
              const isSelected = node.id === selectedId;
              const fill = isSelected ? '#eff6ff' : '#f1f5f9';
              const stroke = isSelected ? '#3b82f6' : '#94a3b8';

              return (
                <g
                  key={node.id}
                  transform={node.rotation ? `rotate(${node.rotation} ${cx} ${cy})` : undefined}
                  onMouseDown={(e) => handleTableMouseDown(e, node.id)}
                  style={{ cursor: 'grab', userSelect: 'none' }}
                >
                  {node.shape === 'circle' ? (
                    <ellipse
                      cx={cx} cy={cy}
                      rx={node.width / 2} ry={node.height / 2}
                      fill={fill} stroke={stroke} strokeWidth={isSelected ? 2.5 : 1.5}
                    />
                  ) : (
                    <rect
                      x={node.x} y={node.y}
                      width={node.width} height={node.height}
                      rx={node.shape === 'oval' ? node.height / 2 : 6}
                      fill={fill} stroke={stroke} strokeWidth={isSelected ? 2.5 : 1.5}
                    />
                  )}
                  <text x={cx} y={cy - 6} textAnchor="middle" fontSize={12} fontWeight="600" fill="#334155">
                    {node.label}
                  </text>
                  <text x={cx} y={cy + 10} textAnchor="middle" fontSize={10} fill="#64748b">
                    {node.seats}座
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>

      {/* ── 右侧属性面板 ── */}
      <div className="w-56 flex-shrink-0">
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            {selectedTable ? '桌台属性' : '选中桌台后编辑'}
          </h3>

          {selectedTable ? (
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">桌号标签</label>
                <input
                  type="text"
                  value={selectedTable.label}
                  onChange={(e) => updateSelected({ label: e.target.value })}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">座位数</label>
                <input
                  type="number"
                  min={1}
                  max={99}
                  value={selectedTable.seats}
                  onChange={(e) => updateSelected({ seats: parseInt(e.target.value) || 1 })}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">形状</label>
                <select
                  value={selectedTable.shape}
                  onChange={(e) => updateSelected({ shape: e.target.value as Shape })}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                >
                  <option value="rect">方形</option>
                  <option value="circle">圆形</option>
                  <option value="oval">椭圆</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">宽度 (px)</label>
                <input
                  type="number"
                  min={40}
                  max={300}
                  value={Math.round(selectedTable.width)}
                  onChange={(e) => updateSelected({ width: parseInt(e.target.value) || 80 })}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">高度 (px)</label>
                <input
                  type="number"
                  min={40}
                  max={300}
                  value={Math.round(selectedTable.height)}
                  onChange={(e) => updateSelected({ height: parseInt(e.target.value) || 70 })}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">旋转角度</label>
                <input
                  type="number"
                  min={0}
                  max={359}
                  value={selectedTable.rotation}
                  onChange={(e) => updateSelected({ rotation: parseInt(e.target.value) || 0 })}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                />
              </div>
              <button
                onClick={deleteSelected}
                className="w-full mt-2 px-3 py-1.5 bg-red-50 text-red-600 border border-red-200 rounded text-sm hover:bg-red-100 transition"
              >
                删除桌台
              </button>
            </div>
          ) : (
            <p className="text-xs text-gray-400">
              点击画布空白处添加桌子，点击已有桌子进行编辑。
            </p>
          )}
        </div>

        {/* 统计 */}
        <div className="mt-3 bg-white border border-gray-200 rounded-lg shadow-sm p-4">
          <div className="text-xs text-gray-500 space-y-1">
            <div className="flex justify-between">
              <span>桌台总数</span>
              <span className="font-medium text-gray-700">{tables.length}</span>
            </div>
            <div className="flex justify-between">
              <span>总座位数</span>
              <span className="font-medium text-gray-700">
                {tables.reduce((s, t) => s + t.seats, 0)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default TableLayoutEditor;
