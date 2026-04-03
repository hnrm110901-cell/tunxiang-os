/**
 * ActionPanel.tsx — 导购快捷操作（发优惠券 / 打标签 / 添加备注）
 *
 * 三个按钮，点击后弹出对应操作面板（底部抽屉形式）。
 * 完成操作后通过 onActionDone 回调通知父组件刷新数据。
 */
import React, { useState, useEffect } from 'react';
import type { CustomerProfile, Coupon, ActionPanelMode } from '../types';
import {
  fetchIssuableCoupons,
  issueCoupon,
  updateCustomerTags,
  updateWecomRemark,
} from '../api/memberApi';

interface ActionPanelProps {
  customer: CustomerProfile;
  onActionDone: () => void;
}

// ─── 底部抽屉容器 ─────────────────────────────────────────────────
function Drawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <>
      {/* 遮罩 */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-40"
          onClick={onClose}
        />
      )}
      {/* 抽屉主体 */}
      <div
        className={`fixed bottom-0 left-0 right-0 z-50 bg-tx-bg-1 rounded-t-2xl
                    shadow-tx-lg transition-transform duration-300 ease-out
                    ${open ? 'translate-y-0' : 'translate-y-full'}`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-tx-border">
          <span className="text-sm font-semibold text-tx-text-1">{title}</span>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full
                       bg-tx-bg-2 text-tx-text-2 active:bg-tx-bg-3 transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="p-4 pb-safe max-h-[60vh] overflow-y-auto">
          {children}
        </div>
      </div>
    </>
  );
}

