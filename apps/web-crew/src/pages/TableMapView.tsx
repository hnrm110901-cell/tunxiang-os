import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { TurnPredictionAlert } from './TurnPredictionAlert';

interface TableLayout {
  no: string;
  floor: string;
  x: number;
  y: number;
  w: number;
  h: number;
  seats: number;
  shape: 'rect' | 'round';
  status: 'free' | 'occupied' | 'checkout' | 'reserved' | 'cleaning';
  guests?: number;
  orderTime?: string;
  amount?: number;
  orderId?: string;
  minutesElapsed?: number;
}

/* Phase 3-A: 翻台预测数据类型 */
interface TurnPrediction {
  table_no: string;
  estimated_finish_minutes: number;
  confidence: 'high' | 'medium' | 'low';
  suggestion: string | null;
  elapsed_minutes: number;
  avg_dining_minutes: number;
}

const TABLE_COLORS = {
  free:     { bg: '#1A2A1A', border: '#30D158', text: '#30D158' },
  occupied: { bg: '#2A1A0A', border: '#FF6B35', text: '#FF6B35' },
  checkout: { bg: '#2A1F00', border: '#FF9F0A', text: '#FF9F0A' },
  reserved: { bg: '#0A1A2A', border: '#1A9BE8', text: '#1A9BE8' },
  cleaning: { bg: '#1A1A1A', border: '#555',    text: '#555'    },
};

const STATUS_LABEL: Record<string, string> = {
  free: '空闲',
  occupied: '就餐中',
  checkout: '待结账',
  reserved: '预订',
  cleaning: '清洁中',
};

const MOCK_TABLES: TableLayout[] = [
  { no: 'A01', floor: '大厅', x: 0, y: 0, w: 1, h: 1, seats: 4, shape: 'round', status: 'free', guests: 0 },
  { no: 'A02', floor: '大厅', x: 1, y: 0, w: 1, h: 1, seats: 4, shape: 'round', status: 'occupied', guests: 3, orderTime: '14:25', amount: 28500, orderId: 'ord_001', minutesElapsed: 38 },
  { no: 'A03', floor: '大厅', x: 2, y: 0, w: 1, h: 1, seats: 6, shape: 'rect', status: 'occupied', guests: 5, orderTime: '14:10', amount: 52000, orderId: 'ord_002', minutesElapsed: 95 },
  { no: 'A04', floor: '大厅', x: 0, y: 1, w: 1, h: 1, seats: 4, shape: 'round', status: 'reserved', guests: 0 },
  { no: 'A05', floor: '大厅', x: 1, y: 1, w: 1, h: 1, seats: 4, shape: 'round', status: 'free', guests: 0 },
  { no: 'B01', floor: '大厅', x: 2, y: 1, w: 2, h: 1, seats: 8, shape: 'rect', status: 'checkout', guests: 8, amount: 128000, orderId: 'ord_003', minutesElapsed: 62 },
  { no: 'B02', floor: '大厅', x: 0, y: 2, w: 1, h: 1, seats: 4, shape: 'round', status: 'cleaning', guests: 0 },
  { no: 'B03', floor: '大厅', x: 1, y: 2, w: 1, h: 1, seats: 4, shape: 'round', status: 'free', guests: 0 },
  { no: 'VIP1', floor: '包厢', x: 0, y: 0, w: 2, h: 2, seats: 12, shape: 'rect', status: 'occupied', guests: 10, orderTime: '13:30', amount: 380000, orderId: 'ord_004', minutesElapsed: 112 },
  { no: 'VIP2', floor: '包厢', x: 2, y: 0, w: 2, h: 2, seats: 12, shape: 'rect', status: 'free', guests: 0 },
  { no: 'VIP3', floor: '包厢', x: 0, y: 2, w: 2, h: 1, seats: 8, shape: 'rect', status: 'reserved', guests: 0 },
];

