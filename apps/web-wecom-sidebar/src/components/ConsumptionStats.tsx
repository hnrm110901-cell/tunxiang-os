/**
 * ConsumptionStats.tsx — 消费统计（累计消费金额 / 订单数 / 最后到店）
 *
 * 金额单位：分 → 元（除以100，保留两位小数）
 */
import React from 'react';
import { formatPrice } from '@tx-ds/utils';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return `¥${(fen / 100).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
}

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
}

function StatCard({ label, value, sub }: StatCardProps): React.ReactElement {
  return (
    <div className="flex flex-col items-center bg-tx-bg-2 rounded-tx-md p-3 flex-1 min-w-0">
      <span className="text-[11px] text-tx-text-3 mb-1 truncate w-full text-center">
        {label}
      </span>
      <span className="text-base font-semibold text-tx-text-1 truncate w-full text-center">
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

interface ConsumptionStatsProps {
  totalOrderAmountFen: number;
  totalOrderCount: number;
  lastOrderAt?: string;
}

export function ConsumptionStats({
  totalOrderAmountFen,
  totalOrderCount,
  lastOrderAt,
}: ConsumptionStatsProps): React.ReactElement {
  const lastVisit = lastOrderAt
    ? dayjs(lastOrderAt).fromNow()
    : '暂无记录';

  const avgPerOrder =
    totalOrderCount > 0
      ? fenToYuan(Math.round(totalOrderAmountFen / totalOrderCount))
      : '—';

  return (
    <div className="flex gap-2">
      <StatCard
        label="累计消费"
        value={fenToYuan(totalOrderAmountFen)}
      />
      <StatCard
        label="订单数"
        value={`${totalOrderCount}单`}
        sub={`均 ${avgPerOrder}`}
      />
      <StatCard
        label="上次到店"
        value={lastVisit}
      />
    </div>
  );
}
