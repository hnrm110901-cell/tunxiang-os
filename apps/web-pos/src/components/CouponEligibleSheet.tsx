/**
 * CouponEligibleSheet — 结账可用券提示底部弹层
 *
 * 触发时机：campaign.checkout_eligible 事件（即 apply-to-order 返回有可用券）
 * 收银员可选择一张券核销，或跳过不使用。
 */
import type { EligibleCoupon } from '../api/couponApi';

const fen2yuan = (fen: number) => (fen / 100).toFixed(2);

const COUPON_TYPE_LABEL: Record<string, string> = {
  cash: '满减券',
  discount: '折扣券',
  gift: '赠品券',
};

interface Props {
  visible: boolean;
  coupons: EligibleCoupon[];
  applying: boolean;
  onApply: (couponId: string) => void;
  onClose: () => void;
}

export function CouponEligibleSheet({ visible, coupons, applying, onApply, onClose }: Props) {
  if (!visible) return null;

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.55)',
          zIndex: 900,
        }}
      />

      {/* 底部弹层 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: '#112228',
        borderRadius: '16px 16px 0 0',
        padding: '20px 16px 32px',
        zIndex: 901,
        maxHeight: '70vh',
        overflowY: 'auto',
      }}>
        {/* 标题栏 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 20 }}>🎟️</span>
            <span style={{ color: '#fff', fontWeight: 700, fontSize: 16 }}>
              发现 {coupons.length} 张可用优惠券
            </span>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#888', fontSize: 22, cursor: 'pointer', lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        <p style={{ color: '#aaa', fontSize: 13, margin: '0 0 16px' }}>
          请选择一张优惠券核销，或跳过不使用
        </p>

        {/* 券列表 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {coupons.map((c) => (
            <div
              key={c.id}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: '#0B1A20',
                border: '1px solid #1e3a42',
                borderRadius: 10,
                padding: '12px 14px',
              }}
            >
              {/* 左：券信息 */}
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{
                    fontSize: 11, padding: '2px 6px', borderRadius: 4,
                    background: '#FF6B2C22', color: '#FF6B2C', fontWeight: 600,
                  }}>
                    {COUPON_TYPE_LABEL[c.coupon_type] ?? c.coupon_type}
                  </span>
                  <span style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>{c.name}</span>
                </div>
                <div style={{ color: '#aaa', fontSize: 12 }}>
                  满 ¥{fen2yuan(c.min_order_fen)} 可用 · 有效期至 {c.expire_at.slice(0, 10)}
                </div>
              </div>

              {/* 中：减免金额 */}
              <div style={{ textAlign: 'center', marginLeft: 12, marginRight: 16 }}>
                <div style={{ color: '#FF6B2C', fontWeight: 700, fontSize: 20 }}>
                  -{fen2yuan(c.discount_amount_fen)}
                </div>
                <div style={{ color: '#888', fontSize: 11 }}>元</div>
              </div>

              {/* 右：核销按钮 */}
              <button
                disabled={applying}
                onClick={() => onApply(c.id)}
                style={{
                  padding: '8px 16px',
                  background: applying ? '#444' : '#FF6B2C',
                  color: '#fff', border: 'none', borderRadius: 8,
                  fontSize: 13, fontWeight: 600, cursor: applying ? 'not-allowed' : 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {applying ? '核销中…' : '立即核销'}
              </button>
            </div>
          ))}
        </div>

        {/* 底部跳过按钮 */}
        <button
          onClick={onClose}
          style={{
            width: '100%', marginTop: 16,
            padding: '12px 0',
            background: 'transparent',
            border: '1px solid #2a4a55',
            borderRadius: 10,
            color: '#888', fontSize: 14, cursor: 'pointer',
          }}
        >
          跳过，不使用优惠券
        </button>
      </div>
    </>
  );
}
