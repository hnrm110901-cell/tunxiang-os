/**
 * ProfileTagsTab.tsx — 会员标签Tab
 *
 * 企微客户标签(可编辑) + 口味偏好标签(只读) + 场景标签(只读) + 自定义标签添加
 */
import React, { useState, useCallback } from 'react';
import type { CustomerProfile } from '../types';
import { updateCustomerTags } from '../api/memberApi';

interface ProfileTagsTabProps {
  customer: CustomerProfile;
  onRefresh: () => void;
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

const PRESET_TAGS = [
  '高消费', '常客', '商务宴请', '家庭聚餐', '过生日',
  '口味清淡', '不辣', '海鲜爱好者', '素食', '需要发票',
];

export function ProfileTagsTab({ customer, onRefresh }: ProfileTagsTabProps): React.ReactElement {
  const [editingTags, setEditingTags] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(customer.tags));
  const [saving, setSaving] = useState(false);
  const [customTagInput, setCustomTagInput] = useState('');

  const startEdit = useCallback(() => {
    setSelected(new Set(customer.tags));
    setEditingTags(true);
  }, [customer.tags]);

  const toggleTag = useCallback((tag: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(tag) ? next.delete(tag) : next.add(tag);
      return next;
    });
  }, []);

  const addCustomTag = useCallback(() => {
    const tag = customTagInput.trim();
    if (tag && !selected.has(tag)) {
      setSelected((prev) => new Set(prev).add(tag));
      setCustomTagInput('');
    }
  }, [customTagInput, selected]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await updateCustomerTags(customer.customer_id, Array.from(selected));
      setEditingTags(false);
      onRefresh();
    } catch {
      // 保持状态让用户重试
    } finally {
      setSaving(false);
    }
  }, [customer.customer_id, selected, onRefresh]);

  const handleCancel = useCallback(() => {
    setSelected(new Set(customer.tags));
    setEditingTags(false);
  }, [customer.tags]);

  return (
    <div className="px-4 pb-4">
      {/* ── 企微客户标签(可编辑) ── */}
      <div className="flex items-center justify-between mb-2">
        <SectionTitle>客户标签</SectionTitle>
        {!editingTags ? (
          <button
            onClick={startEdit}
            className="text-xs text-tx-primary font-medium"
          >
            编辑
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={handleCancel}
              className="text-xs text-tx-text-3"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-xs text-tx-primary font-medium disabled:opacity-50"
            >
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        )}
      </div>

      {editingTags ? (
        <>
          {/* 编辑模式: 预设标签 */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {PRESET_TAGS.map((tag) => {
              const active = selected.has(tag);
              return (
                <button
                  key={tag}
                  onClick={() => toggleTag(tag)}
                  className={`px-2.5 py-1 rounded-full text-xs transition-colors duration-150
                    ${active
                      ? 'bg-tx-primary text-white'
                      : 'bg-tx-bg-2 text-tx-text-2 border border-tx-border'
                    }`}
                >
                  {tag}
                </button>
              );
            })}
          </div>

          {/* 已选的自定义标签 */}
          {Array.from(selected).filter((t) => !PRESET_TAGS.includes(t)).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {Array.from(selected)
                .filter((t) => !PRESET_TAGS.includes(t))
                .map((tag) => (
                  <button
                    key={tag}
                    onClick={() => toggleTag(tag)}
                    className="px-2.5 py-1 rounded-full text-xs bg-tx-primary text-white"
                  >
                    {tag} ✕
                  </button>
                ))}
            </div>
          )}

          {/* 添加自定义标签 */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={customTagInput}
              onChange={(e) => setCustomTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addCustomTag();
                }
              }}
              placeholder="输入自定义标签..."
              maxLength={20}
              className="flex-1 px-3 py-1.5 text-xs bg-tx-bg-2 border border-tx-border
                         rounded-tx-md focus:outline-none focus:border-tx-primary
                         transition-colors placeholder:text-tx-text-3"
            />
            <button
              onClick={addCustomTag}
              disabled={!customTagInput.trim()}
              className="px-3 py-1.5 bg-tx-primary text-white text-xs rounded-tx-md
                         disabled:opacity-30"
            >
              +
            </button>
          </div>
        </>
      ) : (
        /* 展示模式 */
        <div className="flex flex-wrap gap-1.5">
          {customer.tags.length > 0 ? (
            customer.tags.map((tag) => (
              <span
                key={tag}
                className="inline-block px-2 py-0.5 bg-tx-primary-light text-tx-primary
                           text-xs rounded-full font-medium"
              >
                {tag}
              </span>
            ))
          ) : (
            <p className="text-xs text-tx-text-3">暂无标签</p>
          )}
        </div>
      )}

      <Divider />

      {/* ── 口味偏好标签(只读) ── */}
      <SectionTitle>口味偏好</SectionTitle>
      <div className="flex flex-wrap gap-1.5">
        {(customer.taste_tags ?? []).length > 0 ? (
          (customer.taste_tags ?? []).map((tag) => (
            <span
              key={tag}
              className="inline-block px-2 py-0.5 bg-orange-50 text-orange-600
                         text-xs rounded-full border border-orange-200"
            >
              {tag}
            </span>
          ))
        ) : (
          <p className="text-xs text-tx-text-3">暂无口味数据</p>
        )}
      </div>

      <Divider />

      {/* ── 场景标签(只读) ── */}
      <SectionTitle>消费场景</SectionTitle>
      <div className="flex flex-wrap gap-1.5">
        {(customer.scene_tags ?? []).length > 0 ? (
          (customer.scene_tags ?? []).map((tag) => (
            <span
              key={tag}
              className="inline-block px-2 py-0.5 bg-blue-50 text-blue-600
                         text-xs rounded-full border border-blue-200"
            >
              {tag}
            </span>
          ))
        ) : (
          <p className="text-xs text-tx-text-3">暂无场景数据</p>
        )}
      </div>

      <Divider />

      {/* ── 菜品偏好(只读) ── */}
      <SectionTitle>常点菜品</SectionTitle>
      <div className="flex flex-wrap gap-1.5">
        {customer.favorite_dishes.length > 0 ? (
          customer.favorite_dishes.slice(0, 8).map((dish) => (
            <span
              key={dish.name}
              className="inline-flex items-center gap-1 px-2 py-0.5
                         bg-tx-bg-2 text-tx-text-2 text-xs rounded-full border border-tx-border"
            >
              <span>🍽</span>
              <span>{dish.name}</span>
              <span className="text-tx-text-3">x{dish.order_times}</span>
            </span>
          ))
        ) : (
          <p className="text-xs text-tx-text-3">暂无菜品数据</p>
        )}
      </div>
    </div>
  );
}
