/**
 * ActionPanel.tsx — 导购快捷操作（聊天 + 发优惠券 + 打标签 + 添加备注）
 *
 * 精简为头部小按钮样式，抽屉面板保留完整功能。
 * 发券/打标签能力已集成到Tab中，这里保留备注入口和聊天入口。
 */
import React, { useState, useEffect } from 'react';
import type { CustomerProfile, Coupon, ActionPanelMode } from '../types';
import {
  fetchIssuableCoupons,
  issueCoupon,
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

// ─── 主面板（精简为小按钮） ─────────────────────────────────────────
export function ActionPanel({
  customer,
  onActionDone,
}: ActionPanelProps): React.ReactElement {
  const [mode, setMode] = useState<ActionPanelMode>(null);

  return (
    <>
      {/* 紧凑按钮组 */}
      <button
        onClick={() => setMode('remark')}
        className="w-8 h-8 flex items-center justify-center rounded-full
                   bg-tx-bg-2 text-tx-text-2 active:bg-tx-bg-3 transition-colors"
        title="写备注"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round"
                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
      </button>

      {/* 抽屉 */}
      <RemarkDrawer
        open={mode === 'remark'}
        customer={customer}
        onClose={() => setMode(null)}
        onDone={onActionDone}
      />
    </>
  );
}