const CELL = 54;
const GAP = 4;
const FLOORS = ['大厅', '包厢', '露台'];

const API_BASE = (window as any).__STORE_API_BASE__ || '';
const STORE_ID = (window as any).__STORE_ID__ || '';

function TableCard({
  table,
  onClick,
  turnPrediction,
}: {
  table: TableLayout;
  onClick: () => void;
  turnPrediction?: TurnPrediction | null;
}) {
  const colors = TABLE_COLORS[table.status];
  const isTimeout = (table.minutesElapsed ?? 0) > 90;
  const isOccupied = table.status === 'occupied';
  const isCheckout = table.status === 'checkout';

  // Phase 3-A: 只在 high/medium 置信度时显示翻台预测
  const showTurnPrediction =
    turnPrediction &&
    (turnPrediction.confidence === 'high' || turnPrediction.confidence === 'medium') &&
    (isOccupied || isCheckout);

  const cardStyle: React.CSSProperties = {
    gridColumn: `${table.x + 1} / span ${table.w}`,
    gridRow: `${table.y + 1} / span ${table.h}`,
    background: colors.bg,
    border: `2px solid ${colors.border}`,
    borderRadius: table.shape === 'round' ? '50%' : 10,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    padding: 4,
    boxSizing: 'border-box',
    animation: isTimeout ? 'timeoutPulse 1.5s ease-in-out infinite' : undefined,
    WebkitTapHighlightColor: 'transparent',
    userSelect: 'none',
  };

  return (
    <div style={cardStyle} onClick={onClick}>
      <div style={{ fontSize: 13, fontWeight: 700, color: colors.text, lineHeight: 1.2, textAlign: 'center' }}>
        {table.no}
        {isTimeout && ' 🔴'}
        {isCheckout && ' 💰'}
      </div>
      {(isOccupied || isCheckout) && table.guests ? (
        <>
          <div style={{ fontSize: 11, color: colors.text, opacity: 0.9, textAlign: 'center', marginTop: 2 }}>
            {table.guests}人·¥{((table.amount ?? 0) / 100).toFixed(0)}
          </div>
          {table.minutesElapsed !== undefined && (
            <div style={{ fontSize: 10, color: colors.text, opacity: 0.75, marginTop: 1 }}>
              {table.minutesElapsed}分钟
            </div>
          )}
          {/* Phase 3-A: 翻台预测标签（蓝色小字，仅 high/medium 显示） */}
          {showTurnPrediction && (
            <div style={{
              fontSize: 9,
              color: '#1A9BE8',
              opacity: 0.9,
              marginTop: 1,
              textAlign: 'center',
              lineHeight: 1.2,
            }}>
              ~{turnPrediction!.estimated_finish_minutes}分后
            </div>
          )}
        </>
      ) : (
        <div style={{ fontSize: 11, color: colors.text, opacity: 0.7, marginTop: 2 }}>
          {table.seats}人桌
        </div>
      )}
    </div>
  );
}

