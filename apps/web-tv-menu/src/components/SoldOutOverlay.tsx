import { type CSSProperties } from 'react';

interface SoldOutOverlayProps {
  /** 推荐替代菜品名称(可选) */
  alternativeName?: string;
}

export default function SoldOutOverlay({ alternativeName }: SoldOutOverlayProps) {
  const overlayStyle: CSSProperties = {
    position: 'absolute',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.6)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
    pointerEvents: 'none',
  };

  const stampStyle: CSSProperties = {
    fontSize: 48,
    fontWeight: 900,
    color: 'var(--tx-danger)',
    border: '4px solid var(--tx-danger)',
    borderRadius: 12,
    padding: '8px 24px',
    transform: 'rotate(-15deg)',
    opacity: 0.9,
    textShadow: '0 2px 8px rgba(0,0,0,0.5)',
    letterSpacing: 8,
  };

  const altStyle: CSSProperties = {
    marginTop: 16,
    fontSize: 18,
    color: 'var(--tx-primary)',
    background: 'rgba(255, 107, 44, 0.15)',
    padding: '6px 16px',
    borderRadius: 8,
    transform: 'rotate(-15deg)',
  };

  return (
    <div style={overlayStyle}>
      <div style={stampStyle}>已售罄</div>
      {alternativeName && (
        <div style={altStyle}>推荐: {alternativeName}</div>
      )}
    </div>
  );
}
