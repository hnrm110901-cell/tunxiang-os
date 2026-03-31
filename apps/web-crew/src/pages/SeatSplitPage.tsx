/**
 * SeatSplitPage — 按座位分账结算
 * 路由: /seat-split?order_id=xxx
 */
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  accentDim: 'rgba(255,107,53,0.15)',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  paid: '#0F6E56',
};

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

type SplitMode = 'individual' | 'equal' | 'custom';

interface MockSeatItem {
  name: string;
  qty: number;
  price: number;
  seat_no: number | null;
  share_count?: number;
  share_amount?: number;
}

interface MockSeat {
  seat_no: number;
  seat_label: string;
  sub_total: number;
  items: MockSeatItem[];
}

const MOCK_SEATS: MockSeat[] = [
  {
    seat_no: 1, seat_label: '1号', sub_total: 28500,
    items: [
      { name: '宫保鸡丁', qty: 1, price: 3800, seat_no: 1 },
      { name: '鱼香肉丝', qty: 1, price: 3200, seat_no: 1 },
      { name: '佛跳墙（共享）', qty: 1, price: 18800, seat_no: null, share_count: 6, share_amount: 3133 },
    ],
  },
  {
    seat_no: 2, seat_label: '2号', sub_total: 31200,
    items: [
      { name: '红烧肉', qty: 1, price: 5800, seat_no: 2 },
      { name: '佛跳墙（共享）', qty: 1, price: 18800, seat_no: null, share_count: 6, share_amount: 3133 },
    ],
  },
  {
    seat_no: 3, seat_label: '3号', sub_total: 25600,
    items: [
      { name: '清蒸鲈鱼', qty: 1, price: 8800, seat_no: 3 },
      { name: '佛跳墙（共享）', qty: 1, price: 18800, seat_no: null, share_count: 6, share_amount: 3133 },
    ],
  },
  {
    seat_no: 4, seat_label: '4号', sub_total: 22400,
    items: [
      { name: '口水鸡', qty: 1, price: 4800, seat_no: 4 },
      { name: '佛跳墙（共享）', qty: 1, price: 18800, seat_no: null, share_count: 6, share_amount: 3133 },
    ],
  },
  {
    seat_no: 5, seat_label: '5号', sub_total: 19800,
    items: [
      { name: '水煮肉片', qty: 1, price: 3600, seat_no: 5 },
      { name: '佛跳墙（共享）', qty: 1, price: 18800, seat_no: null, share_count: 6, share_amount: 3133 },
    ],
  },
  {
    seat_no: 6, seat_label: '6号', sub_total: 20500,
    items: [
      { name: '夫妻肺片', qty: 1, price: 4200, seat_no: 6 },
      { name: '佛跳墙（共享）', qty: 1, price: 18800, seat_no: null, share_count: 6, share_amount: 3133 },
    ],
  },
];

const TOTAL_FEN = 168000;
const PAID_FEN = 59700;

interface SeatCardProps {
  seat: MockSeat;
  onGenerateCode: (seat_no: number) => void;
  generating: number | null;
  generated: Set<number>;
}

