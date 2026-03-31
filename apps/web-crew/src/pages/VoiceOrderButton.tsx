/**
 * VoiceOrderButton — 服务员端语音点单按钮组件
 *
 * 交互流程：
 *   按下麦克风按钮 → 橙色脉冲 + 实时 transcript 展示
 *   松开 / 再次点击 → 停止录音 → NLU 解析 → 确认面板
 *   确认面板中可调整数量/删除条目 → "加入订单" 调用 onOrderConfirmed
 */

import React, { useCallback, useState } from 'react';
import { useVoiceOrder, ParsedOrderItem } from '../hooks/useVoiceOrder';

// ─── 样式常量 ────────────────────────────────────────────────────────────────

const BTN_SIZE = 80;

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    gap: '12px',
    userSelect: 'none' as const,
  },
  button: (isListening: boolean): React.CSSProperties => ({
    width: BTN_SIZE,
    height: BTN_SIZE,
    borderRadius: '50%',
    border: 'none',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '32px',
    background: isListening
      ? 'linear-gradient(135deg, #FF6B00, #FF9500)'
      : 'linear-gradient(135deg, #FF8C00, #FFB347)',
    boxShadow: isListening
      ? '0 0 0 8px rgba(255, 107, 0, 0.25), 0 4px 16px rgba(255, 107, 0, 0.5)'
      : '0 4px 12px rgba(0,0,0,0.2)',
    transition: 'box-shadow 0.2s ease, transform 0.1s ease',
    transform: isListening ? 'scale(1.05)' : 'scale(1)',
    outline: 'none',
    WebkitTapHighlightColor: 'transparent',
    animation: isListening ? 'txPulse 1.2s ease-in-out infinite' : 'none',
    position: 'relative' as const,
  }),
  transcriptBox: {
    maxWidth: '280px',
    minHeight: '40px',
    padding: '8px 12px',
    background: '#1a1a1a',
    borderRadius: '8px',
    color: '#fff',
    fontSize: '14px',
    lineHeight: 1.5,
    textAlign: 'center' as const,
    whiteSpace: 'pre-wrap' as const,
  },
  errorText: {
    color: '#FF4D4D',
    fontSize: '13px',
    textAlign: 'center' as const,
    maxWidth: '280px',
  },
  processingText: {
    color: '#FF8C00',
    fontSize: '13px',
    textAlign: 'center' as const,
  },
  panel: {
    width: '320px',
    background: '#fff',
    borderRadius: '12px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
    overflow: 'hidden' as const,
  },
  panelHeader: {
    padding: '12px 16px',
    background: '#FF8C00',
    color: '#fff',
    fontWeight: 600 as const,
    fontSize: '15px',
    display: 'flex',
    justifyContent: 'space-between' as const,
    alignItems: 'center' as const,
  },
  panelBody: {
    padding: '8px 0',
  },
  orderItem: {
    display: 'flex',
    alignItems: 'center' as const,
    padding: '10px 16px',
    borderBottom: '1px solid #f0f0f0',
    gap: '8px',
  },
  dishName: {
    flex: 1,
    fontSize: '14px',
    color: '#222',
    fontWeight: 500 as const,
  },
  dishNote: {
    fontSize: '12px',
    color: '#888',
  },
  qtyControl: {
    display: 'flex',
    alignItems: 'center' as const,
    gap: '6px',
  },
  qtyBtn: {
    width: '28px',
    height: '28px',
    borderRadius: '50%',
    border: '1px solid #ddd',
    background: '#f5f5f5',
    cursor: 'pointer',
    fontSize: '16px',
    display: 'flex',
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    lineHeight: 1,
    padding: 0,
    color: '#333',
  },
  qtyNum: {
    minWidth: '24px',
    textAlign: 'center' as const,
    fontSize: '15px',
    fontWeight: 600 as const,
  },
  deleteBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    fontSize: '18px',
    color: '#bbb',
    padding: '0 4px',
  },
  confidenceDot: (confidence: number): React.CSSProperties => ({
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    background:
      confidence >= 0.8 ? '#4CAF50' : confidence >= 0.5 ? '#FF9800' : '#F44336',
    flexShrink: 0,
  }),
  confirmBtn: {
    display: 'block',
    width: 'calc(100% - 32px)',
    margin: '12px 16px',
    padding: '12px',
    background: 'linear-gradient(135deg, #FF8C00, #FFB347)',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontSize: '15px',
    fontWeight: 600 as const,
    cursor: 'pointer',
  },
  emptyHint: {
    padding: '16px',
    color: '#999',
    fontSize: '13px',
    textAlign: 'center' as const,
  },
} as const;

// ─── keyframe 注入（全局一次）────────────────────────────────────────────────

