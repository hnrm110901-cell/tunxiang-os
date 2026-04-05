/**
 * SpecSelectorSheet -- 多规格选择弹层
 *
 * 当菜品含有 specifications（大份/中份/小份/半份）时，
 * 点击菜品弹出此弹层，选择规格 + 数量后加入购物车。
 *
 * POS 暗色主题 (#0B1A20 / #112228 / #FF6B2C)
 */
import { useState } from 'react';
import type { DishSpecification } from '../api/menuApi';

export interface SpecSelectorSheetProps {
  visible: boolean;
  dish: {
    id: string;
    name: string;
    imageUrl?: string;
    priceFen: number;
    specifications: DishSpecification[];
  };
  onConfirm: (specId: string, specName: string, priceFen: number, quantity: number) => void;
  onClose: () => void;
}

const fen2yuan = (fen: number) => `\u00A5${(fen / 100).toFixed(2)}`;

export function SpecSelectorSheet({ visible, dish, onConfirm, onClose }: SpecSelectorSheetProps) {
  const [selectedSpecId, setSelectedSpecId] = useState<string>(
    dish.specifications[0]?.spec_id ?? '',
  );
  const [quantity, setQuantity] = useState(1);

  if (!visible) return null;

  const selectedSpec = dish.specifications.find((s) => s.spec_id === selectedSpecId);
  const unitPrice = selectedSpec?.price_fen ?? dish.priceFen;
  const totalFen = unitPrice * quantity;

  const handleConfirm = () => {
    if (!selectedSpec) return;
    onConfirm(selectedSpec.spec_id, selectedSpec.name, selectedSpec.price_fen, quantity);
    onClose();
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
      }}
    >
      {/* backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(0,0,0,0.55)',
        }}
      />

      {/* sheet */}
      <div
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 480,
          background: '#112228',
          borderRadius: '16px 16px 0 0',
          padding: '20px 20px 28px',
          color: '#fff',
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
        }}
      >
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18 }}>
          {dish.imageUrl && (
            <img
              src={dish.imageUrl}
              alt={dish.name}
              style={{ width: 64, height: 64, borderRadius: 8, objectFit: 'cover' }}
            />
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.3 }}>{dish.name}</div>
            <div style={{ fontSize: 15, color: '#999', marginTop: 4 }}>
              {dish.specifications.length > 0 ? '请选择规格' : fen2yuan(dish.priceFen)}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#666',
              fontSize: 24,
              cursor: 'pointer',
              padding: 4,
              lineHeight: 1,
            }}
          >
            &#x2715;
          </button>
        </div>

        {/* spec buttons */}
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 15, color: '#aaa', marginBottom: 8 }}>规格</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {dish.specifications.map((spec) => {
              const isSelected = spec.spec_id === selectedSpecId;
              return (
                <button
                  key={spec.spec_id}
                  type="button"
                  onClick={() => setSelectedSpecId(spec.spec_id)}
                  style={{
                    padding: '10px 18px',
                    borderRadius: 8,
                    border: isSelected ? '2px solid #FF6B2C' : '2px solid #2a3a42',
                    background: isSelected ? 'rgba(255,107,44,0.12)' : '#0B1A20',
                    color: isSelected ? '#FF6B2C' : '#ccc',
                    fontSize: 16,
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 2,
                    minWidth: 80,
                    fontFamily: 'inherit',
                  }}
                >
                  <span>{spec.name}</span>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>
                    {fen2yuan(spec.price_fen)}
                  </span>
                  {spec.is_half && (
                    <span style={{ fontSize: 11, color: '#52c41a', marginTop: 1 }}>半份</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* quantity selector */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 20,
          }}
        >
          <span style={{ fontSize: 15, color: '#aaa' }}>数量</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              type="button"
              onClick={() => setQuantity((q) => Math.max(1, q - 1))}
              style={qtyBtnStyle}
            >
              -
            </button>
            <span style={{ fontSize: 20, fontWeight: 700, minWidth: 28, textAlign: 'center' }}>
              {quantity}
            </span>
            <button type="button" onClick={() => setQuantity((q) => q + 1)} style={qtyBtnStyle}>
              +
            </button>
          </div>
        </div>

        {/* confirm button */}
        <button
          type="button"
          onClick={handleConfirm}
          disabled={!selectedSpec}
          style={{
            width: '100%',
            height: 52,
            border: 'none',
            borderRadius: 10,
            background: selectedSpec ? '#FF6B2C' : '#444',
            color: '#fff',
            fontSize: 18,
            fontWeight: 700,
            cursor: selectedSpec ? 'pointer' : 'not-allowed',
            fontFamily: 'inherit',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
          }}
        >
          <span>加入购物车</span>
          <span>{fen2yuan(totalFen)}</span>
        </button>
      </div>
    </div>
  );
}

const qtyBtnStyle: React.CSSProperties = {
  width: 36,
  height: 36,
  border: 'none',
  borderRadius: 6,
  background: '#0B1A20',
  color: '#fff',
  cursor: 'pointer',
  fontSize: 18,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};
