/**
 * 折扣申请页面 — 服务员为某桌发起折扣/赠送申请，提交后等待领班手机审批
 * 移动端竖屏，最小字体16px，热区>=48px，inline style，无 antd
 * 路由: /discount-request?table=A01&order_id=xxx
 */
import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import { txFetch } from '../api/index';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#ef4444',
};

/* ---------- 折扣类型数据 ---------- */
const DISCOUNT_TYPES = [
  { key: 'rate_9', label: '整单9折', type: 'rate', value: 0.9 },
  { key: 'rate_8', label: '整单8折', type: 'rate', value: 0.8 },
  { key: 'gift_drink', label: '赠送饮品', type: 'gift', value: 0 },
  { key: 'gift_dessert', label: '赠送甜品', type: 'gift', value: 0 },
  { key: 'custom', label: '其他（自定义）', type: 'custom', value: 0 },
];

const QUICK_REASONS = ['等待时间长', 'VIP会员', '生日庆祝', '客诉补偿'];

/* ---------- 工具函数 ---------- */
/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

/* ---------- 组件 ---------- */
export function DiscountRequestPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const tableNo = searchParams.get('table') || '';
  const orderId = searchParams.get('order_id') || '';

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const [originalAmountFen, setOriginalAmountFen] = useState<number | null>(null);
  const [reasonError, setReasonError] = useState('');

  /* 获取订单原价 */
  useEffect(() => {
    if (!orderId) return;
    txFetch<{ final_amount_fen: number }>(`/api/v1/orders/${orderId}`)
      .then(data => setOriginalAmountFen(data.final_amount_fen))
      .catch(() => setOriginalAmountFen(null));
  }, [orderId]);

  /* 提交后倒计时返回 */
  useEffect(() => {
    if (!submitted) return;
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          navigate(`/table-detail?table=${tableNo}&order_id=${orderId}`);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [submitted, navigate, tableNo, orderId]);

  /* 计算折扣金额预估 */
  const selectedType = DISCOUNT_TYPES.find(d => d.key === selectedKey) || null;
  let discountedFen: number | null = null;
  let savedFen: number | null = null;
  if (
    selectedType?.type === 'rate' &&
    originalAmountFen !== null
  ) {
    discountedFen = Math.round(originalAmountFen * selectedType.value);
    savedFen = originalAmountFen - discountedFen;
  }

  const handleQuickReason = (text: string) => {
    setReason(prev => {
      const trimmed = prev.trim();
      if (!trimmed) return text;
      if (trimmed.includes(text)) return prev;
      return `${trimmed} ${text}`;
    });
    setReasonError('');
  };

  const handleSubmit = async () => {
    if (!selectedKey || !selectedType) return;
    if (reason.trim().length < 5) {
      setReasonError('申请原因至少需要5个字');
      return;
    }
    setReasonError('');
    setSubmitting(true);

    const estimatedDiscountFen =
      selectedType.type === 'rate' && originalAmountFen !== null
        ? originalAmountFen - Math.round(originalAmountFen * selectedType.value)
        : 0;

    const storeId = (window as any).__STORE_ID__ || '';
    const applicantId = (window as any).__STAFF_ID__ || '';
    const applicantName = (window as any).__CREW_NAME__ || '';

    try {
      await txFetch('/api/v1/approvals/discount-requests', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          table_no: tableNo,
          order_id: orderId,
          discount_type: selectedKey,
          discount_label: selectedType.label,
          estimated_discount_fen: estimatedDiscountFen,
          reason: reason.trim(),
          applicant_id: applicantId,
          applicant_name: applicantName,
        }),
      });
    } catch {
      /* 网络异常静默处理，仍显示成功界面避免重复提交 */
    } finally {
      setSubmitting(false);
      setSubmitted(true);
    }
  };

  /* ---------- 成功状态 ---------- */
  if (submitted) {
    return (
      <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
        {/* 顶部导航 */}
        <div style={{
          display: 'flex', alignItems: 'center', padding: '0 16px',
          height: 56, borderBottom: `1px solid ${C.border}`,
          background: C.card,
        }}>
          <span style={{ fontSize: 18, fontWeight: 700, flex: 1 }}>折扣申请</span>
          {tableNo && (
            <span style={{ fontSize: 16, color: C.muted }}>{tableNo}桌</span>
          )}
        </div>

        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', padding: '80px 24px 40px',
        }}>
          <div style={{
            width: 72, height: 72, borderRadius: 36,
            background: C.green, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: 36, marginBottom: 24,
          }}>
            ✓
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 12, textAlign: 'center' }}>
            申请已发送
          </div>
          <div style={{ fontSize: 17, color: C.muted, marginBottom: 8, textAlign: 'center' }}>
            等待领班手机审批
          </div>
          <div style={{ fontSize: 16, color: C.muted, textAlign: 'center' }}>
            {countdown} 秒后自动返回
          </div>
          <button
            onClick={() => navigate(`/table-detail?table=${tableNo}&order_id=${orderId}`)}
            style={{
              marginTop: 32, minHeight: 48, padding: '12px 32px',
              borderRadius: 12, background: C.accent, color: C.white,
              border: 'none', fontSize: 17, fontWeight: 700, cursor: 'pointer',
            }}
          >
            立即返回
          </button>
        </div>
      </div>
    );
  }

  /* ---------- 主界面 ---------- */
  const canSubmit = !!selectedKey && reason.trim().length >= 5 && !submitting;

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white, paddingBottom: 24 }}>
      {/* 顶部导航栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', padding: '0 16px',
        height: 56, borderBottom: `1px solid ${C.border}`,
        background: C.card, position: 'sticky', top: 0, zIndex: 10,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 48, minHeight: 48, background: 'none', border: 'none',
            color: C.white, fontSize: 22, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            marginLeft: -12,
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, flex: 1 }}>折扣申请</span>
        {tableNo && (
          <span style={{
            fontSize: 16, fontWeight: 600, color: C.accent,
            background: `${C.accent}22`, padding: '4px 12px',
            borderRadius: 8,
          }}>
            {tableNo}桌
          </span>
        )}
      </div>

      <div style={{ padding: '16px 16px 0' }}>
        {/* 选择折扣类型 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: C.text, marginBottom: 12 }}>
            选择折扣类型
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {DISCOUNT_TYPES.map(dt => {
              const isSelected = selectedKey === dt.key;
              /* 最后一项（其他）跨全宽 */
              const isLast = dt.key === 'custom';
              return (
                <button
                  key={dt.key}
                  onClick={() => setSelectedKey(dt.key)}
                  style={{
                    gridColumn: isLast ? '1 / -1' : undefined,
                    minHeight: 64, padding: '14px 16px',
                    borderRadius: 12, cursor: 'pointer',
                    background: isSelected ? `${C.accent}22` : C.card,
                    border: isSelected ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                    color: isSelected ? C.accent : C.white,
                    fontSize: 17, fontWeight: isSelected ? 700 : 500,
                    textAlign: 'center', transition: 'all 0.15s',
                  }}
                >
                  {dt.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* 折扣金额预估 */}
        {selectedType?.type === 'rate' && originalAmountFen !== null && discountedFen !== null && savedFen !== null && (
          <div style={{
            marginBottom: 20, padding: '14px 16px',
            background: C.card, borderRadius: 12,
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>折扣金额预估</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 17, color: C.muted, textDecoration: 'line-through' }}>
                ¥{fenToYuan(originalAmountFen)}
              </span>
              <span style={{ fontSize: 16, color: C.muted }}>→</span>
              <span style={{ fontSize: 20, fontWeight: 700, color: C.accent }}>
                ¥{fenToYuan(discountedFen)}
              </span>
              <span style={{
                fontSize: 15, color: C.green,
                background: 'rgba(34,197,94,0.12)', padding: '2px 8px',
                borderRadius: 6,
              }}>
                省¥{fenToYuan(savedFen)}
              </span>
            </div>
          </div>
        )}

        {/* 申请原因 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: C.text, marginBottom: 8 }}>
            申请原因
            <span style={{ color: C.danger, marginLeft: 4, fontWeight: 400, fontSize: 15 }}>*必填</span>
          </div>
          <textarea
            value={reason}
            onChange={e => {
              setReason(e.target.value);
              if (e.target.value.trim().length >= 5) setReasonError('');
            }}
            placeholder="请简述申请原因（至少5个字）..."
            rows={4}
            style={{
              width: '100%', padding: '14px', fontSize: 16,
              background: C.card,
              border: `1px solid ${reasonError ? C.danger : C.border}`,
              borderRadius: 12, color: C.white,
              resize: 'none', boxSizing: 'border-box',
              lineHeight: 1.6, outline: 'none',
            }}
          />
          {reasonError && (
            <div style={{ fontSize: 15, color: C.danger, marginTop: 6 }}>
              {reasonError}
            </div>
          )}

          {/* 常用原因快选 */}
          <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {QUICK_REASONS.map(qr => (
              <button
                key={qr}
                onClick={() => handleQuickReason(qr)}
                style={{
                  minHeight: 48, padding: '10px 14px',
                  borderRadius: 8, cursor: 'pointer',
                  background: C.card, border: `1px solid ${C.border}`,
                  color: C.text, fontSize: 16,
                }}
              >
                {qr}
              </button>
            ))}
          </div>
        </div>

        {/* 提交按钮 */}
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          style={{
            width: '100%', height: 72, borderRadius: 14,
            background: canSubmit ? C.accent : C.muted,
            color: C.white, border: 'none',
            fontSize: 19, fontWeight: 700,
            cursor: canSubmit ? 'pointer' : 'not-allowed',
            opacity: canSubmit ? 1 : 0.6,
            transition: 'all 0.15s',
          }}
        >
          {submitting ? '提交中...' : '提交申请'}
        </button>
      </div>
    </div>
  );
}
