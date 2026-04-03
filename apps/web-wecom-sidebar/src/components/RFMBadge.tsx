/**
 * RFMBadge.tsx — RFM 等级徽章 + R/F/M 分值显示
 *
 * S1 紫色 VIP     — 最高价值客户
 * S2 金色         — 高价值客户
 * S3 蓝色         — 中等价值客户
 * S4 灰色         — 低活跃客户
 * S5 红色警示     — 高流失风险客户
 */
import React from 'react';
import type { RfmLevel } from '../types';

interface RFMBadgeProps {
  rfmLevel: RfmLevel;
  rScore: number;
  fScore: number;
  mScore: number;
}

const RFM_STYLE: Record<
  RfmLevel,
  { label: string; bgClass: string; textClass: string; dotClass: string }
> = {
  S1: {
    label: 'VIP 尊享',
    bgClass: 'bg-purple-50',
    textClass: 'text-purple-700',
    dotClass: 'bg-purple-500',
  },
  S2: {
    label: '高价值',
    bgClass: 'bg-amber-50',
    textClass: 'text-amber-700',
    dotClass: 'bg-amber-500',
  },
  S3: {
    label: '成长中',
    bgClass: 'bg-blue-50',
    textClass: 'text-blue-700',
    dotClass: 'bg-blue-500',
  },
  S4: {
    label: '低活跃',
    bgClass: 'bg-gray-100',
    textClass: 'text-gray-600',
    dotClass: 'bg-gray-400',
  },
  S5: {
    label: '高风险',
    bgClass: 'bg-red-50',
    textClass: 'text-red-700',
    dotClass: 'bg-red-500',
  },
};

function ScorePill({
  label,
  score,
}: {
  label: string;
  score: number;
}): React.ReactElement {
  return (
    <span className="inline-flex items-center gap-0.5 text-xs text-tx-text-2">
      <span className="font-medium text-tx-text-1">{label}</span>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={`w-1.5 h-1.5 rounded-full ${
            n <= score ? 'bg-tx-primary' : 'bg-tx-border'
          }`}
        />
      ))}
    </span>
  );
}

export function RFMBadge({
  rfmLevel,
  rScore,
  fScore,
  mScore,
}: RFMBadgeProps): React.ReactElement {
  const style = RFM_STYLE[rfmLevel] ?? RFM_STYLE.S4;

  return (
    <div className="flex flex-col gap-2">
      {/* 等级徽章 */}
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                    ${style.bgClass} ${style.textClass} w-fit`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${style.dotClass}`} />
        <span className="text-xs font-semibold">
          {rfmLevel} · {style.label}
        </span>
      </div>

      {/* R / F / M 分值 */}
      <div className="flex items-center gap-3 flex-wrap">
        <ScorePill label="R" score={rScore} />
        <ScorePill label="F" score={fScore} />
        <ScorePill label="M" score={mScore} />
      </div>
    </div>
  );
}
