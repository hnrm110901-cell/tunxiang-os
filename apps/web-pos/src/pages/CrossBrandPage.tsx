/**
 * CrossBrandPage — Cool Path 跨品牌门店切换（V4 sprint D5b 2026-05-07）
 *
 * D1 sign-off C6 (cool path)：跨品牌 / 跨门店切换 UI。
 * 路由：/cross-brand
 *
 * 集团多品牌运营场景：
 *   - 一个集团（如徐记海鲜集团）下若干品牌（徐记 / 徐记小吃 / 徐记外送 / 中央厨房）
 *   - 每个品牌下若干门店
 *   - 操作员（区域督导 / 集团运营）需要跨品牌跨门店切换查看
 *
 * 此屏：列出当前账号有权访问的品牌树 + 当前 active 品牌/门店 + 切换交互
 *
 * 业务实装由 tx-org 后续 sprint 完成；D5b 骨架 ensure D6 cool path 路由跑通。
 */
import { useState } from 'react';

interface Brand {
  id: string;
  name: string;
  format: string;          // 品牌业态
  storeCount: number;
}

interface Store {
  id: string;
  name: string;
  brandId: string;
  city: string;
  status: 'active' | 'paused' | 'maintenance';
}

const mockBrands: Brand[] = [
  { id: 'b-xj', name: '徐记海鲜', format: '海鲜正餐', storeCount: 32 },
  { id: 'b-xj-sml', name: '徐记小吃', format: '小吃快餐', storeCount: 8 },
  { id: 'b-xj-ws', name: '徐记外送', format: '外送专门店', storeCount: 12 },
  { id: 'b-ck', name: '中央厨房', format: '集团 CK', storeCount: 1 },
];

const mockStores: Store[] = [
  { id: 's1', name: '徐记海鲜·解放西路店', brandId: 'b-xj', city: '长沙', status: 'active' },
  { id: 's2', name: '徐记海鲜·万达广场店', brandId: 'b-xj', city: '长沙', status: 'active' },
  { id: 's3', name: '徐记海鲜·武汉光谷店', brandId: 'b-xj', city: '武汉', status: 'active' },
  { id: 's4', name: '徐记小吃·五一广场店', brandId: 'b-xj-sml', city: '长沙', status: 'maintenance' },
  { id: 's5', name: '徐记外送·岳麓站', brandId: 'b-xj-ws', city: '长沙', status: 'active' },
  { id: 's6', name: '中央厨房·星沙基地', brandId: 'b-ck', city: '长沙', status: 'active' },
];

const storeStatusBadge: Record<Store['status'], { label: string; cls: string }> = {
  active: { label: '运营中', cls: 'bg-green-100 text-green-700' },
  paused: { label: '已暂停', cls: 'bg-yellow-100 text-yellow-700' },
  maintenance: { label: '维护中', cls: 'bg-blue-100 text-blue-700' },
};

export function CrossBrandPage(): JSX.Element {
  const [activeBrandId, setActiveBrandId] = useState<string>(mockBrands[0].id);
  const [activeStoreId, setActiveStoreId] = useState<string>(mockStores[0].id);

  const activeBrand = mockBrands.find((b) => b.id === activeBrandId);
  const activeStore = mockStores.find((s) => s.id === activeStoreId);
  const storesInBrand = mockStores.filter((s) => s.brandId === activeBrandId);

  const handleSwitchStore = (s: Store) => {
    setActiveStoreId(s.id);
    setActiveBrandId(s.brandId);
    // TODO(post-V4): POST /api/v1/session/switch-store
    //   + invalidate Repository caches in android-pos hot path（通过 mac-station WebSocket push）
    alert(`(D5b 骨架) 切换到：${s.name}`);
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">跨品牌切换</h1>
        <p className="text-sm text-gray-500 mt-1">
          集团多品牌 / 跨门店切换 · Cool Path · D5b 骨架
        </p>
      </header>

      {/* 当前 active 概览 */}
      <section className="bg-white rounded-lg shadow-sm p-4 mb-4 flex items-center justify-between">
        <div>
          <div className="text-xs text-gray-500 uppercase">当前会话</div>
          <div className="text-lg font-bold mt-1">
            {activeBrand?.name} · {activeStore?.name}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {activeBrand?.format} · {activeStore?.city}
          </div>
        </div>
        <button
          type="button"
          className="text-blue-600 hover:underline text-sm"
          onClick={() => alert('(D5b 骨架) 退出当前会话')}
        >
          退出当前会话 →
        </button>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* 品牌列表 */}
        <aside className="bg-white rounded-lg shadow-sm overflow-hidden">
          <h2 className="px-4 py-3 bg-gray-100 text-sm font-medium text-gray-700">品牌</h2>
          <ul className="divide-y">
            {mockBrands.map((b) => (
              <li key={b.id}>
                <button
                  type="button"
                  onClick={() => setActiveBrandId(b.id)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 ${
                    b.id === activeBrandId ? 'bg-blue-50 border-l-4 border-blue-600' : ''
                  }`}
                >
                  <div className="font-medium">{b.name}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{b.format} · {b.storeCount} 家门店</div>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        {/* 门店列表 */}
        <section className="md:col-span-2 bg-white rounded-lg shadow-sm overflow-hidden">
          <h2 className="px-4 py-3 bg-gray-100 text-sm font-medium text-gray-700">
            门店（{activeBrand?.name}）
          </h2>
          <ul className="divide-y">
            {storesInBrand.length === 0 && (
              <li className="px-4 py-8 text-center text-gray-400 text-sm">该品牌下无门店</li>
            )}
            {storesInBrand.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => handleSwitchStore(s)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between ${
                    s.id === activeStoreId ? 'bg-blue-50' : ''
                  }`}
                >
                  <div>
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-gray-500 mt-0.5">{s.city}</div>
                  </div>
                  <span className={`inline-block px-2 py-0.5 rounded text-xs ${storeStatusBadge[s.status].cls}`}>
                    {storeStatusBadge[s.status].label}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* TODO(post-V4):
          - tx-org /api/v1/session/switch-store API 真接入
          - 跨品牌权限校验（不同账号能看到的品牌树不同）
          - 切换时 invalidate android-pos hot path Repository 缓存
            （通过 mac-station WebSocket push）
          - 集团-品牌-业态-门店 4 层组织模型可视化（CLAUDE.md §六 治理）*/}
    </div>
  );
}
