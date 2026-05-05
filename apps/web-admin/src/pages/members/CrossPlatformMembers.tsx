/**
 * CrossPlatformMembers — 全域会员（跨平台 Golden ID 关联概览）
 *
 * 展示：
 * - 各渠道（美团/饿了么/抖音/微信/高德/淘宝）绑定数量统计卡片
 * - 最近跨渠道关联会员列表（姓名、脱敏手机号、已关联渠道标签、累计消费、最近消费时间）
 *
 * 数据源：
 * - GET /api/v1/member/golden-id/stats         → 各渠道绑定统计
 * - GET /api/v1/members?has_golden_id=true     → 已关联 Golden ID 的会员列表
 */
import React, { useState, useEffect } from 'react';
import { txFetchData } from '../../api';

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface ChannelStat {
  channel: string;
  label: string;
  count: number;
}

interface CrossChannelMember {
  customer_id: string;
  name: string;
  phone_masked: string;
  channels: string[];
  total_spend_fen: number;
  last_order_at: string;
}

interface StatsResponse {
  channels: ChannelStat[];
  total_members: number;
}

interface MembersResponse {
  items: CrossChannelMember[];
  total: number;
}

// ── 渠道显示映射 ──────────────────────────────────────────────────────────────

const CHANNELS: Record<string, { label: string; color: string }> = {
  dine_in: { label: '堂食', color: 'bg-blue-100 text-blue-700' },
  meituan: { label: '美团', color: 'bg-orange-100 text-orange-700' },
  eleme:   { label: '饿了么', color: 'bg-cyan-100 text-cyan-700' },
  douyin:  { label: '抖音', color: 'bg-gray-100 text-gray-700' },
  wechat:  { label: '微信', color: 'bg-green-100 text-green-700' },
  amap:    { label: '高德', color: 'bg-indigo-100 text-indigo-700' },
  taobao:  { label: '淘宝', color: 'bg-yellow-100 text-yellow-700' },
};

const CHANNEL_CARD_COLORS: Record<string, string> = {
  dine_in: 'border-l-blue-500',
  meituan: 'border-l-orange-500',
  eleme:   'border-l-cyan-500',
  douyin:  'border-l-gray-500',
  wechat:  'border-l-green-500',
  amap:    'border-l-indigo-500',
  taobao:  'border-l-yellow-500',
};

// ── 格式化工具 ─────────────────────────────────────────────────────────────────

function formatFen(fen: number): string {
  return `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return dateStr;
  }
}

// ── 主组件 ─────────────────────────────────────────────────────────────────────

export default function CrossPlatformMembers() {
  const [channelStats, setChannelStats] = useState<ChannelStat[]>([]);
  const [totalMembers, setTotalMembers] = useState(0);
  const [members, setMembers] = useState<CrossChannelMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [statsData, memberData] = await Promise.all([
          txFetchData<StatsResponse>('/api/v1/member/golden-id/stats'),
          txFetchData<MembersResponse>('/api/v1/members?has_golden_id=true&size=50'),
        ]);
        if (cancelled) return;
        setChannelStats(statsData.channels ?? []);
        setTotalMembers(statsData.total_members ?? 0);
        setMembers(memberData.items ?? []);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : '加载全域会员数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, []);

  // ── 加载中 ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500">
        <svg className="animate-spin h-5 w-5 mr-2 text-blue-500" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        加载中...
      </div>
    );
  }

  // ── 错误状态 ───────────────────────────────────────────────────────────────

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-red-600 text-sm">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm transition-colors"
        >
          重试
        </button>
      </div>
    );
  }

  // ── 空数据 ─────────────────────────────────────────────────────────────────

  const hasData = channelStats.length > 0 || members.length > 0;

  if (!hasData) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-slate-800 mb-1">全域会员</h1>
        <p className="text-sm text-slate-500 mb-6">跨平台会员身份打通 · Golden ID</p>
        <div className="text-center py-16 text-slate-400">
          <p className="text-5xl mb-4">👤</p>
          <p className="text-lg">暂无跨渠道会员数据</p>
          <p className="text-sm mt-1">等待各渠道会员数据接入后，此处将展示全平台会员关联概览</p>
        </div>
      </div>
    );
  }

  const linkedCount = members.length;
  const totalFromStats = channelStats.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* 页头 */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">全域会员</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          跨平台会员身份打通 · Golden ID ·
          <span className="font-medium text-slate-600"> {totalMembers || linkedCount} 位已关联会员</span>
        </p>
      </div>

      {/* 统计卡片：各渠道绑定数 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-8">
        {channelStats.map((stat) => {
          const cfg = CHANNELS[stat.channel] ?? { label: stat.channel, color: 'bg-slate-100 text-slate-700' };
          const borderColor = CHANNEL_CARD_COLORS[stat.channel] ?? 'border-l-slate-400';
          return (
            <div
              key={stat.channel}
              className={`bg-white rounded-lg border border-slate-200 border-l-4 ${borderColor} p-4 shadow-sm`}
            >
              <div className="text-2xl font-bold text-slate-800">{stat.count}</div>
              <div className="text-xs text-slate-500 mt-0.5">{cfg.label}</div>
            </div>
          );
        })}
      </div>

      {/* 汇总行：总绑定数 + 唯一会员数 */}
      <div className="flex items-center gap-4 mb-4 text-sm text-slate-500">
        <span>
          渠道绑定总数：
          <span className="font-semibold text-slate-700">{totalFromStats}</span>
        </span>
        <span className="text-slate-300">|</span>
        <span>
          最近绑定会员（近50位）：
          <span className="font-semibold text-slate-700">{linkedCount}</span>
        </span>
      </div>

      {/* 跨渠道绑定会员表格 */}
      {members.length > 0 ? (
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-3 text-left text-slate-600 font-medium">顾客</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">手机号</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">已关联渠道</th>
                <th className="px-4 py-3 text-right text-slate-600 font-medium">累计消费</th>
                <th className="px-4 py-3 text-left text-slate-600 font-medium">最近消费</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {members.map((m) => (
                <tr key={m.customer_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {m.name || '未命名'}
                  </td>
                  <td className="px-4 py-3 text-slate-500 font-mono text-xs">
                    {m.phone_masked || '-'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {m.channels.map((c) => {
                        const cfg = CHANNELS[c] ?? { label: c, color: 'bg-slate-100 text-slate-700' };
                        return (
                          <span
                            key={c}
                            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cfg.color}`}
                          >
                            {cfg.label}
                          </span>
                        );
                      })}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-slate-800">
                    {formatFen(m.total_spend_fen)}
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    {formatDate(m.last_order_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm text-center py-12 text-slate-400">
          暂无跨渠道关联会员记录
        </div>
      )}
    </div>
  );
}