if (typeof document !== 'undefined') {
  const styleId = 'tx-voice-order-styles';
  if (!document.getElementById(styleId)) {
    const el = document.createElement('style');
    el.id = styleId;
    el.textContent = `
      @keyframes txPulse {
        0%   { box-shadow: 0 0 0 4px rgba(255,107,0,0.4), 0 4px 16px rgba(255,107,0,0.5); }
        50%  { box-shadow: 0 0 0 14px rgba(255,107,0,0.1), 0 4px 16px rgba(255,107,0,0.5); }
        100% { box-shadow: 0 0 0 4px rgba(255,107,0,0.4), 0 4px 16px rgba(255,107,0,0.5); }
      }
    `;
    document.head.appendChild(el);
  }
}

// ─── 子组件：确认面板 ─────────────────────────────────────────────────────────

interface ConfirmPanelProps {
  items: ParsedOrderItem[];
  onItemsChange: (items: ParsedOrderItem[]) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmPanel({ items, onItemsChange, onConfirm, onCancel }: ConfirmPanelProps) {
  const updateQty = (index: number, delta: number) => {
    const next = items.map((item, i) =>
      i === index ? { ...item, quantity: Math.max(1, item.quantity + delta) } : item,
    );
    onItemsChange(next);
  };

  const removeItem = (index: number) => {
    onItemsChange(items.filter((_, i) => i !== index));
  };

  return (
    <div style={styles.panel}>
      <div style={styles.panelHeader}>
        <span>识别结果确认</span>
        <button
          onClick={onCancel}
          style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: '18px', padding: 0 }}
          aria-label="关闭"
        >
          ✕
        </button>
      </div>

      <div style={styles.panelBody}>
        {items.length === 0 ? (
          <p style={styles.emptyHint}>未识别到点单内容，请重新语音点单</p>
        ) : (
          items.map((item, i) => (
            <div key={i} style={styles.orderItem}>
              <span style={styles.confidenceDot(item.confidence)} title={`置信度 ${Math.round(item.confidence * 100)}%`} />
              <div style={{ flex: 1 }}>
                <div style={styles.dishName}>{item.dishName}</div>
                {item.note && <div style={styles.dishNote}>{item.note}</div>}
              </div>
              <div style={styles.qtyControl}>
                <button style={styles.qtyBtn} onClick={() => updateQty(i, -1)} aria-label="减少">−</button>
                <span style={styles.qtyNum}>{item.quantity}</span>
                <button style={styles.qtyBtn} onClick={() => updateQty(i, +1)} aria-label="增加">+</button>
              </div>
              <button style={styles.deleteBtn} onClick={() => removeItem(i)} aria-label="删除">🗑</button>
            </div>
          ))
        )}
      </div>

      {items.length > 0 && (
        <button style={styles.confirmBtn} onClick={onConfirm}>
          加入订单（{items.reduce((s, it) => s + it.quantity, 0)} 件）
        </button>
      )}
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export interface VoiceOrderButtonProps {
  tableNo: string;
  menuContext?: string[];
  onOrderConfirmed: (items: ParsedOrderItem[]) => void;
}

export function VoiceOrderButton({ tableNo, menuContext, onOrderConfirmed }: VoiceOrderButtonProps) {
  const [editableOrder, setEditableOrder] = useState<ParsedOrderItem[]>([]);
  const [showPanel, setShowPanel] = useState(false);

  const handleOrderConfirmed = useCallback(
    (items: ParsedOrderItem[]) => {
      onOrderConfirmed(items);
      setShowPanel(false);
      setEditableOrder([]);
    },
    [onOrderConfirmed],
  );

  const {
    isListening,
    isProcessing,
    transcript,
    parsedOrder,
    error,
    startListening,
    stopListening,
    clearOrder,
  } = useVoiceOrder({ tableNo, menuContext, onOrderConfirmed: handleOrderConfirmed });

  // 当解析完成且有结果时，展示确认面板
  React.useEffect(() => {
    if (!isProcessing && parsedOrder.length > 0) {
      setEditableOrder(parsedOrder);
      setShowPanel(true);
    }
  }, [isProcessing, parsedOrder]);

  const handleButtonClick = () => {
    if (showPanel) return;
    if (isListening) {
      stopListening();
    } else {
      setShowPanel(false);
      setEditableOrder([]);
      startListening();
    }
  };

  const handleConfirm = () => {
    handleOrderConfirmed(editableOrder);
    clearOrder();
  };

  const handleCancel = () => {
    setShowPanel(false);
    setEditableOrder([]);
    clearOrder();
  };

  return (
    <div style={styles.container}>
      {/* 麦克风大按钮 */}
      <button
        style={styles.button(isListening)}
        onClick={handleButtonClick}
        aria-label={isListening ? '停止录音' : '开始语音点单'}
        disabled={isProcessing}
      >
        🎤
      </button>

      {/* 状态提示 */}
      {isListening && (
        <div style={styles.transcriptBox}>
          {transcript || '正在聆听…'}
        </div>
      )}

      {isProcessing && (
        <div style={styles.processingText}>正在解析点单…</div>
      )}

      {error && !isListening && !isProcessing && (
        <div style={styles.errorText}>{error}</div>
      )}

      {/* 确认面板 */}
      {showPanel && (
        <ConfirmPanel
          items={editableOrder}
          onItemsChange={setEditableOrder}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}

export default VoiceOrderButton;
