import React from 'react';
import { Tag } from 'antd';

interface MarginTagProps {
  margin: number;       // 0-1 的小数（如 0.45 表示 45%）
  threshold?: number;   // 毛利底线，默认 0.4
}

export const MarginTag: React.FC<MarginTagProps> = ({ margin, threshold = 0.4 }) => {
  const pct = (margin * 100).toFixed(1);

  let color: string;
  if (margin >= threshold) {
    color = 'success';
  } else if (margin >= threshold * 0.8) {
    color = 'warning';
  } else {
    color = 'error';
  }

  return <Tag color={color}>{pct}%</Tag>;
};