function SeatCard({ seat, onGenerateCode, generating, generated }: SeatCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: 12,
      marginBottom: 10,
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', padding: '14px 16px',
          background: 'transparent', border: 'none', color: C.white,
          cursor: 'pointer', minHeight: 56,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            background: C.accentDim, border: `1px solid ${C.accent}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, fontWeight: 700, color: C.accent,
          }}>
            {seat.seat_no}
          </div>
          <span style={{ fontSize: 17, fontWeight: 600 }}>{seat.seat_label}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: C.accent }}>
            {fen2yuan(seat.sub_total)}
          </span>
          <span style={{ fontSize: 16, color: C.muted }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div style={{ padding: '0 16px 14px' }}>
          {seat.items.map((item, idx) => (
            <div key={idx} style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', padding: '6px 0',
              borderTop: idx === 0 ? `1px solid ${C.border}` : 'none',
              fontSize: 15, color: C.text,
            }}>
              <span style={{ flex: 1 }}>
                {item.name}
                {item.seat_no === null && (
                  <span style={{ fontSize: 13, color: C.muted, marginLeft: 6 }}>
                    ÷{item.share_count}
                  </span>
                )}
              </span>
              <span style={{ color: item.seat_no === null ? C.muted : C.text }}>
                {item.seat_no === null && item.share_amount != null
                  ? fen2yuan(item.share_amount)
                  : fen2yuan(item.price * item.qty)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ padding: '0 16px 14px', display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={() => onGenerateCode(seat.seat_no)}
          disabled={generating === seat.seat_no || generated.has(seat.seat_no)}
          style={{
            padding: '10px 20px', minHeight: 48, borderRadius: 10,
            background: generated.has(seat.seat_no) ? C.paid : C.accent,
            color: C.white, border: 'none', fontSize: 16, fontWeight: 600,
            cursor: generating === seat.seat_no || generated.has(seat.seat_no) ? 'default' : 'pointer',
            opacity: generating === seat.seat_no ? 0.7 : 1,
          }}
        >
          {generating === seat.seat_no ? '生成中...' : generated.has(seat.seat_no) ? '已生成付款码' : '生成付款码'}
        </button>
      </div>
    </div>
  );
}

export function SeatSplitPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const orderId = searchParams.get('order_id') || 'mock-order-001';

  const [splitMode, setSplitMode] = useState<SplitMode>('individual');
  const [generating, setGenerating] = useState<number | null>(null);
  const [generated, setGenerated] = useState<Set<number>>(new Set());

  const handleGenerateCode = async (seatNo: number) => {
    setGenerating(seatNo);
    try {
      await new Promise(r => setTimeout(r, 800));
      setGenerated(prev => new Set(prev).add(seatNo));
    } finally {
      setGenerating(null);
    }
  };

  const handleFullTableCheckout = () => {
    navigate(`/table-ops?order_id=${orderId}`);
  };

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
      {/* 顶部导航 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', borderBottom: `1px solid ${C.border}`,
        background: C.card, position: 'sticky', top: 0, zIndex: 10,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            width: 48, height: 48, background: 'transparent', border: 'none',
            color: C.text, fontSize: 20, cursor: 'pointer', borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          ←
        </button>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>分账结算</div>
          <div style={{ fontSize: 15, color: C.muted, marginTop: 2 }}>A03桌 · {MOCK_SEATS.length}人</div>
        </div>
        <div style={{ width: 48 }} />
      </div>

      {/* 分账方式选择 */}
      <div style={{ padding: '14px 16px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 15, color: C.muted, marginBottom: 10 }}>分账方式</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {([
            { key: 'individual', label: '按座位各付' },
            { key: 'equal', label: '均分' },
            { key: 'custom', label: '自定义' },
          ] as { key: SplitMode; label: string }[]).map(m => (
            <button
              key={m.key}
              onClick={() => setSplitMode(m.key)}
              style={{
                flex: 1, minHeight: 48, borderRadius: 10,
                border: splitMode === m.key ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                background: splitMode === m.key ? C.accentDim : C.card,
                color: splitMode === m.key ? C.accent : C.text,
                fontSize: 16, fontWeight: splitMode === m.key ? 700 : 400,
                cursor: 'pointer',
              }}
            >
              {splitMode === m.key ? '● ' : '○ '}{m.label}
            </button>
          ))}
        </div>
      </div>

      {/* 均分提示 */}
      {splitMode === 'equal' && (
        <div style={{
          margin: '12px 16px 0',
          padding: '12px 16px',
          background: 'rgba(255,107,53,0.1)',
          border: `1px solid ${C.accent}`,
          borderRadius: 10,
          fontSize: 15,
          color: C.text,
        }}>
          均分模式：总金额 {fen2yuan(TOTAL_FEN)} ÷ {MOCK_SEATS.length} 人 ={' '}
          <span style={{ color: C.accent, fontWeight: 700 }}>
            {fen2yuan(Math.ceil(TOTAL_FEN / MOCK_SEATS.length))}
          </span> / 人
        </div>
      )}

      {/* 自定义提示 */}
      {splitMode === 'custom' && (
        <div style={{
          margin: '12px 16px 0',
          padding: '12px 16px',
          background: 'rgba(255,107,53,0.1)',
          border: `1px solid ${C.accent}`,
          borderRadius: 10,
          fontSize: 15,
          color: C.muted,
        }}>
          自定义模式：可在后台选择合并座位进行分组结账
        </div>
      )}

      {/* 座位卡片列表 */}
      <div style={{ padding: '12px 16px 120px' }}>
        {MOCK_SEATS.map(seat => (
          <SeatCard
            key={seat.seat_no}
            seat={seat}
            onGenerateCode={handleGenerateCode}
            generating={generating}
            generated={generated}
          />
        ))}
      </div>

      {/* 底部汇总 + 全桌合单 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: C.card, borderTop: `1px solid ${C.border}`,
        padding: '12px 16px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: 16, color: C.text }}>
            合计: <span style={{ fontWeight: 700, color: C.white }}>{fen2yuan(TOTAL_FEN)}</span>
          </div>
          <div style={{ fontSize: 16, color: C.text }}>
            已付: <span style={{ fontWeight: 700, color: C.green }}>{fen2yuan(PAID_FEN)}</span>
          </div>
        </div>
        <button
          onClick={handleFullTableCheckout}
          style={{
            width: '100%', minHeight: 56, borderRadius: 12,
            background: C.accent, color: C.white,
            border: 'none', fontSize: 18, fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          全桌合单结账
        </button>
      </div>
    </div>
  );
}
