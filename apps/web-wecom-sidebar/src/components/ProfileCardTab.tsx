/**
 * ProfileCardTab.tsx — 会员卡Tab
 *
 * 会员卡视觉 + 卡号/等级/有效期 + 积分 + 储值 + 升级进度
 */
import React from 'react';
import type { CustomerProfile, MemberLevel } from '../types';

interface ProfileCardTabProps {
  customer: CustomerProfile;
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

function fenToYuan(fen: number): string {
  return `¥${(fen / 100).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
}

const CARD_BG: Record<MemberLevel, string> = {
  normal:  'from-gray-400 to-gray-500',
  silver:  'from-slate-400 to-slate-500',
  gold:    'from-amber-400 to-amber-600',
  diamond: 'from-purple-500 to-purple-700',
};

const CARD_LEVEL_LABEL: Record<MemberLevel, string> = {
  normal:  '普通会员',
  silver:  '银卡会员',
  gold:    '金卡会员',
  diamond: '钻石会员',
};

export function ProfileCardTab({ customer }: ProfileCardTabProps): React.ReactElement {
  const card = customer.member_card;
  const points = customer.points;
  const stored = customer.stored_value;
  const bg = CARD_BG[customer.member_level] ?? CARD_BG.normal;

  return (
    <div className="px-4 pb-4">
      {/* ── 会员卡视觉 ── */}
      <div className={`bg-gradient-to-br ${bg} rounded-tx-lg p-4 text-white shadow-tx-md mb-3`}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="text-[10px] opacity-80 mb-0.5">屯象会员</p>
            <p className="text-base font-bold">
              {card?.level_name ?? CARD_LEVEL_LABEL[customer.member_level]}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[10px] opacity-80 mb-0.5">会员等级</p>
            <p className="text-sm font-semibold">
              {card?.level ?? customer.member_level.toUpperCase()}
            </p>
          </div>
        </div>

        <div className="flex items-end justify-between">
          <div>
            <p className="text-[10px] opacity-70">卡号</p>
            <p className="text-sm font-mono tracking-wider">
              {card?.card_no ?? '—'}
            </p>
          </div>
          {card?.expire_at && (
            <div className="text-right">
              <p className="text-[10px] opacity-70">有效期至</p>
              <p className="text-xs">{card.expire_at.slice(0, 10)}</p>
            </div>
          )}
        </div>

        <p className="text-xs opacity-80 mt-2">{customer.display_name}</p>
      </div>

      {/* ── 升级进度 ── */}
      {card?.upgrade_progress != null && card.next_level && (
        <>
          <SectionTitle>升级进度</SectionTitle>
          <div className="bg-tx-bg-2 rounded-tx-md p-3 mb-1">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-tx-text-2">
                距 <span className="font-semibold text-tx-text-1">{card.next_level}</span>
              </span>
              <span className="text-xs font-semibold text-tx-primary">
                {Math.round(card.upgrade_progress * 100)}%
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-tx-border overflow-hidden">
              <div
                className="h-full rounded-full bg-tx-primary transition-all duration-500"
                style={{ width: `${Math.round(card.upgrade_progress * 100)}%` }}
              />
            </div>
          </div>
          <Divider />
        </>
      )}

      {/* ── 积分 ── */}
      <SectionTitle>积分</SectionTitle>
      {points ? (
        <div className="bg-tx-bg-2 rounded-tx-md p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-tx-text-3">可用积分</span>
            <span className="text-lg font-bold text-tx-primary">
              {points.balance.toLocaleString()}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <div className="text-center flex-1">
              <p className="text-[11px] text-tx-text-3">累计获取</p>
              <p className="text-sm font-medium text-tx-text-1">
                {points.total_earned.toLocaleString()}
              </p>
            </div>
            <div className="w-px h-6 bg-tx-border" />
            <div className="text-center flex-1">
              <p className="text-[11px] text-tx-text-3">已使用</p>
              <p className="text-sm font-medium text-tx-text-1">
                {points.total_used.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-tx-text-3 py-1">暂无积分数据</p>
      )}

      <Divider />

      {/* ── 储值 ── */}
      <SectionTitle>储值</SectionTitle>
      {stored ? (
        <div className="bg-tx-bg-2 rounded-tx-md p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-tx-text-3">储值余额</span>
            <span className="text-lg font-bold text-tx-success">
              {fenToYuan(stored.balance_fen)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <div className="text-center flex-1">
              <p className="text-[11px] text-tx-text-3">总充值</p>
              <p className="text-sm font-medium text-tx-text-1">
                {fenToYuan(stored.total_recharged_fen)}
              </p>
            </div>
            <div className="w-px h-6 bg-tx-border" />
            <div className="text-center flex-1">
              <p className="text-[11px] text-tx-text-3">充值次数</p>
              <p className="text-sm font-medium text-tx-text-1">
                {stored.recharge_count}次
              </p>
            </div>
          </div>
          {stored.last_recharge_at && (
            <p className="text-[10px] text-tx-text-3 text-right mt-2">
              上次充值: {stored.last_recharge_at.slice(0, 10)}
            </p>
          )}
        </div>
      ) : (
        <p className="text-xs text-tx-text-3 py-1">暂无储值数据</p>
      )}
    </div>
  );
}
