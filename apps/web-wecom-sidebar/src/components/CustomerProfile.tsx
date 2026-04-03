/**
 * CustomerProfile.tsx — 会员档案主卡片
 *
 * 展示内容：
 *   - 头像 + 姓名 + 会员等级徽章
 *   - RFM 等级（含 R/F/M 分值）
 *   - 消费统计（累计金额 / 订单数 / 最后到店）
 *   - 偏好标签 + 常点菜品
 *   - 流失风险条
 *   - 导购快捷操作（发优惠券 / 打标签 / 写备注）
 *   - 导购备注展示
 */
import React from 'react';
import type { CustomerProfile as CustomerProfileType, MemberLevel } from '../types';
import { RFMBadge } from './RFMBadge';
import { ConsumptionStats } from './ConsumptionStats';
import { PreferenceTags } from './PreferenceTags';
import { ChurnRiskBar } from './ChurnRiskBar';
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

interface CustomerProfileProps {
  customer: CustomerProfileType;
  onRefresh: () => void;
}

export function CustomerProfile({
  customer,
  onRefresh,
}: CustomerProfileProps): React.ReactElement {
  const levelConfig = MEMBER_LEVEL_CONFIG[customer.member_level] ?? MEMBER_LEVEL_CONFIG.normal;
  const avatarUrl = customer.wechat_avatar_url;

  return (
    <div className="bg-tx-bg-1 rounded-tx-lg shadow-tx-sm overflow-hidden">
      {/* ── 头部：头像 + 姓名 + 等级 ──────────────────────────── */}
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
            {/* 默认头像（头像加载失败时显示，或无头像时显示） */}
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

            {/* 企微备注（若有） */}
            {customer.wecom_remark && (
              <p className="text-xs text-tx-text-3 mt-1 line-clamp-1">
                备注：{customer.wecom_remark}
              </p>
            )}
          </div>
        </div>
      </div>

      <Divider />

      {/* ── RFM 等级 ──────────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <SectionTitle>客户价值</SectionTitle>
        <RFMBadge
          rfmLevel={customer.rfm_level}
          rScore={customer.r_score}
          fScore={customer.f_score}
          mScore={customer.m_score}
        />
      </div>

      <Divider />

      {/* ── 消费统计 ──────────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <SectionTitle>消费记录</SectionTitle>
        <ConsumptionStats
          totalOrderAmountFen={customer.total_order_amount_fen}
          totalOrderCount={customer.total_order_count}
          lastOrderAt={customer.last_order_at}
        />
      </div>

      <Divider />

      {/* ── 偏好标签 ──────────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <SectionTitle>偏好 &amp; 标签</SectionTitle>
        <PreferenceTags
          tags={customer.tags}
          favoriteDishes={customer.favorite_dishes}
        />
      </div>

      <Divider />

      {/* ── 流失风险 ──────────────────────────────────────────── */}
      <div className="px-4 pb-3">
        <SectionTitle>流失风险</SectionTitle>
        <ChurnRiskBar riskScore={customer.risk_score} />
      </div>

      <Divider />

      {/* ── 快捷操作 ──────────────────────────────────────────── */}
      <div className="px-4 pb-4">
        <SectionTitle>快捷操作</SectionTitle>
        <ActionPanel customer={customer} onActionDone={onRefresh} />
      </div>
    </div>
  );
}
