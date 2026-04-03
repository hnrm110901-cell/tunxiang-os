/**
 * ChurnRiskBar.tsx — 流失风险进度条
 *
 * risk_score 范围 0.0 - 1.0（来自 AI 模型输出）
 *   0%-30%  绿色（安全）
 *   30%-70% 黄色（注意）
 *   70%-100% 红色（高风险）
 */
import React from 'react';

interface ChurnRiskBarProps {
  riskScore: number; // 0.0 - 1.0
}

function getRiskStyle(score: number): {
  label: string;
  barClass: string;
  textClass: string;
  bgClass: string;
} {
  const pct = score * 100;
  if (pct < 30) {
    return {
      label: '安全',
      barClass: 'bg-tx-success',
      textClass: 'text-tx-success',
      bgClass: 'bg-green-50',
    };
  }
  if (pct < 70) {
    return {
      label: '注意',
      barClass: 'bg-tx-warning',
      textClass: 'text-tx-warning',
      bgClass: 'bg-amber-50',
    };
  }
  return {
    label: '高风险',
    barClass: 'bg-tx-danger',
    textClass: 'text-tx-danger',
    bgClass: 'bg-red-50',
  };
}

export function ChurnRiskBar({ riskScore }: ChurnRiskBarProps): React.ReactElement {
  const pct = Math.min(100, Math.max(0, Math.round(riskScore * 100)));
  const style = getRiskStyle(riskScore);

  return (
    <div className={`rounded-tx-md p-3 ${style.bgClass}`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-tx-text-2">流失风险</span>
        <span className={`text-xs font-semibold ${style.textClass}`}>
          {pct}% · {style.label}
        </span>
      </div>

      {/* 进度条 */}
      <div className="h-2 w-full rounded-full bg-tx-border overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${style.barClass} ${
            pct >= 70 ? 'animate-pulse' : ''
          }`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`流失风险 ${pct}%`}
        />
      </div>
    </div>
  );
}
