/**
 * BirthdayBadge.tsx — 生日标记（7天内生日时显示）
 */
import React from 'react';

export function BirthdayBadge(): React.ReactElement {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-pink-100 text-pink-600 text-xs rounded-full">
      <span>🎂</span> 本周生日
    </span>
  );
}
