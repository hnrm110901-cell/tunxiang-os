/**
 * PinnedInsightsFeed — 驾驶舱"已 Pin 洞察"区块
 *
 * S4-04 PR2.D / Tier 2 — 用户在 AgentConsole.chat 中 Pin 的 AI 洞察卡片在此展示。
 *
 * 数据流：
 *   GET  /api/v1/dashboard/pins   → 列 active Pin（最新在前，最多 20 条）
 *   每张卡 surface_snapshot 经 A2UIRenderer 渲染（与 chat 中渲染同源）
 *   "取消 Pin" 按钮 → DELETE /api/v1/dashboard/pins/{pin_id}（幂等）
 *
 * RLS：tenant 过滤完全由 backend USING 子句承担，前端不带 tenant_id 参数。
 */
import { useCallback, useEffect, useState } from 'react';

import { A2UIRenderer } from '../a2ui';
import type { A2UIDeclaration } from '../a2ui/types';
import {
  type PinnedItem,
  deletePin,
  listPinnedInsights,
} from '../../api/pinnedDashboard';

export function PinnedInsightsFeed() {
  const [pins, setPins] = useState<PinnedItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listPinnedInsights();
      setPins(resp.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleUnpin = useCallback(
    async (pinId: string) => {
      try {
        await deletePin(pinId);
        // 乐观更新（即使 backend 返 deleted=false 也从前端移除，再次 list 时纠正）
        setPins((prev) => prev.filter((p) => p.pin_id !== pinId));
      } catch (e) {
        setError(e instanceof Error ? e.message : '取消 Pin 失败');
      }
    },
    [],
  );

  return (
    <div
      style={{
        background: '#FFF',
        border: '1px solid #E8E6E1',
        borderRadius: 8,
        padding: 16,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: '#1A1A1A' }}>
          📌 已 Pin 洞察
          {pins.length > 0 && (
            <span style={{ marginLeft: 8, fontSize: 12, color: '#5F5E5A', fontWeight: 400 }}>
              （{pins.length} 条）
            </span>
          )}
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          style={{
            border: '1px solid #E8E6E1',
            background: '#FFF',
            color: '#5F5E5A',
            fontSize: 12,
            padding: '4px 10px',
            borderRadius: 6,
            cursor: loading ? 'wait' : 'pointer',
          }}
        >
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {error && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: 12,
            color: '#CF1322',
            background: '#FFF1F0',
            border: '1px solid #FFA39E',
            marginBottom: 12,
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {!loading && pins.length === 0 && !error && (
        <div
          style={{
            color: '#B4B2A9',
            fontSize: 13,
            padding: '24px 0',
            textAlign: 'center',
            lineHeight: 1.6,
          }}
        >
          还没有 Pin 的洞察
          <div style={{ fontSize: 11, marginTop: 4 }}>
            在右侧 AI 对话中点击 📌 把回答保存到这里
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {pins.map((p) => (
          <PinCard key={p.pin_id} pin={p} onUnpin={handleUnpin} />
        ))}
      </div>
    </div>
  );
}

function PinCard({
  pin,
  onUnpin,
}: {
  pin: PinnedItem;
  onUnpin: (pinId: string) => void;
}) {
  // surface_snapshot 在 backend 是 Record<string, unknown> JSONB，
  // 这里 type-assert 为 A2UIDeclaration（chat 写入时即此 shape）
  const declaration = pin.surface_snapshot as unknown as A2UIDeclaration;
  const pinnedAt = new Date(pin.pinned_at);

  return (
    <div
      style={{
        border: '1px solid #E8E6E1',
        borderRadius: 8,
        padding: 12,
        background: '#FAFAF8',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
          fontSize: 11,
          color: '#5F5E5A',
        }}
      >
        <span>
          {pin.source_natural_query ? `「${pin.source_natural_query}」` : '已 Pin'}
          <span style={{ marginLeft: 8, color: '#B4B2A9' }}>
            {pinnedAt.toLocaleString('zh-CN', {
              month: '2-digit',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </span>
        <button
          onClick={() => onUnpin(pin.pin_id)}
          style={{
            border: 'none',
            background: 'transparent',
            color: '#5F5E5A',
            fontSize: 11,
            cursor: 'pointer',
            padding: '2px 6px',
            borderRadius: 4,
          }}
          title="从驾驶舱移除"
        >
          取消 Pin
        </button>
      </div>
      <A2UIRenderer declaration={declaration} />
    </div>
  );
}
