/**
 * 折扣审批弹层 — 毛利底线约束校验
 * 当折扣使毛利低于阈值时弹出，需店长审批
 */
interface Props {
  visible: boolean;
  orderNo: string;
  discountRate: number;
  marginBefore: number;
  marginAfter: number;
  threshold: number;
  onApprove: (reason: string) => void;
  onReject: () => void;
}

export function DiscountApprovalModal({ visible, orderNo, discountRate, marginBefore, marginAfter, threshold, onApprove, onReject }: Props) {
  if (!visible) return null;
  const isViolation = marginAfter < threshold;

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ width: 400, background: '#112228', borderRadius: 12, padding: 24, border: isViolation ? '2px solid #ff4d4f' : '2px solid #faad14' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>{isViolation ? '🚨' : '⚠️'}</span>
          <h3 style={{ margin: 0, color: isViolation ? '#ff4d4f' : '#faad14' }}>
            {isViolation ? '毛利底线告警' : '折扣审批'}
          </h3>
        </div>

        <div style={{ fontSize: 13, color: '#ccc', lineHeight: 1.8, marginBottom: 16 }}>
          <div>订单 <b>{orderNo}</b> 申请折扣率 <b style={{ color: '#FF6B2C' }}>{(discountRate * 100).toFixed(0)}%</b></div>
          <div>折扣前毛利率：<b>{(marginBefore * 100).toFixed(1)}%</b></div>
          <div>折扣后毛利率：<b style={{ color: marginAfter < threshold ? '#ff4d4f' : '#52c41a' }}>{(marginAfter * 100).toFixed(1)}%</b></div>
          <div>毛利底线阈值：<b>{(threshold * 100).toFixed(0)}%</b></div>
          {isViolation && <div style={{ color: '#ff4d4f', marginTop: 8, fontWeight: 'bold' }}>⚠️ 折扣后毛利低于底线，需店长授权</div>}
        </div>

        <textarea placeholder="审批原因..." style={{
          width: '100%', height: 60, padding: 8, borderRadius: 6, border: '1px solid #333',
          background: '#0B1A20', color: '#fff', fontSize: 13, resize: 'none', marginBottom: 12,
        }} id="approval-reason" />

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onReject} style={{ flex: 1, padding: 10, background: '#333', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>驳回</button>
          <button onClick={() => onApprove((document.getElementById('approval-reason') as HTMLTextAreaElement)?.value || '')}
            style={{ flex: 1, padding: 10, background: isViolation ? '#ff4d4f' : '#FF6B2C', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>
            {isViolation ? '强制审批' : '批准'}
          </button>
        </div>
      </div>
    </div>
  );
}
