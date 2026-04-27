/**
 * ProfileInfoTab.tsx — 会员信息Tab
 *
 * 包含：基础信息 + 消费统计增强 + 菜品偏好柱状图 + RFM + 流失风险 + AI话术
 */
import React from 'react';
import type { CustomerProfile } from '../types';
import { RFMBadge } from './RFMBadge';
import { ChurnRiskBar } from './ChurnRiskBar';
import { GreetingHint } from './GreetingHint';
import { BirthdayBadge } from './BirthdayBadge';

interface ProfileInfoTabProps {
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

function InfoRow({ label, value }: { label: string; value: React.ReactNode }): React.ReactElement {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-tx-text-3">{label}</span>
      <span className="text-xs text-tx-text-1 font-medium text-right max-w-[60%] truncate">
        {value || '—'}
      </span>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}): React.ReactElement {
  return (
    <div className="flex flex-col items-center bg-tx-bg-2 rounded-tx-md p-2.5 flex-1 min-w-0">
      <span className="text-[11px] text-tx-text-3 mb-1 truncate w-full text-center">
        {label}
      </span>
      <span className="text-sm font-semibold text-tx-text-1 truncate w-full text-center">
        {value}
      </span>
      {sub && (
        <span className="text-[10px] text-tx-text-3 truncate w-full text-center mt-0.5">
          {sub}
        </span>
      )}
    </div>
  );
}

export function ProfileInfoTab({ customer }: ProfileInfoTabProps): React.ReactElement {
  const consumption = customer.consumption;

  // 消费统计数据（优先使用 consumption 详情，回退到顶层字段）
  const totalAmount = consumption?.total_amount_fen ?? customer.total_order_amount_fen;
  const totalCount = consumption?.total_count ?? customer.total_order_count;
  const avgAmount = consumption?.avg_amount_fen
    ?? (totalCount > 0 ? Math.round(totalAmount / totalCount) : 0);
  const lastOrderAt = consumption?.last_order_at ?? customer.last_order_at;

  // 格式化最后到店
  const lastVisitText = (() => {
    if (consumption?.last_order_days != null) {
      if (consumption.last_order_days === 0) return '今天';
      return `${consumption.last_order_days}天前`;
    }
    if (lastOrderAt) {
      const days = Math.floor(
        (Date.now() - new Date(lastOrderAt).getTime()) / (1000 * 60 * 60 * 24),
      );
      if (days === 0) return '今天';
      return `${days}天前`;
    }
    return '暂无记录';
  })();

  const dishPrefs = customer.dish_preferences ?? [];
  const maxOrderTimes = dishPrefs.length > 0
    ? Math.max(...dishPrefs.map((d) => d.order_times))
    : 1;

  return (
    <div className="px-4 pb-4">
      {/* ── 基础信息 ── */}
      <SectionTitle>基本信息</SectionTitle>
      <div className="bg-tx-bg-2 rounded-tx-md px-3 py-1">
        <InfoRow label="手机号" value={customer.phone} />
        <InfoRow
          label="生日"
          value={
            <span className="inline-flex items-center gap-1.5">
              {customer.birthday || '—'}
              {customer.birthday_coming && <BirthdayBadge />}
            </span>
          }
        />
        <InfoRow label="性别" value={customer.gender} />
        <InfoRow label="注册日期" value={customer.member_since} />
        <InfoRow label="来源渠道" value={customer.channel_source} />
        {customer.frequent_store && (
          <InfoRow
            label="常去门店"
            value={`${customer.frequent_store.store_name} (${customer.frequent_store.visit_count}次)`}
          />
        )}
        {customer.wecom_remark && (
          <InfoRow label="导购备注" value={customer.wecom_remark} />
        )}
      </div>

      <Divider />

      {/* ── RFM等级 ── */}
      <SectionTitle>客户价值</SectionTitle>
      <RFMBadge
        rfmLevel={customer.rfm_level}
        rScore={customer.r_score}
        fScore={customer.f_score}
        mScore={customer.m_score}
      />

      <Divider />

      {/* ── 消费统计增强 ── */}
      <SectionTitle>消费记录</SectionTitle>
      <div className="grid grid-cols-3 gap-1.5 mb-2">
        <StatCard label="累计消费" value={fenToYuan(totalAmount)} />
        <StatCard label="订单数" value={`${totalCount}单`} />
        <StatCard label="客单价" value={avgAmount > 0 ? fenToYuan(avgAmount) : '—'} />
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <StatCard label="上次到店" value={lastVisitText} />
        {consumption?.recent_30d_count != null && (
          <StatCard
            label="近30天"
            value={`${consumption.recent_30d_count}单`}
            sub={consumption.recent_30d_amount_fen != null
              ? fenToYuan(consumption.recent_30d_amount_fen)
              : undefined}
          />
        )}
        {consumption?.avg_interval_days != null && (
          <StatCard label="消费间隔" value={`${consumption.avg_interval_days}天`} />
        )}
      </div>

      <Divider />

      {/* ── 菜品偏好柱状图 ── */}
      {dishPrefs.length > 0 && (
        <>
          <SectionTitle>菜品偏好</SectionTitle>
          <div className="space-y-1.5">
            {dishPrefs.slice(0, 8).map((dish) => (
              <div key={dish.dish_name} className="flex items-center gap-2">
                <span className="text-xs text-tx-text-2 w-16 truncate flex-shrink-0">
                  {dish.dish_name}
                </span>
                <div className="flex-1 bg-tx-bg-2 rounded-full h-4 overflow-hidden">
                  <div
                    className="bg-purple-400 h-full rounded-full transition-all"
                    style={{ width: `${Math.max(dish.percentage * 100, 5)}%` }}
                  />
                </div>
                <span className="text-xs text-tx-text-3 w-8 text-right flex-shrink-0">
                  {dish.order_times}次
                </span>
              </div>
            ))}
          </div>
          <Divider />
        </>
      )}

      {/* ── 流失风险 ── */}
      <SectionTitle>流失风险</SectionTitle>
      <ChurnRiskBar riskScore={customer.risk_score} />

      {/* ── AI话术建议 ── */}
      {customer.greeting_hint && (
        <>
          <Divider />
          <GreetingHint hint={customer.greeting_hint} />
        </>
      )}
    </div>
  );
}
