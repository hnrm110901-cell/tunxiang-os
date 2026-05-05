/**
 * OmniChannelOrders — 全渠道订单管理
 * P1 G3: 多渠道订单列表/筛选/统计
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  fetchOrders,
  fetchOrderStats,
  type OrderSummary,
  type OrderStats,
} from '../../api/orderHub';

// ─── 常量 ───

const PLATFORMS = [
  { value: '', label: '全部平台' },
  { value: 'meituan', label: '美团' },
  { value: 'eleme', label: '饿了么' },
  { value: 'douyin', label: '抖音' },
  { value: 'amap', label: '高德' },
  { value: 'taobao', label: '淘宝' },
];

const STATUSES = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待接单' },
  { value: 'confirmed', label: '已接单' },
  { value: 'preparing', label: '制作中' },
  { value: 'ready', label: '待取餐' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
];

// ─── 工具函数 ───

function formatFen(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function statusLabel(s: string): string {
  return STATUSES.find((x) => x.value === s)?.label ?? s;
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'pending':
      return 'bg-yellow-100 text-yellow-800';
    case 'confirmed':
    case 'preparing':
    case 'ready':
      return 'bg-blue-100 text-blue-800';
    case 'completed':
      return 'bg-green-100 text-green-800';
    case 'cancelled':
      return 'bg-red-100 text-red-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

// ─── 子组件 ───

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  const colors: Record<string, string> = {
    blue: 'bg-blue-50 text-blue-700',
    yellow: 'bg-yellow-50 text-yellow-700',
    green: 'bg-green-50 text-green-700',
    gray: 'bg-gray-50 text-gray-700',
    red: 'bg-red-50 text-red-700',
  };
  return (
    <div className={`rounded-lg p-4 ${colors[color] ?? colors.gray}`}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-sm opacity-80">{label}</div>
    </div>
  );
}

// ─── 主组件 ───

export default function OmniChannelOrders() {
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [stats, setStats] = useState<OrderStats | null>(null);
  const [platform, setPlatform] = useState('');
  const [status, setStatus] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [orderData, statsData] = await Promise.all([
        fetchOrders({ platform, status, keyword, page, size: 20 }),
        fetchOrderStats({ platform }),
      ]);
      setOrders(orderData.items);
      setTotal(orderData.total);
      setStats(statsData);
    } finally {
      setLoading(false);
    }
  }, [platform, status, keyword, page]);

  useEffect(() => {
    load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / 20));

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <h1 className="text-2xl font-bold mb-4 text-gray-900">全渠道订单</h1>

      {/* 统计栏 */}
      {stats && (
        <div className="grid grid-cols-5 gap-4 mb-6">
          <StatCard label="总订单" value={stats.total_orders} color="blue" />
          <StatCard label="待接单" value={stats.pending} color="yellow" />
          <StatCard label="进行中" value={stats.active} color="green" />
          <StatCard label="已完成" value={stats.completed} color="gray" />
          <StatCard label="已取消" value={stats.cancelled} color="red" />
        </div>
      )}

      {/* 筛选栏 */}
      <div className="flex gap-3 mb-4 flex-wrap items-center">
        <select
          value={platform}
          onChange={(e) => {
            setPlatform(e.target.value);
            setPage(1);
          }}
          className="border rounded px-3 py-2 text-sm bg-white"
        >
          {PLATFORMS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>

        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="border rounded px-3 py-2 text-sm bg-white"
        >
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>

        <input
          type="text"
          placeholder="搜索订单号 / 手机号..."
          value={keyword}
          onChange={(e) => {
            setKeyword(e.target.value);
            setPage(1);
          }}
          className="border rounded px-3 py-2 text-sm flex-1 min-w-[200px]"
        />
      </div>

      {/* 表格 */}
      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 border-b">
            <tr>
              <th className="px-4 py-3 text-left font-medium">平台</th>
              <th className="px-4 py-3 text-left font-medium">平台单号</th>
              <th className="px-4 py-3 text-left font-medium">状态</th>
              <th className="px-4 py-3 text-right font-medium">金额</th>
              <th className="px-4 py-3 text-left font-medium">手机号</th>
              <th className="px-4 py-3 text-left font-medium">时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && orders.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  加载中...
                </td>
              </tr>
            ) : orders.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                  暂无订单
                </td>
              </tr>
            ) : (
              orders.map((o) => (
                <tr
                  key={o.id}
                  className="hover:bg-gray-50 cursor-pointer transition-colors"
                  onClick={() => {
                    window.location.hash = `#/orders/${o.id}`;
                  }}
                >
                  <td className="px-4 py-3">
                    <span className="inline-block px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-800">
                      {PLATFORMS.find((p) => p.value === o.platform)?.label ??
                        o.platform}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">
                    {o.platform_order_id}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-1 rounded text-xs font-medium ${statusBadgeClass(o.status)}`}
                    >
                      {statusLabel(o.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-gray-900">
                    {formatFen(o.total_fen)}
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {o.customer_phone || '-'}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {o.created_at}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      {total > 20 && (
        <div className="flex justify-center items-center gap-3 mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
          >
            上一页
          </button>
          <span className="text-sm text-gray-500">
            第 {page} / {totalPages} 页（共 {total} 条）
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= totalPages}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
