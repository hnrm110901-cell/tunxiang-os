/**
 * MarketingPage — Cool Path 营销活动总览（V4 sprint D5b 2026-05-07）
 *
 * D1 sign-off C2 (cool path)：营销活动 / 优惠券规则。
 * 这是 V4 hot/cool 边界 cool path 的入口屏；具体业务逻辑由后续 sprint 实装，
 * D5b 仅补缺口 ensure D6 真机回归 cool path 路由跑通。
 *
 * 路由：/marketing
 */
import { useState } from 'react';

interface CampaignSummary {
  id: string;
  name: string;
  status: 'draft' | 'active' | 'paused' | 'ended';
  channel: string;
  startDate: string;
  endDate: string;
  participants: number;
}

const mockCampaigns: CampaignSummary[] = [
  { id: 'c1', name: '春节家宴 8 折', status: 'active', channel: '堂食 + 美团', startDate: '2026-01-20', endDate: '2026-02-15', participants: 1287 },
  { id: 'c2', name: '会员日次卡满减', status: 'active', channel: '会员小程序', startDate: '2026-05-01', endDate: '2026-05-31', participants: 420 },
  { id: 'c3', name: '工作日午市赠饮', status: 'paused', channel: '堂食', startDate: '2026-04-01', endDate: '2026-06-30', participants: 89 },
  { id: 'c4', name: '618 储值卡充返', status: 'draft', channel: '会员小程序 + 总部', startDate: '2026-06-15', endDate: '2026-06-20', participants: 0 },
];

const statusBadge: Record<CampaignSummary['status'], { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'bg-gray-200 text-gray-700' },
  active: { label: '进行中', cls: 'bg-green-100 text-green-700' },
  paused: { label: '已暂停', cls: 'bg-yellow-100 text-yellow-700' },
  ended: { label: '已结束', cls: 'bg-gray-300 text-gray-600' },
};

export function MarketingPage(): JSX.Element {
  const [filter, setFilter] = useState<CampaignSummary['status'] | 'all'>('all');

  const filtered = filter === 'all' ? mockCampaigns : mockCampaigns.filter((c) => c.status === filter);

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">营销活动</h1>
          <p className="text-sm text-gray-500 mt-1">
            总部 + 门店活动统一管理 · Cool Path · D5b 骨架
          </p>
        </div>
        <a
          href="/campaigns/new"
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg shadow-sm font-medium"
        >
          + 新建活动
        </a>
      </header>

      <nav className="flex gap-2 mb-4">
        {(['all', 'active', 'paused', 'draft', 'ended'] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setFilter(k)}
            className={`px-3 py-1.5 rounded-md text-sm font-medium ${
              filter === k ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 border'
            }`}
          >
            {k === 'all' ? '全部' : statusBadge[k].label}
          </button>
        ))}
      </nav>

      <div className="bg-white rounded-lg shadow-sm overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-100 text-gray-700">
            <tr>
              <th className="px-4 py-3">活动名称</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3">渠道</th>
              <th className="px-4 py-3">起止日期</th>
              <th className="px-4 py-3 text-right">参与人次</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id} className="border-t hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{c.name}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs ${statusBadge[c.status].cls}`}>
                    {statusBadge[c.status].label}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600">{c.channel}</td>
                <td className="px-4 py-3 text-gray-500">{c.startDate} ~ {c.endDate}</td>
                <td className="px-4 py-3 text-right tabular-nums">{c.participants.toLocaleString()}</td>
                <td className="px-4 py-3 text-right">
                  <a href={`/campaigns/${c.id}`} className="text-blue-600 hover:underline text-sm">查看 →</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="p-12 text-center text-gray-400">该状态下暂无活动</div>
        )}
      </div>

      {/* TODO(post-V4): 接入真实 API（tx-growth :8004 / tx-member :8003 营销路由）
          + 跨品牌过滤 + Agent 决策弹窗（cool path C3）建议的活动 */}
    </div>
  );
}
