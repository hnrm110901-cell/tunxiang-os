/** 跨平台菜品状态看板 — 一次编辑，各渠道状态一目了然 */
import React, { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../api';

interface DishChannelStatus {
  dish_id: string;
  dish_name: string;
  category: string;
  channels: Record<string, 'online' | 'offline' | 'unknown'>;
  stock: number;
  bom_remaining: number;
}

const CHANNELS = [
  { key: 'dine_in', label: '堂食' },
  { key: 'meituan', label: '美团' },
  { key: 'eleme', label: '饿了么' },
  { key: 'douyin', label: '抖音' },
  { key: 'amap', label: '高德' },
  { key: 'taobao', label: '淘宝' },
  { key: 'miniapp', label: '小程序' },
];

function statusColor(s: string): string {
  if (s === 'online') return 'bg-green-100 text-green-700';
  if (s === 'offline') return 'bg-red-100 text-red-700';
  return 'bg-gray-100 text-gray-500';
}

function statusLabel(s: string): string {
  if (s === 'online') return '上架';
  if (s === 'offline') return '下架';
  return '未配置';
}

export default function ChannelMenuStatus() {
  const [dishes, setDishes] = useState<DishChannelStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await txFetchData<{ items: DishChannelStatus[] }>(
        '/api/v1/menu/channel-overrides/effective-menu?all=true',
      );
      setDishes(data.items ?? []);
    } catch {
      setDishes([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = filter
    ? dishes.filter(d => d.dish_name.includes(filter) || d.category.includes(filter))
    : dishes;

  if (loading) return <div className="p-6 text-gray-500">加载中...</div>;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-2">跨平台菜品管理</h1>
      <p className="text-sm text-gray-500 mb-6">
        统一管理各渠道菜品上下架状态。库存售罄时自动下架所有外卖平台。
      </p>

      <div className="flex gap-3 mb-4">
        <input
          type="text"
          placeholder="搜索菜品名称或分类..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="border rounded px-3 py-2 text-sm w-80"
        />
        <button
          onClick={load}
          className="px-4 py-2 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
        >
          刷新
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              <th className="px-4 py-3 text-left w-32">菜品</th>
              <th className="px-4 py-3 text-left w-20">分类</th>
              <th className="px-4 py-3 text-center w-16">库存</th>
              {CHANNELS.map(c => (
                <th key={c.key} className="px-3 py-3 text-center w-16">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {filtered.map(d => (
              <tr key={d.dish_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{d.dish_name}</td>
                <td className="px-4 py-3 text-gray-500">{d.category}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`font-bold ${d.bom_remaining === 0 ? 'text-red-600' : 'text-green-600'}`}>
                    {d.bom_remaining}
                  </span>
                </td>
                {CHANNELS.map(c => (
                  <td key={c.key} className="px-3 py-3 text-center">
                    <span className={`inline-block px-2 py-1 rounded text-xs font-medium ${statusColor(d.channels[c.key] ?? 'unknown')}`}>
                      {statusLabel(d.channels[c.key] ?? 'unknown')}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <div className="text-center py-12 text-gray-400">暂无菜品数据</div>
      )}

      <div className="mt-4 text-xs text-gray-400">
        共 {filtered.length} 个菜品 · 7 个渠道 · 库存为 0 时自动暂停所有外卖平台
      </div>
    </div>
  );
}
