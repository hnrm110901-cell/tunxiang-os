/**
 * WeighDishSheet — 称重菜下单面板
 *
 * 从电子秤实时读取重量，稳定后服务员确认，按 kg 单价计算总价后加入购物车。
 * 真实环境: 商米台秤通过 TXBridge.onScaleData 推送数据
 * 开发模式: 自动模拟秤数据（3秒后稳定）
 */
import { useState, useEffect, useCallback } from 'react';
import type { DishInfo } from '../api/index';
import { startScale, stopScale, onScaleWeight } from '../bridge/TXBridge';

interface WeighDishSheetProps {
  dish: DishInfo;
  onConfirm: (weightKg: number, totalFen: number) => void;
  onClose: () => void;
}

/* Design tokens（与 OrderPage 保持一致） */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  yellow: '#facc15',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

export function WeighDishSheet({ dish, onConfirm, onClose }: WeighDishSheetProps) {
  const [weightKg, setWeightKg] = useState(0);
  const [stable, setStable] = useState(false);
  const [measureCount, setMeasureCount] = useState(0);

  /* 将 price_fen 解释为"每 kg 价格（分）" */
  const pricePerKgFen = dish.price_fen;
  const pricePerKgYuan = (pricePerKgFen / 100).toFixed(2);
  const pricePerJinYuan = (pricePerKgFen / 200).toFixed(2); // 1斤 = 0.5kg

  const totalFen = Math.round(weightKg * pricePerKgFen);
  const totalYuan = (totalFen / 100).toFixed(2);
  const weightJin = (weightKg * 2).toFixed(3); // 1kg = 2斤

  /* 启动秤监听 */
  const startMeasuring = useCallback(() => {
    startScale();
    const cleanup = onScaleWeight((kg, isStable) => {
      setWeightKg(kg);
      setStable(isStable);
    });
    return cleanup;
  }, []);

  useEffect(() => {
    const cleanup = startMeasuring();
    return () => {
      stopScale();
      cleanup();
    };
  // startMeasuring 是 useCallback 包裹的稳定引用，无需加入依赖
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measureCount]);

  /* 重新测量：重置状态，触发 effect 重跑 */
  const handleRemeasure = () => {
    setWeightKg(0);
    setStable(false);
    setMeasureCount(c => c + 1);
  };

  const handleConfirm = () => {
    if (!stable || weightKg <= 0) return;
    onConfirm(weightKg, totalFen);
  };

  return (
    /* 遮罩层 */
    <div
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(0,0,0,0.65)', zIndex: 500,
        display: 'flex', alignItems: 'flex-end',
      }}
      onClick={onClose}
    >
      {/* Sheet 主体 */}
      <div
        style={{
          width: '100%', background: C.bg,
          borderRadius: '16px 16px 0 0',
          padding: '20px 20px 40px',
          boxSizing: 'border-box',
          maxHeight: '65vh',
          overflowY: 'auto',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 拖动条 */}
        <div style={{
          width: 40, height: 4, borderRadius: 2,
          background: C.border, margin: '0 auto 20px',
        }} />

        {/* ── 区域1: 菜品信息 ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{
            display: 'flex', alignItems: 'center',
            justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>
              {dish.dish_name}
            </span>
            <button
              onClick={onClose}
              style={{
                minWidth: 48, minHeight: 48, borderRadius: 8,
                background: 'transparent', border: 'none',
                color: C.muted, fontSize: 20, cursor: 'pointer',
              }}
            >
              ✕
            </button>
          </div>
          <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>
            单价：¥{pricePerKgYuan}/kg（¥{pricePerJinYuan}/斤）
          </div>
          <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>
            换算提示：1斤 = 0.5 kg，1 kg = 2斤
          </div>
        </div>

        {/* ── 区域2: 实时秤显示 ── */}
        <div style={{
          background: C.card, borderRadius: 16,
          border: `1px solid ${stable ? C.green : C.border}`,
          padding: '24px 16px',
          textAlign: 'center',
          marginBottom: 20,
          transition: 'border-color 0.3s',
        }}>
          {/* 大重量数字 */}
          <div style={{
            fontSize: 56, fontWeight: 800, lineHeight: 1,
            color: stable ? C.green : C.yellow,
            fontVariantNumeric: 'tabular-nums',
            letterSpacing: '-1px',
            transition: 'color 0.3s',
          }}>
            {weightKg > 0 ? weightKg.toFixed(3) : '---'}
          </div>
          {/* 单位分隔线 */}
          <div style={{
            height: 2, background: stable ? C.green : C.yellow,
            margin: '8px auto', width: 80,
            borderRadius: 1, transition: 'background 0.3s',
          }} />
          <div style={{ fontSize: 18, color: C.muted, fontWeight: 600 }}>kg</div>

          {/* 稳定性指示 */}
          <div style={{
            marginTop: 12,
            display: 'flex', alignItems: 'center',
            justifyContent: 'center', gap: 8,
          }}>
            {stable ? (
              <>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: C.green, display: 'inline-block',
                }} />
                <span style={{ fontSize: 16, color: C.green, fontWeight: 700 }}>
                  稳定 ✓
                </span>
              </>
            ) : (
              <>
                <span style={{
                  fontSize: 16, color: C.yellow, fontWeight: 700,
                  animation: 'pulse 1s infinite',
                }}>
                  ≈
                </span>
                <span style={{ fontSize: 16, color: C.yellow, fontWeight: 700 }}>
                  测量中...
                </span>
              </>
            )}
          </div>

          {/* kg 转换为斤 */}
          {weightKg > 0 && (
            <div style={{
              marginTop: 10, fontSize: 16, color: C.muted,
            }}>
              {weightJin} 斤
            </div>
          )}
        </div>

        {/* ── 区域3: 价格计算 ── */}
        <div style={{
          background: C.card, borderRadius: 12,
          border: `1px solid ${C.border}`,
          padding: '14px 16px',
          marginBottom: 20,
        }}>
          <div style={{
            fontSize: 16, color: C.muted, marginBottom: 6,
            display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
          }}>
            <span>{weightKg > 0 ? weightKg.toFixed(3) : '0.000'} kg</span>
            <span>×</span>
            <span>¥{pricePerKgYuan}/kg</span>
            <span>=</span>
          </div>
          <div style={{
            fontSize: 28, fontWeight: 800, color: C.accent,
          }}>
            ¥{totalYuan}
          </div>
        </div>

        {/* ── 区域4: 操作按钮 ── */}
        <div style={{ display: 'flex', gap: 12 }}>
          {/* 重新测量 */}
          <button
            onClick={handleRemeasure}
            style={{
              flex: 1, minHeight: 56, borderRadius: 12,
              background: 'transparent',
              border: `1.5px solid ${C.border}`,
              color: C.text, fontSize: 17, fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            重新测量
          </button>

          {/* 确认加入购物车 */}
          <button
            onClick={handleConfirm}
            disabled={!stable || weightKg <= 0}
            style={{
              flex: 2, minHeight: 56, borderRadius: 12,
              background: stable && weightKg > 0 ? C.accent : C.muted,
              color: C.white, border: 'none',
              fontSize: 17, fontWeight: 700,
              cursor: stable && weightKg > 0 ? 'pointer' : 'not-allowed',
              transition: 'background 0.3s',
            }}
          >
            {stable && weightKg > 0
              ? `确认加入 ¥${totalYuan}`
              : '等待秤稳定...'}
          </button>
        </div>
      </div>
    </div>
  );
}
