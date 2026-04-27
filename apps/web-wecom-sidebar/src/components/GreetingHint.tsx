/**
 * GreetingHint.tsx — AI话术建议卡片
 */
import React from 'react';

interface GreetingHintProps {
  hint: string;
}

export function GreetingHint({ hint }: GreetingHintProps): React.ReactElement {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-tx-md p-3">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-amber-500 text-sm">💡</span>
        <span className="text-xs font-semibold text-amber-700">服务话术建议</span>
      </div>
      <p className="text-sm text-amber-900 leading-relaxed">
        {hint}
      </p>
    </div>
  );
}
