/**
 * CustomerProfile.tsx — 会员档案主卡片（iCC Grow 风格4Tab布局）
 *
 * Tab结构：
 *   - 会员信息（默认）: 基础信息+消费统计+菜品偏好+RFM+流失风险+AI话术
 *   - 会员标签: 偏好标签+口味标签+场景标签+打标操作
 *   - 会员卡: 卡号+等级+积分+储值+升级进度
 *   - 会员券包: 可用券列表+发券历史+发券操作
 */
import React, { useState } from 'react';
import type { CustomerProfile as CustomerProfileType, MemberLevel, ProfileTab } from '../types';
import { ProfileInfoTab } from './ProfileInfoTab';
import { ProfileTagsTab } from './ProfileTagsTab';
import { ProfileCardTab } from './ProfileCardTab';
import { ProfileCouponsTab } from './ProfileCouponsTab';
import { ActionPanel } from './ActionPanel';

// 会员等级配置
const MEMBER_LEVEL_CONFIG: Record<
  MemberLevel,
  { label: string; bgClass: string; textClass: string }
> = {
  normal:  { label: '普通会员', bgClass: 'bg-gray-100',    textClass: 'text-gray-600' },
  silver:  { label: '银卡会员', bgClass: 'bg-slate-100',   textClass: 'text-slate-600' },
  gold:    { label: '金卡会员', bgClass: 'bg-amber-100',   textClass: 'text-amber-700' },
  diamond: { label: '钻石会员', bgClass: 'bg-purple-100',  textClass: 'text-purple-700' },
};

const TAB_LABELS: Record<ProfileTab, string> = {
  info: '会员信息',
  tags: '会员标签',
  card: '会员卡',
  coupons: '券包',
};

interface CustomerProfileProps {
  customer: CustomerProfileType;
  onRefresh: () => void;
}

export function CustomerProfile({
  customer,
  onRefresh,
}: CustomerProfileProps): React.ReactElement {
  const [activeTab, setActiveTab] = useState<ProfileTab>('info');
  const levelConfig = MEMBER_LEVEL_CONFIG[customer.member_level] ?? MEMBER_LEVEL_CONFIG.normal;
  const avatarUrl = customer.wechat_avatar_url;

  return (
    <div className="bg-tx-bg-1 rounded-tx-lg shadow-tx-sm overflow-hidden">
      {/* ── 头部：头像 + 姓名 + 等级 + 快捷操作 ──────────── */}
      <div className="p-4 pb-3">
        <div className="flex items-start gap-3">
          {/* 头像 */}
          <div className="flex-shrink-0">
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt={customer.display_name}
                className="w-14 h-14 rounded-full object-cover border-2 border-tx-border"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = 'none';
                  const fallback = e.currentTarget.nextSibling as HTMLElement | null;
                  if (fallback) fallback.style.display = 'flex';
                }}
              />
            ) : null}
            {/* 默认头像 */}
            <div
              className={`w-14 h-14 rounded-full bg-tx-bg-3 flex items-center
                          justify-center text-2xl ${avatarUrl ? 'hidden' : 'flex'}`}
            >
              👤
            </div>
          </div>

          {/* 姓名 + 会员等级 */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base font-semibold text-tx-text-1 truncate">
                {customer.display_name || '未知客户'}
              </h2>
              <span
                className={`text-[11px] font-medium px-1.5 py-0.5 rounded
                            ${levelConfig.bgClass} ${levelConfig.textClass}`}
              >
                {levelConfig.label}
              </span>
            </div>

            {/* 手机号（若有） */}
            {customer.phone && (
              <p className="text-xs text-tx-text-2 mt-0.5">{customer.phone}</p>
            )}

            {/* 企微备注（若有） */}
            {customer.wecom_remark && (
              <p className="text-xs text-tx-text-3 mt-0.5 line-clamp-1">
                备注：{customer.wecom_remark}
              </p>
            )}
          </div>

          {/* 右侧快捷操作按钮 */}
          <div className="flex flex-col gap-1.5 flex-shrink-0">
            <ActionPanel customer={customer} onActionDone={onRefresh} />
          </div>
        </div>
      </div>

      {/* ── Tab导航栏 ────────────────────────────────────── */}
      <div className="flex border-b border-tx-border">
        {(['info', 'tags', 'card', 'coupons'] as ProfileTab[]).map((tab) => (
          <button
            key={tab}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors relative
              ${activeTab === tab
                ? 'text-tx-primary'
                : 'text-tx-text-3'
              }`}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_LABELS[tab]}
            {tab === 'coupons' && customer.available_coupon_count != null && customer.available_coupon_count > 0 && (
              <span className="absolute -top-0.5 right-1/4 min-w-[16px] h-4 px-1
                               bg-tx-danger text-white text-[10px] font-bold
                               rounded-full flex items-center justify-center">
                {customer.available_coupon_count > 99 ? '99+' : customer.available_coupon_count}
              </span>
            )}
            {/* active下划线 */}
            {activeTab === tab && (
              <span className="absolute bottom-0 left-1/4 right-1/4 h-0.5 bg-tx-primary rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* ── Tab内容区 ────────────────────────────────────── */}
      <div className="pt-3">
        {activeTab === 'info' && <ProfileInfoTab customer={customer} />}
        {activeTab === 'tags' && <ProfileTagsTab customer={customer} onRefresh={onRefresh} />}
        {activeTab === 'card' && <ProfileCardTab customer={customer} />}
        {activeTab === 'coupons' && <ProfileCouponsTab customer={customer} onRefresh={onRefresh} />}
      </div>
    </div>
  );
}
