/**
 * FoodSafetyPage — Cool Path 食安溯源/明厨亮灶/上报（V4 sprint D5b 2026-05-07）
 *
 * D1 sign-off C5 / C8 (cool path)：食安上报 + 食安溯源 + 明厨亮灶展示。
 * 路由：/food-safety
 *
 * 三段式骨架：
 *   1. 食材批次 + 保质期一览（采购溯源）
 *   2. 关键温度记录（冷藏/冷冻/留样）
 *   3. 食安上报记录（监管/内部）
 *
 * 业务实装由 tx-civic + tx-supply 后续 sprint 完成；D5b 仅占位 ensure D6
 * cool path 真机回归路由跑通。
 */
import { useState } from 'react';

type Tab = 'traceability' | 'temperature' | 'reports';

interface IngredientBatch {
  id: string;
  name: string;
  supplier: string;
  receivedAt: string;
  expiresAt: string;
  status: 'fresh' | 'near-expiry' | 'expired';
}

interface TempRecord {
  id: string;
  device: string;
  zone: string;
  reading: number;       // ℃
  threshold: { min: number; max: number };
  recordedAt: string;
  alarm: boolean;
}

interface SafetyReport {
  id: string;
  type: 'self-check' | 'gov-inspection' | 'incident';
  title: string;
  reportedAt: string;
  reporter: string;
  status: 'draft' | 'submitted' | 'closed';
}

const mockBatches: IngredientBatch[] = [
  { id: 'b1', name: '海鲈鱼（活）', supplier: '深海渔业', receivedAt: '2026-05-06 06:30', expiresAt: '2026-05-08', status: 'fresh' },
  { id: 'b2', name: '冷冻虾仁 5kg', supplier: '蓝海冻品', receivedAt: '2026-05-04 09:00', expiresAt: '2026-05-08', status: 'near-expiry' },
  { id: 'b3', name: '叶菜（油麦菜）', supplier: '本地农场', receivedAt: '2026-05-06 05:00', expiresAt: '2026-05-07', status: 'near-expiry' },
];

const mockTemps: TempRecord[] = [
  { id: 't1', device: '冷藏柜 #1', zone: '后厨主厨房', reading: 4.2, threshold: { min: 0, max: 8 }, recordedAt: '2026-05-07 14:00', alarm: false },
  { id: 't2', device: '冷冻柜 #2', zone: '后厨主厨房', reading: -16.5, threshold: { min: -20, max: -15 }, recordedAt: '2026-05-07 14:00', alarm: false },
  { id: 't3', device: '留样柜', zone: '食品安全间', reading: 6.8, threshold: { min: 0, max: 5 }, recordedAt: '2026-05-07 14:00', alarm: true },
];

const mockReports: SafetyReport[] = [
  { id: 'r1', type: 'self-check', title: '5月日常自查 - 厨房卫生', reportedAt: '2026-05-07', reporter: '李店长', status: 'submitted' },
  { id: 'r2', type: 'gov-inspection', title: '市监局季度检查', reportedAt: '2026-04-28', reporter: '总部食安部', status: 'closed' },
];

const batchStatusBadge: Record<IngredientBatch['status'], { label: string; cls: string }> = {
  fresh: { label: '新鲜', cls: 'bg-green-100 text-green-700' },
  'near-expiry': { label: '临期', cls: 'bg-yellow-100 text-yellow-700' },
  expired: { label: '过期', cls: 'bg-red-100 text-red-700' },
};

export function FoodSafetyPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('traceability');

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">食品安全</h1>
        <p className="text-sm text-gray-500 mt-1">
          食材溯源 · 关键温度 · 食安上报 · Cool Path · D5b 骨架
        </p>
      </header>

      <nav className="flex gap-2 mb-4 border-b">
        {(
          [
            { k: 'traceability', label: '食材溯源' },
            { k: 'temperature', label: '关键温度' },
            { k: 'reports', label: '上报记录' },
          ] as const
        ).map((t) => (
          <button
            key={t.k}
            type="button"
            onClick={() => setTab(t.k)}
            className={`px-4 py-2 text-sm font-medium border-b-2 ${
              tab === t.k ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-600'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'traceability' && (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-100 text-gray-700">
              <tr>
                <th className="px-4 py-3">食材</th>
                <th className="px-4 py-3">供应商</th>
                <th className="px-4 py-3">入库时间</th>
                <th className="px-4 py-3">效期</th>
                <th className="px-4 py-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {mockBatches.map((b) => (
                <tr key={b.id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{b.name}</td>
                  <td className="px-4 py-3 text-gray-600">{b.supplier}</td>
                  <td className="px-4 py-3 text-gray-500">{b.receivedAt}</td>
                  <td className="px-4 py-3 text-gray-500">{b.expiresAt}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs ${batchStatusBadge[b.status].cls}`}>
                      {batchStatusBadge[b.status].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'temperature' && (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-100 text-gray-700">
              <tr>
                <th className="px-4 py-3">设备</th>
                <th className="px-4 py-3">区域</th>
                <th className="px-4 py-3 text-right">温度 (℃)</th>
                <th className="px-4 py-3">阈值</th>
                <th className="px-4 py-3">记录时间</th>
                <th className="px-4 py-3">告警</th>
              </tr>
            </thead>
            <tbody>
              {mockTemps.map((t) => (
                <tr key={t.id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{t.device}</td>
                  <td className="px-4 py-3 text-gray-600">{t.zone}</td>
                  <td className={`px-4 py-3 text-right tabular-nums font-mono ${t.alarm ? 'text-red-600' : 'text-gray-900'}`}>
                    {t.reading.toFixed(1)}
                  </td>
                  <td className="px-4 py-3 text-gray-500 tabular-nums">[{t.threshold.min}, {t.threshold.max}]</td>
                  <td className="px-4 py-3 text-gray-500">{t.recordedAt}</td>
                  <td className="px-4 py-3">
                    {t.alarm ? <span className="text-red-600 font-medium">⚠️ 告警</span> : <span className="text-green-600">✓ 正常</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'reports' && (
        <div className="bg-white rounded-lg shadow-sm overflow-hidden">
          <div className="flex justify-between items-center p-4 border-b">
            <h2 className="font-medium text-gray-700">上报记录（自查 / 监管 / 事件）</h2>
            <button
              type="button"
              className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded text-sm font-medium"
              onClick={() => alert('(D5b 骨架) 新建上报')}
            >
              + 新建上报
            </button>
          </div>
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-100 text-gray-700">
              <tr>
                <th className="px-4 py-3">类型</th>
                <th className="px-4 py-3">标题</th>
                <th className="px-4 py-3">日期</th>
                <th className="px-4 py-3">上报人</th>
                <th className="px-4 py-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {mockReports.map((r) => (
                <tr key={r.id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-600">
                    {r.type === 'self-check' ? '自查' : r.type === 'gov-inspection' ? '监管' : '事件'}
                  </td>
                  <td className="px-4 py-3 font-medium">{r.title}</td>
                  <td className="px-4 py-3 text-gray-500">{r.reportedAt}</td>
                  <td className="px-4 py-3 text-gray-600">{r.reporter}</td>
                  <td className="px-4 py-3 text-gray-500">{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* TODO(post-V4):
          - tx-civic 食安上报路由真接入（kitchen_routes / food_safety_routes）
          - tx-supply 食材效期 / 留样 真接入
          - 明厨亮灶视频流嵌入（独立 RTSP / WebRTC，不阻塞 cool path）
          - Agent 决策弹窗（cool path C3）：临期/告警自动 push */}
    </div>
  );
}
