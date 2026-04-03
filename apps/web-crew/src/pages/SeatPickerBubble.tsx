/**
 * SeatPickerBubble — 点单时为菜品选择归属座位的浮层组件
 */
import { useEffect, useRef } from 'react';

const C = {
  bg: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  accentDim: 'rgba(255,107,53,0.18)',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  shared: '#334155',
};

interface SeatInfo {
  seat_no: number;
  seat_label: string;
}

interface Props {
  seats: SeatInfo[];
  currentSeatNo: number | null;
  onSelect: (seatNo: number | null) => void;
  onClose: () => void;
}

export function SeatPickerBubble({ seats, currentSeatNo, onSelect, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent | TouchEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('touchstart', handler);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('touchstart', handler);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{
        position: 'absolute',
        zIndex: 200,
        background: C.bg,
        border: `1px solid ${C.border}`,
        borderRadius: 14,
        padding: '14px 12px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        minWidth: 220,
      }}
    >
      <div style={{ fontSize: 15, color: C.muted, marginBottom: 10 }}>选择归属座位</div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {/* 全桌共享 */}
        <button
          onClick={() => { onSelect(null); onClose(); }}
          style={{
            width: 60, height: 60, borderRadius: 10, flexShrink: 0,
            border: currentSeatNo === null ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
            background: currentSeatNo === null ? C.accentDim : C.shared,
            color: currentSeatNo === null ? C.accent : C.text,
            fontSize: 13, fontWeight: 600, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            textAlign: 'center', lineHeight: 1.3,
          }}
        >
          全桌
        </button>

        {seats.map(seat => {
          const isActive = currentSeatNo === seat.seat_no;
          return (
            <button
              key={seat.seat_no}
              onClick={() => { onSelect(seat.seat_no); onClose(); }}
              style={{
                width: 60, height: 60, borderRadius: '50%', flexShrink: 0,
                border: isActive ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                background: isActive ? C.accentDim : C.bg,
                color: isActive ? C.accent : C.text,
                fontSize: 15, fontWeight: isActive ? 700 : 400,
                cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              {seat.seat_label}
            </button>
          );
        })}
      </div>

      <button
        onClick={onClose}
        style={{
          width: '100%', minHeight: 44, marginTop: 12, borderRadius: 8,
          background: 'transparent', border: `1px solid ${C.border}`,
          color: C.muted, fontSize: 15, cursor: 'pointer',
        }}
      >
        取消
      </button>
    </div>
  );
}
