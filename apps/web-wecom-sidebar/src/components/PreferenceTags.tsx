/**
 * PreferenceTags.tsx — 偏好标签（CRM 标签 + 常点菜品）
 */
import React from 'react';
import type { FavoriteDish } from '../types';

interface PreferenceTagsProps {
  tags: string[];
  favoriteDishes: FavoriteDish[];
}

export function PreferenceTags({
  tags,
  favoriteDishes,
}: PreferenceTagsProps): React.ReactElement {
  const hasData = tags.length > 0 || favoriteDishes.length > 0;

  if (!hasData) {
    return (
      <p className="text-xs text-tx-text-3 py-1">暂无标签和偏好数据</p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* CRM 标签 */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-block px-2 py-0.5 bg-tx-primary-light text-tx-primary
                         text-xs rounded-full font-medium"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* 常点菜品 */}
      {favoriteDishes.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {favoriteDishes.slice(0, 5).map((dish) => (
            <span
              key={dish.name}
              className="inline-flex items-center gap-1 px-2 py-0.5
                         bg-tx-bg-2 text-tx-text-2 text-xs rounded-full border border-tx-border"
            >
              <span>🍽</span>
              <span>{dish.name}</span>
              <span className="text-tx-text-3">×{dish.order_times}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