// ─── 发券面板 ──────────────────────────────────────────────────────
function CouponDrawer({
  open,
  customerId,
  onClose,
  onDone,
}: {
  open: boolean;
  customerId: string;
  onClose: () => void;
  onDone: () => void;
}): React.ReactElement {
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [loadingCoupons, setLoadingCoupons] = useState(false);
  const [issuing, setIssuing] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoadingCoupons(true);
    fetchIssuableCoupons()
      .then(setCoupons)
      .catch(() => setCoupons([]))
      .finally(() => setLoadingCoupons(false));
  }, [open]);

  async function handleIssue(couponId: string): Promise<void> {
    setIssuing(couponId);
    setFeedback(null);
    try {
      await issueCoupon(customerId, couponId);
      setFeedback('发券成功！');
      setTimeout(() => {
        onDone();
        onClose();
      }, 800);
    } catch {
      setFeedback('发券失败，请重试');
    } finally {
      setIssuing(null);
    }
  }

  return (
    <Drawer open={open} title="选择优惠券" onClose={onClose}>
      {feedback && (
        <p className="text-sm text-center text-tx-success mb-3">{feedback}</p>
      )}
      {loadingCoupons ? (
        <p className="text-sm text-tx-text-3 text-center py-4">加载中...</p>
      ) : coupons.length === 0 ? (
        <p className="text-sm text-tx-text-3 text-center py-4">暂无可发放的优惠券</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {coupons.map((c) => (
            <li
              key={c.coupon_id}
              className="flex items-center justify-between p-3 bg-tx-bg-2
                         rounded-tx-md border border-tx-border"
            >
              <div>
                <p className="text-sm font-medium text-tx-text-1">{c.name}</p>
                <p className="text-xs text-tx-text-3">{c.discount_desc}</p>
              </div>
              <button
                onClick={() => handleIssue(c.coupon_id)}
                disabled={issuing === c.coupon_id}
                className="px-3 py-1.5 bg-tx-primary text-white text-xs rounded-tx-md
                           disabled:opacity-50 active:scale-[0.97] transition-transform"
              >
                {issuing === c.coupon_id ? '发送中...' : '发放'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}

// ─── 打标签面板 ────────────────────────────────────────────────────
const PRESET_TAGS = [
  '高消费', '常客', '商务宴请', '家庭聚餐', '过生日',
  '口味清淡', '不辣', '海鲜爱好者', '素食', '需要发票',
];

function TagDrawer({
  open,
  customer,
  onClose,
  onDone,
}: {
  open: boolean;
  customer: CustomerProfile;
  onClose: () => void;
  onDone: () => void;
}): React.ReactElement {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(customer.tags),
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setSelected(new Set(customer.tags));
  }, [open, customer.tags]);

  function toggle(tag: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(tag) ? next.delete(tag) : next.add(tag);
      return next;
    });
  }

  async function handleSave(): Promise<void> {
    setSaving(true);
    try {
      await updateCustomerTags(customer.customer_id, Array.from(selected));
      onDone();
      onClose();
    } catch {
      // 保持当前状态，让用户重试
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer open={open} title="打标签" onClose={onClose}>
      <div className="flex flex-wrap gap-2 mb-4">
        {PRESET_TAGS.map((tag) => {
          const active = selected.has(tag);
          return (
            <button
              key={tag}
              onClick={() => toggle(tag)}
              className={`px-3 py-1.5 rounded-full text-sm transition-colors duration-150
                          ${active
                            ? 'bg-tx-primary text-white'
                            : 'bg-tx-bg-2 text-tx-text-2 border border-tx-border'
                          }`}
            >
              {tag}
            </button>
          );
        })}
      </div>
      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full py-3 bg-tx-primary text-white font-medium rounded-tx-md
                   disabled:opacity-50 active:bg-tx-primary-active transition-colors"
      >
        {saving ? '保存中...' : '保存标签'}
      </button>
    </Drawer>
  );
}

// ─── 添加备注面板 ──────────────────────────────────────────────────
function RemarkDrawer({
  open,
  customer,
  onClose,
  onDone,
}: {
  open: boolean;
  customer: CustomerProfile;
  onClose: () => void;
  onDone: () => void;
}): React.ReactElement {
  const [text, setText] = useState(customer.wecom_remark ?? '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setText(customer.wecom_remark ?? '');
  }, [open, customer.wecom_remark]);

  async function handleSave(): Promise<void> {
    setSaving(true);
    try {
      await updateWecomRemark(customer.customer_id, text.trim());
      onDone();
      onClose();
    } catch {
      // 保持状态
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer open={open} title="导购备注" onClose={onClose}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="记录客户偏好、特殊需求、重要提醒..."
        rows={5}
        maxLength={200}
        className="w-full p-3 text-sm text-tx-text-1 bg-tx-bg-2 border border-tx-border
                   rounded-tx-md resize-none focus:outline-none focus:border-tx-primary
                   transition-colors placeholder:text-tx-text-3"
      />
      <div className="flex items-center justify-between mt-1 mb-4">
        <span className="text-xs text-tx-text-3">{text.length}/200</span>
      </div>
      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full py-3 bg-tx-primary text-white font-medium rounded-tx-md
                   disabled:opacity-50 active:bg-tx-primary-active transition-colors"
      >
        {saving ? '保存中...' : '保存备注'}
      </button>
    </Drawer>
  );
}

// ─── 主面板 ────────────────────────────────────────────────────────
export function ActionPanel({
  customer,
  onActionDone,
}: ActionPanelProps): React.ReactElement {
  const [mode, setMode] = useState<ActionPanelMode>(null);

  const actions: Array<{
    id: ActionPanelMode;
    label: string;
    icon: string;
    colorClass: string;
  }> = [
    { id: 'coupon', label: '发优惠券', icon: '🎫', colorClass: 'bg-orange-50 text-tx-primary' },
    { id: 'tag',    label: '打标签',   icon: '🏷️', colorClass: 'bg-blue-50 text-blue-600' },
    { id: 'remark', label: '写备注',   icon: '📝', colorClass: 'bg-green-50 text-tx-success' },
  ];

  return (
    <>
      {/* 三按钮行 */}
      <div className="flex gap-2">
        {actions.map((action) => (
          <button
            key={action.id}
            onClick={() => setMode(action.id)}
            className={`flex-1 flex flex-col items-center gap-1.5 py-3 rounded-tx-md
                        ${action.colorClass} font-medium
                        active:scale-[0.97] transition-transform duration-200`}
          >
            <span className="text-xl leading-none">{action.icon}</span>
            <span className="text-xs">{action.label}</span>
          </button>
        ))}
      </div>

      {/* 抽屉 */}
      <CouponDrawer
        open={mode === 'coupon'}
        customerId={customer.customer_id}
        onClose={() => setMode(null)}
        onDone={onActionDone}
      />
      <TagDrawer
        open={mode === 'tag'}
        customer={customer}
        onClose={() => setMode(null)}
        onDone={onActionDone}
      />
      <RemarkDrawer
        open={mode === 'remark'}
        customer={customer}
        onClose={() => setMode(null)}
        onDone={onActionDone}
      />
    </>
  );
}
