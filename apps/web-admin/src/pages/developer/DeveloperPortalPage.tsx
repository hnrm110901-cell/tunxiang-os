import React from 'react';

/**
 * DeveloperPortal — 第三方开发者集成门户
 *
 * 提供：
 *  - API 密钥管理
 *  - Webhook 订阅管理
 *  - API 文档入口
 *  - 集成状态监控
 */

// 示例 API 密钥列表
const MOCK_KEYS = [
  { id: '1', name: '生产环境', prefix: 'tx_aB3xK7...', created: '2026-05-01', status: 'active' },
  { id: '2', name: '测试环境', prefix: 'tx_mN9pQ2...', created: '2026-04-28', status: 'active' },
];

// 示例 Webhook 列表
const MOCK_WEBHOOKS = [
  { id: '1', url: 'https://api.myapp.com/webhooks/order', events: ['order.paid', 'order.created'], status: 'active' },
  { id: '2', url: 'https://api.myapp.com/webhooks/inventory', events: ['inventory.low'], status: 'active' },
];

export default function DeveloperPortalPage(): JSX.Element {
  const [activeTab, setActiveTab] = React.useState<'keys' | 'webhooks' | 'docs'>('keys');

  const tabs = [
    { key: 'keys' as const, label: 'API 密钥' },
    { key: 'webhooks' as const, label: 'Webhook 订阅' },
    { key: 'docs' as const, label: 'API 文档' },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">开发者门户</h1>
        <p className="text-gray-500 mt-1">管理你的 API 集成凭证和通知订阅</p>
      </div>

      {/* Tab Bar */}
      <div className="flex gap-1 mb-6 border-b">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.key
                ? 'border-orange-500 text-orange-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: API Keys */}
      {activeTab === 'keys' && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">API 密钥</h2>
            <button className="px-4 py-2 bg-orange-500 text-white rounded-lg text-sm hover:bg-orange-600">
              + 创建密钥
            </button>
          </div>
          <div className="bg-white rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">名称</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">密钥前缀</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">创建时间</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {MOCK_KEYS.map((k) => (
                  <tr key={k.id} className="border-b last:border-b-0">
                    <td className="px-4 py-3">{k.name}</td>
                    <td className="px-4 py-3 font-mono text-gray-500">{k.prefix}</td>
                    <td className="px-4 py-3 text-gray-500">{k.created}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        {k.status === 'active' ? '正常' : '已吊销'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-red-500 hover:text-red-700 text-xs">吊销</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 p-4 bg-blue-50 rounded-lg text-sm text-blue-800">
            <strong>安全性须知：</strong> API 密钥仅在创建时显示一次。请在创建后立即保存到安全位置。
          </div>
        </div>
      )}

      {/* Tab: Webhooks */}
      {activeTab === 'webhooks' && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Webhook 订阅</h2>
            <button className="px-4 py-2 bg-orange-500 text-white rounded-lg text-sm hover:bg-orange-600">
              + 添加订阅
            </button>
          </div>
          <div className="bg-white rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">回调 URL</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">订阅事件</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {MOCK_WEBHOOKS.map((w) => (
                  <tr key={w.id} className="border-b last:border-b-0">
                    <td className="px-4 py-3 font-mono text-xs">{w.url}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1 flex-wrap">
                        {w.events.map((e) => (
                          <span key={e} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-700">
                            {e}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        活跃
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-red-500 hover:text-red-700 text-xs">删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 p-4 bg-gray-50 rounded-lg text-sm text-gray-600">
            <h3 className="font-medium text-gray-900 mb-2">可用事件类型</h3>
            <div className="grid grid-cols-2 gap-2">
              {[
                'order.created', 'order.paid', 'order.cancelled',
                'menu.updated', 'inventory.low', 'member.registered',
              ].map((evt) => (
                <code key={evt} className="text-xs bg-white px-2 py-1 rounded border">{evt}</code>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab: API Docs */}
      {activeTab === 'docs' && (
        <div>
          <h2 className="text-lg font-semibold mb-4">API 文档</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              { title: '订单 API', desc: '创建、查询、管理订单', endpoint: 'GET /api/v1/orders' },
              { title: '菜单 API', desc: '菜品和分类管理', endpoint: 'GET /api/v1/menu' },
              { title: '会员 API', desc: '会员查询和积分管理', endpoint: 'GET /api/v1/members' },
              { title: '库存 API', desc: '库存查询和预警', endpoint: 'GET /api/v1/inventory' },
              { title: '财务报表 API', desc: '营业数据和报表', endpoint: 'GET /api/v1/finance' },
              { title: 'Webhook API', desc: '事件订阅管理', endpoint: 'POST /api/v1/developer/webhooks' },
            ].map((api) => (
              <div key={api.title} className="p-4 border rounded-lg hover:shadow-sm transition-shadow">
                <h3 className="font-medium text-gray-900">{api.title}</h3>
                <p className="text-sm text-gray-500 mt-1">{api.desc}</p>
                <code className="text-xs text-orange-600 mt-2 block">{api.endpoint}</code>
              </div>
            ))}
          </div>
          <div className="mt-6 p-4 bg-orange-50 rounded-lg text-sm">
            <p>完整的 API 文档请访问 <code className="text-orange-600 font-mono">/docs</code>（Swagger UI）或 <code className="text-orange-600 font-mono">/redoc</code>（ReDoc）。</p>
          </div>
        </div>
      )}
    </div>
  );
}
