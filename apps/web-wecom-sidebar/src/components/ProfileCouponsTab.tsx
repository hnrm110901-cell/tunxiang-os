/**
 * ProfileCouponsTab.tsx — 会员券包Tab
 *
 * 可用券列表 + 发券操作 + 发券历史记录
 */
import React, { useState, useCallback } from 'react';
import type { CustomerProfile, AvailableCoupon, CouponSendRecord } from '../types';
import { sendCouponWithLog } from '../api/memberApi';

interface ProfileCouponsTabProps {
  customer: CustomerProfile;
  onRefresh: () => void;
}

function SectionTitle({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <h3 className="text-xs font-semibold text-tx-text-3 uppercase tracking-wide mb-2">
      {children}
    </h3>
  );
}

function Divider(): React.ReactElement {
  return <div className="border-t border-tx-border my-3" />;
}

const SEND_STATUS_LABEL: Record<string, { label: string; className: string }> = {
  sent:     { label: '已发',  className: 'text-blue-600 bg-blue-50' },
  received: { label: '已领',  className: 'text-green-600 bg-green-50' },
  used:     { label: '已用',  className: 'text-tx-success bg-green-50' },
  expired:  { label: '已过期', className: 'text-tx-text-3 bg-gray-100' },
  failed:   { label: '失败',  className: 'text-tx-danger bg-red-50' },
};

function CouponCard({
  coupon,
  onSend,
  sending,
}: {
  coupon: AvailableCoupon;
  onSend: () => void;
  sending: boolean;
}): React.ReactElement {
  const isExpired = coupon.status === 'expired';
  const isUsed = coupon.status === 'used';
  const disabled = isExpired || isUsed || sending;

  return (
    <div
      className={`flex items-stretch rounded-tx-md border overflow-hidden
        ${isExpired || isUsed
          ? 'border-tx-border bg-tx-bg-2 opacity-60'
          : 'border-tx-primary/30 bg-white'
        }`}
    >
      {/* 左: 折扣标识 */}
      <div
        className={`w-20 flex flex-col items-center justify-center p-2 flex-shrink-0
          ${isExpired || isUsed ? 'bg-gray-100' : 'bg-tx-primary-light'}`}
      >
        <span
          className={`text-sm font-bold leading-tight
            ${isExpired || isUsed ? 'text-tx-text-3' : 'text-tx-primary'}`}
        >
          {coupon.discount_desc}
        </span>
      </div>

      {/* 中: 名称+有效期 */}
      <div className="flex-1 px-3 py-2 min-w-0">
        <p className="text-sm font-medium text-tx-text-1 truncate">{coupon.name}</p>
        <p className="text-[10px] text-tx-text-3 mt-0.5">
          有效期至 {coupon.expire_at.slice(0, 10)}
        </p>
      </div>

      {/* 右: 发券按钮 */}
      <div className="flex items-center pr-2 flex-shrink-0">
        {isUsed ? (
          <span className="text-[11px] text-tx-text-3 px-2">已使用</span>
        ) : isExpired ? (
          <span className="text-[11px] text-tx-text-3 px-2">已过期</span>
        ) : (
          <button
            onClick={onSend}
            disabled={disabled}
            className="px-3 py-1.5 bg-tx-primary text-white text-xs rounded-tx-md
                       disabled:opacity-50 active:scale-[0.97] transition-transform"
          >
            {sending ? '发送...' : '发券'}
          </button>
        )}
      </div>
    </div>
  );
}

function SendRecordItem({ record }: { record: CouponSendRecord }): React.ReactElement {
  const statusInfo = SEND_STATUS_LABEL[record.send_status] ?? SEND_STATUS_LABEL.sent;

  return (
    <div className="flex items-center justify-between py-2 border-b border-tx-border last:border-b-0">
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-tx-text-1 truncate">{record.coupon_name}</p>
        <p className="text-[10px] text-tx-text-3 mt-0.5">
          {record.sent_at.slice(0, 16).replace('T', ' ')}
          {record.employee_name ? ` · ${record.employee_name}` : ''}
        </p>
      </div>
      <span
        className={`text-[11px] font-medium px-2 py-0.5 rounded-full flex-shrink-0
          ${statusInfo.className}`}
      >
        {statusInfo.label}
      </span>
    </div>
  );
}

export function ProfileCouponsTab({
  customer,
  onRefresh,
}: ProfileCouponsTabProps): React.ReactElement {
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(
    null,
  );

  const coupons = customer.available_coupons ?? [];
  const sendRecords = customer.recent_coupon_sends ?? [];

  // 分类券
  const activeCoupons = coupons.filter(
    (c) => c.status !== 'used' && c.status !== 'expired',
  );
  const usedOrExpired = coupons.filter(
    (c) => c.status === 'used' || c.status === 'expired',
  );

  const handleSend = useCallback(
    async (coupon: AvailableCoupon) => {
      setSendingId(coupon.coupon_id);
      setFeedback(null);
      try {
        const employeeId = localStorage.getItem('tx_employee_id') ?? '';
        const storeId = localStorage.getItem('tx_store_id') ?? '';
        await sendCouponWithLog(
          customer.customer_id,
          coupon.coupon_id,
          employeeId,
          storeId,
        );
        setFeedback({ type: 'success', message: `"${coupon.name}" 发券成功` });
        setTimeout(() => {
          setFeedback(null);
          onRefresh();
        }, 1500);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : '发券失败';
        setFeedback({ type: 'error', message: msg });
      } finally {
        setSendingId(null);
      }
    },
    [customer.customer_id, onRefresh],
  );

  return (
    <div className="px-4 pb-4">
      {/* 反馈 */}
      {feedback && (
        <div
          className={`text-sm text-center py-2 mb-3 rounded-tx-md
            ${feedback.type === 'success'
              ? 'bg-green-50 text-tx-success'
              : 'bg-red-50 text-tx-danger'
            }`}
        >
          {feedback.message}
        </div>
      )}

      {/* ── 可用券 ── */}
      <div className="flex items-center justify-between mb-2">
        <SectionTitle>可用优惠券</SectionTitle>
        {customer.available_coupon_count != null && (
          <span className="text-xs text-tx-primary font-medium">
            {customer.available_coupon_count}张
          </span>
        )}
      </div>

      {activeCoupons.length > 0 ? (
        <div className="flex flex-col gap-2">
          {activeCoupons.map((coupon) => (
            <CouponCard
              key={coupon.coupon_id}
              coupon={coupon}
              onSend={() => handleSend(coupon)}
              sending={sendingId === coupon.coupon_id}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-tx-text-3 py-3 text-center">暂无可用优惠券</p>
      )}

      {/* ── 已使用/过期 ── */}
      {usedOrExpired.length > 0 && (
        <>
          <Divider />
          <SectionTitle>已使用 / 已过期</SectionTitle>
          <div className="flex flex-col gap-2">
            {usedOrExpired.map((coupon) => (
              <CouponCard
                key={coupon.coupon_id}
                coupon={coupon}
                onSend={() => {}}
                sending={false}
              />
            ))}
          </div>
        </>
      )}

      <Divider />

      {/* ── 发券记录 ── */}
      <SectionTitle>发券记录</SectionTitle>
      {sendRecords.length > 0 ? (
        <div className="bg-tx-bg-2 rounded-tx-md px-3">
          {sendRecords.slice(0, 10).map((record, idx) => (
            <SendRecordItem key={`${record.coupon_name}-${record.sent_at}-${idx}`} record={record} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-tx-text-3 py-3 text-center">暂无发券记录</p>
      )}
    </div>
  );
}