export function TableMapView() {
  const [floor, setFloor] = useState('大厅');
  const [tables, setTables] = useState<TableLayout[]>(MOCK_TABLES);
  // Phase 3-A: 翻台预测 Map，key = table_no
  const [turnPredictions, setTurnPredictions] = useState<Record<string, TurnPrediction>>({});
  // Phase 3-A: 翻台提醒 Alert 状态（当前触发提醒的桌台）
  const [alertTableNo, setAlertTableNo] = useState<string | null>(null);
  // 已被忽略的提醒，避免重复弹出
  const [dismissedAlerts, setDismissedAlerts] = useState<Set<string>>(new Set());
  // Mock 候位队列数（实际集成时从候位系统获取）
  const MOCK_QUEUE_COUNT = 3;
  const navigate = useNavigate();

  // Phase 3-A: 拉取就餐桌台的翻台预测
  const fetchTurnPredictions = async (currentTables: TableLayout[]) => {
    if (!API_BASE) return;
    const occupiedTables = currentTables.filter(
      t => (t.status === 'occupied' || t.status === 'checkout') && t.orderId
    );
    const results: Record<string, TurnPrediction> = {};
    await Promise.allSettled(
      occupiedTables.map(async t => {
        try {
          const params = new URLSearchParams({
            store_id: STORE_ID,
            order_id: t.orderId || '',
            seats: String(t.seats),
            elapsed_minutes: String(t.minutesElapsed ?? 0),
          });
          const res = await fetch(
            `${API_BASE}/api/v1/predict/table/${t.no}/turn?${params}`,
          );
          if (!res.ok) return;
          const json = await res.json();
          if (json.ok && json.data) {
            results[t.no] = json.data as TurnPrediction;
          }
        } catch {
          // 预测失败静默降级
        }
      })
    );
    if (Object.keys(results).length > 0) {
      setTurnPredictions(prev => ({ ...prev, ...results }));
      // Phase 3-A: 检查是否有需要提醒的桌台（预计20分钟内翻台，且置信度高/中）
      for (const [tableNo, pred] of Object.entries(results)) {
        if (
          pred.estimated_finish_minutes <= 20 &&
          (pred.confidence === 'high' || pred.confidence === 'medium')
        ) {
          setAlertTableNo(prev => prev || tableNo); // 每次只弹一个
          break;
        }
      }
    }
  };

  useEffect(() => {
    const fetchTables = async () => {
      if (!API_BASE || !STORE_ID) return;
      try {
        const res = await fetch(`${API_BASE}/api/v1/tables/map-layout?store_id=${STORE_ID}`);
        if (res.ok) {
          const json = await res.json();
          if (json.ok && Array.isArray(json.data)) {
            setTables(json.data);
            // Phase 3-A: 拉取桌台数据后顺带获取翻台预测
            fetchTurnPredictions(json.data);
          }
        }
      } catch {
        // 静默降级到 mock 数据
      }
    };

    fetchTables();
    const timer = setInterval(fetchTables, 30000);
    return () => clearInterval(timer);
  }, []);

  const floorTables = tables.filter(t => t.floor === floor);

  const maxCol = floorTables.reduce((m, t) => Math.max(m, t.x + t.w), 1);
  const maxRow = floorTables.reduce((m, t) => Math.max(m, t.y + t.h), 1);

  const gridWidth = maxCol * CELL + (maxCol - 1) * GAP;
  const gridHeight = maxRow * CELL + (maxRow - 1) * GAP;

  const occupiedCount = floorTables.filter(t => t.status === 'occupied' || t.status === 'checkout').length;
  const freeCount = floorTables.filter(t => t.status === 'free').length;
  const totalTurns = tables.filter(t => t.status === 'free' || t.minutesElapsed !== undefined).length;
  const turnRate = occupiedCount > 0 ? (occupiedCount / Math.max(floorTables.length, 1) * 3.5).toFixed(1) : '0.0';

  const handleTableClick = (t: TableLayout) => {
    if (t.status === 'occupied') {
      navigate(`/table-detail?table=${t.no}&order_id=${t.orderId}`);
    } else if (t.status === 'checkout') {
      navigate(`/table-detail?table=${t.no}&order_id=${t.orderId}`);
    } else if (t.status === 'free') {
      navigate(`/open-table?table=${t.no}`);
    }
  };

  return (
    <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#fff', display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @keyframes timeoutPulse {
          0%, 100% { border-color: #FF3B30; box-shadow: 0 0 0 0 rgba(255,59,48,0.4); }
          50% { border-color: #FF6B00; box-shadow: 0 0 0 6px rgba(255,59,48,0); }
        }
      `}</style>

      {/* 顶部标题 + 楼层 Tab */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 16px',
        borderBottom: '1px solid #1a2a33',
        background: '#0B1A20',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => navigate(-1)}
            style={{
              background: 'none',
              border: 'none',
              color: '#fff',
              fontSize: 20,
              cursor: 'pointer',
              minWidth: 48,
              minHeight: 48,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 0,
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            ←
          </button>
          <span style={{ fontSize: 18, fontWeight: 700 }}>桌台地图</span>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {FLOORS.map(f => (
            <button
              key={f}
              onClick={() => setFloor(f)}
              style={{
                minHeight: 36,
                padding: '0 12px',
                borderRadius: 18,
                border: `1.5px solid ${floor === f ? '#FF6B35' : '#2a3a44'}`,
                background: floor === f ? 'rgba(255,107,53,0.15)' : 'transparent',
                color: floor === f ? '#FF6B35' : '#64748b',
                fontSize: 14,
                fontWeight: floor === f ? 700 : 400,
                cursor: 'pointer',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* 图例行 */}
      <div style={{
        display: 'flex',
        gap: 12,
        padding: '10px 16px',
        flexWrap: 'wrap',
        borderBottom: '1px solid #1a2a33',
      }}>
        {(Object.entries(TABLE_COLORS) as [keyof typeof TABLE_COLORS, typeof TABLE_COLORS[keyof typeof TABLE_COLORS]][]).map(([key, clr]) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{
              width: 12,
              height: 12,
              borderRadius: 2,
              background: clr.bg,
              border: `2px solid ${clr.border}`,
              flexShrink: 0,
            }} />
            <span style={{ fontSize: 12, color: '#94a3b8' }}>{STATUS_LABEL[key]}</span>
          </div>
        ))}
      </div>

      {/* 地图区域 */}
      <div style={{ flex: 1, overflowX: 'auto', overflowY: 'auto', padding: 16 }}>
        {floorTables.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#64748b', paddingTop: 60, fontSize: 16 }}>
            该楼层暂无桌台数据
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${maxCol}, ${CELL}px)`,
            gridTemplateRows: `repeat(${maxRow}, ${CELL}px)`,
            gap: GAP,
            width: gridWidth,
            height: gridHeight,
            minWidth: gridWidth,
          }}>
            {floorTables.map(t => (
              <TableCard
                key={t.no}
                table={t}
                onClick={() => handleTableClick(t)}
                turnPrediction={turnPredictions[t.no] || null}
              />
            ))}
          </div>
        )}
      </div>

      {/* 底部统计栏 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-around',
        padding: '12px 16px',
        borderTop: '1px solid #1a2a33',
        background: '#0d1f28',
        gap: 8,
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#FF6B35' }}>{occupiedCount}</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>在台桌数</div>
        </div>
        <div style={{ width: 1, height: 32, background: '#1a2a33' }} />
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#30D158' }}>{freeCount}</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>空台桌数</div>
        </div>
        <div style={{ width: 1, height: 32, background: '#1a2a33' }} />
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#FF9F0A' }}>{turnRate}</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>翻台率</div>
        </div>
        <div style={{ width: 1, height: 32, background: '#1a2a33' }} />
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#1A9BE8' }}>{floorTables.filter(t => t.status === 'reserved').length}</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>预订桌数</div>
        </div>
      </div>

      {/* Phase 3-A: 翻台预测提醒浮动卡 */}
      {alertTableNo && !dismissedAlerts.has(alertTableNo) && (
        <TurnPredictionAlert
          tableNo={alertTableNo}
          estimatedMinutes={turnPredictions[alertTableNo]?.estimated_finish_minutes ?? 0}
          queueCount={MOCK_QUEUE_COUNT}
          onNotifyQueue={() => {
            // TODO: 调用候位通知 API
            setDismissedAlerts(prev => new Set([...prev, alertTableNo]));
            setAlertTableNo(null);
          }}
          onDismiss={() => {
            setDismissedAlerts(prev => new Set([...prev, alertTableNo]));
            setAlertTableNo(null);
          }}
        />
      )}
    </div>
  );
}
