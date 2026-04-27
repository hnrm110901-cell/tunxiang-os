/**
 * Workspace: Adapters — 适配器管理（替代 v1 AdaptersPage）
 *
 * 左侧列表 + 右侧 Object Page (8 Tab) + 矩阵视图切换
 * 覆盖全部 15 个适配器
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { hubGet, hubPost } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型定义 ──

type AdapterStatus = 'healthy' | 'degraded' | 'error' | 'inactive';
type AdapterProtocol = 'REST' | 'SOAP' | 'WebSocket' | 'gRPC';
type FilterKey = 'all' | AdapterStatus;
type TabKey = 'overview' | 'timeline' | 'actions' | 'traces' | 'cost' | 'logs' | 'related' | 'playbooks';
type ViewMode = 'list' | 'matrix';

interface MerchantLink {
  name: string;
  status: 'normal' | 'slow' | 'error' | 'inactive';
  lastSync: string;
  successRate: number;
  p95Latency: number;
}

interface SyncEvent {
  id: string;
  time: string;
  type: 'success' | 'failure' | 'retry' | 'mapping_update' | 'version_upgrade';
  description: string;
}

interface FieldMapping {
  sourceField: string;
  targetField: string;
  status: 'mapped' | 'unmapped' | 'conflict';
}

interface AdapterItem {
  id: string;
  name: string;
  displayName: string;
  protocol: AdapterProtocol;
  version: string;
  lastUpdate: string;
  status: AdapterStatus;
  merchantsCount: number;
  successRate: number;
  p95Latency: number;
  todaySyncCount: number;
  failedRetryQueue: number;
  merchants: MerchantLink[];
  recentEvents: SyncEvent[];
  fieldMappings: FieldMapping[];
}

// ── Mock 数据 ──

const MERCHANTS = ['徐记海鲜', '尝在一起', '最黔线', '尚宫厨', '湘粤楼', '悦麻辣', '渝乡辣婆婆', '老碗会', '黔庄', '望湘园'];

function makeMerchants(count: number, adapter: string): MerchantLink[] {
  const shuffled = [...MERCHANTS].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, count).map(name => {
    const r = Math.random();
    const status: MerchantLink['status'] = r > 0.85 ? 'error' : r > 0.7 ? 'slow' : r > 0.05 ? 'normal' : 'inactive';
    return {
      name,
      status,
      lastSync: `2026-04-26 ${String(8 + Math.floor(Math.random() * 14)).padStart(2, '0')}:${String(Math.floor(Math.random() * 60)).padStart(2, '0')}`,
      successRate: status === 'error' ? 85 + Math.random() * 10 : status === 'slow' ? 95 + Math.random() * 4 : 99 + Math.random(),
      p95Latency: status === 'error' ? 500 + Math.floor(Math.random() * 300) : status === 'slow' ? 200 + Math.floor(Math.random() * 200) : 20 + Math.floor(Math.random() * 80),
    };
  });
}

function makeEvents(adapter: string): SyncEvent[] {
  return [
    { id: `${adapter}-e1`, time: '2026-04-26 09:30', type: 'success', description: '批量同步完成，1,240 条记录' },
    { id: `${adapter}-e2`, time: '2026-04-26 08:15', type: 'success', description: '增量同步，42 条更新' },
    { id: `${adapter}-e3`, time: '2026-04-25 22:00', type: 'failure', description: '同步超时，已加入重试队列' },
    { id: `${adapter}-e4`, time: '2026-04-25 18:30', type: 'retry', description: '重试成功，恢复同步' },
    { id: `${adapter}-e5`, time: '2026-04-25 14:00', type: 'mapping_update', description: '字段映射更新：新增 3 个字段' },
  ];
}

function makeMappings(adapter: string): FieldMapping[] {
  const sourceFields = [
    'order_id', 'order_time', 'total_amount', 'pay_type', 'customer_phone',
    'dish_name', 'dish_qty', 'discount_amount', 'table_no', 'store_code',
    'operator_name', 'remark', 'tax_amount', 'delivery_fee', 'channel_code',
  ];
  const targetFields = [
    'order.id', 'order.created_at', 'order.total_fen', 'order.payment_method', 'customer.phone',
    'dish.name', 'order_item.quantity', 'order.discount_fen', 'table.number', 'store.code',
    'employee.name', 'order.note', 'order.tax_fen', 'order.delivery_fee_fen', 'order.channel',
  ];
  return sourceFields.map((sf, i) => {
    const r = Math.random();
    return {
      sourceField: sf,
      targetField: r > 0.15 ? targetFields[i] : '',
      status: r > 0.15 ? (r > 0.9 ? 'conflict' : 'mapped') : 'unmapped',
    };
  });
}

const MOCK_ADAPTERS: AdapterItem[] = [
  { id: 'pinzhi', name: 'pinzhi', displayName: '品智POS', protocol: 'REST', version: '2.3.1', lastUpdate: '2026-04-20', status: 'healthy', merchantsCount: 6, successRate: 99.8, p95Latency: 45, todaySyncCount: 3420, failedRetryQueue: 0, merchants: makeMerchants(6, 'pinzhi'), recentEvents: makeEvents('pinzhi'), fieldMappings: makeMappings('pinzhi') },
  { id: 'aoqiwei', name: 'aoqiwei', displayName: '奥琦玮', protocol: 'REST', version: '1.8.0', lastUpdate: '2026-04-18', status: 'healthy', merchantsCount: 4, successRate: 99.5, p95Latency: 62, todaySyncCount: 2180, failedRetryQueue: 2, merchants: makeMerchants(4, 'aoqiwei'), recentEvents: makeEvents('aoqiwei'), fieldMappings: makeMappings('aoqiwei') },
  { id: 'tiancai-shanglong', name: 'tiancai-shanglong', displayName: '天财商龙', protocol: 'SOAP', version: '1.5.2', lastUpdate: '2026-04-15', status: 'healthy', merchantsCount: 5, successRate: 99.2, p95Latency: 88, todaySyncCount: 2850, failedRetryQueue: 1, merchants: makeMerchants(5, 'tiancai-shanglong'), recentEvents: makeEvents('tiancai-shanglong'), fieldMappings: makeMappings('tiancai-shanglong') },
  { id: 'keruyun', name: 'keruyun', displayName: '客如云', protocol: 'REST', version: '2.1.0', lastUpdate: '2026-04-22', status: 'healthy', merchantsCount: 3, successRate: 99.6, p95Latency: 52, todaySyncCount: 1560, failedRetryQueue: 0, merchants: makeMerchants(3, 'keruyun'), recentEvents: makeEvents('keruyun'), fieldMappings: makeMappings('keruyun') },
  { id: 'weishenghuo', name: 'weishenghuo', displayName: '微生活', protocol: 'REST', version: '1.2.0', lastUpdate: '2026-04-10', status: 'degraded', merchantsCount: 3, successRate: 97.5, p95Latency: 180, todaySyncCount: 980, failedRetryQueue: 8, merchants: makeMerchants(3, 'weishenghuo'), recentEvents: makeEvents('weishenghuo'), fieldMappings: makeMappings('weishenghuo') },
  { id: 'meituan', name: 'meituan', displayName: '美团', protocol: 'REST', version: '3.0.2', lastUpdate: '2026-04-25', status: 'healthy', merchantsCount: 8, successRate: 99.9, p95Latency: 32, todaySyncCount: 5600, failedRetryQueue: 0, merchants: makeMerchants(8, 'meituan'), recentEvents: makeEvents('meituan'), fieldMappings: makeMappings('meituan') },
  { id: 'eleme', name: 'eleme', displayName: '饿了么', protocol: 'REST', version: '2.8.1', lastUpdate: '2026-04-24', status: 'healthy', merchantsCount: 7, successRate: 99.7, p95Latency: 38, todaySyncCount: 4200, failedRetryQueue: 1, merchants: makeMerchants(7, 'eleme'), recentEvents: makeEvents('eleme'), fieldMappings: makeMappings('eleme') },
  { id: 'douyin', name: 'douyin', displayName: '抖音', protocol: 'REST', version: '2.2.0', lastUpdate: '2026-04-23', status: 'healthy', merchantsCount: 5, successRate: 99.4, p95Latency: 55, todaySyncCount: 2100, failedRetryQueue: 0, merchants: makeMerchants(5, 'douyin'), recentEvents: makeEvents('douyin'), fieldMappings: makeMappings('douyin') },
  { id: 'yiding', name: 'yiding', displayName: '易订', protocol: 'WebSocket', version: '1.4.0', lastUpdate: '2026-04-12', status: 'degraded', merchantsCount: 2, successRate: 96.8, p95Latency: 210, todaySyncCount: 320, failedRetryQueue: 12, merchants: makeMerchants(2, 'yiding'), recentEvents: makeEvents('yiding'), fieldMappings: makeMappings('yiding') },
  { id: 'nuonuo', name: 'nuonuo', displayName: '诺诺发票', protocol: 'REST', version: '1.6.0', lastUpdate: '2026-04-19', status: 'healthy', merchantsCount: 6, successRate: 99.8, p95Latency: 42, todaySyncCount: 1800, failedRetryQueue: 0, merchants: makeMerchants(6, 'nuonuo'), recentEvents: makeEvents('nuonuo'), fieldMappings: makeMappings('nuonuo') },
  { id: 'xiaohongshu', name: 'xiaohongshu', displayName: '小红书', protocol: 'REST', version: '1.0.3', lastUpdate: '2026-04-08', status: 'error', merchantsCount: 1, successRate: 88.5, p95Latency: 520, todaySyncCount: 45, failedRetryQueue: 23, merchants: makeMerchants(1, 'xiaohongshu'), recentEvents: makeEvents('xiaohongshu'), fieldMappings: makeMappings('xiaohongshu') },
  { id: 'erp', name: 'erp', displayName: 'ERP通用', protocol: 'REST', version: '1.1.0', lastUpdate: '2026-03-28', status: 'healthy', merchantsCount: 3, successRate: 99.3, p95Latency: 75, todaySyncCount: 680, failedRetryQueue: 0, merchants: makeMerchants(3, 'erp'), recentEvents: makeEvents('erp'), fieldMappings: makeMappings('erp') },
  { id: 'logistics', name: 'logistics', displayName: '物流通用', protocol: 'REST', version: '1.0.0', lastUpdate: '2026-03-20', status: 'inactive', merchantsCount: 0, successRate: 0, p95Latency: 0, todaySyncCount: 0, failedRetryQueue: 0, merchants: [], recentEvents: [], fieldMappings: makeMappings('logistics') },
  { id: 'delivery_factory', name: 'delivery_factory', displayName: '配送工厂', protocol: 'gRPC', version: '0.9.0', lastUpdate: '2026-03-15', status: 'inactive', merchantsCount: 0, successRate: 0, p95Latency: 0, todaySyncCount: 0, failedRetryQueue: 0, merchants: [], recentEvents: [], fieldMappings: makeMappings('delivery_factory') },
  { id: 'wechat_delivery', name: 'wechat_delivery', displayName: '微信外卖', protocol: 'REST', version: '0.8.0', lastUpdate: '2026-03-10', status: 'inactive', merchantsCount: 0, successRate: 0, p95Latency: 0, todaySyncCount: 0, failedRetryQueue: 0, merchants: [], recentEvents: [], fieldMappings: makeMappings('wechat_delivery') },
];

// ── 常量 ──

const STATUS_COLOR: Record<AdapterStatus, string> = { healthy: C.green, degraded: C.yellow, error: C.red, inactive: C.text3 };
const STATUS_LABEL: Record<AdapterStatus, string> = { healthy: '健康', degraded: '降级', error: '异常', inactive: '未接入' };

const CELL_COLOR: Record<MerchantLink['status'], string> = { normal: C.green, slow: C.yellow, error: C.red, inactive: C.text3 + '44' };

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'actions', label: 'Actions' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
  { key: 'related', label: 'Related' },
  { key: 'playbooks', label: 'Playbooks' },
];

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'healthy', label: '健康' },
  { key: 'degraded', label: '降级' },
  { key: 'error', label: '异常' },
  { key: 'inactive', label: '未接入' },
];

const EVENT_COLOR: Record<SyncEvent['type'], string> = {
  success: C.green, failure: C.red, retry: C.yellow, mapping_update: C.blue, version_upgrade: C.purple,
};
const EVENT_LABEL: Record<SyncEvent['type'], string> = {
  success: '成功', failure: '失败', retry: '重试', mapping_update: '映射更新', version_upgrade: '版本升级',
};

// ── Helpers ──

function Placeholder({ label }: { label: string }) {
  return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>{label}</div>;
}

function ConfirmDialog({ title, description, onConfirm, onCancel }: {
  title: string; description: string; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={onCancel}>
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24, minWidth: 360, maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 13, color: C.text2, marginBottom: 20 }}>{description}</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ background: 'transparent', color: C.text2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '8px 16px', fontSize: 13, cursor: 'pointer' }}>取消</button>
          <button onClick={onConfirm} style={{ background: C.orange, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>确认</button>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color: string }) {
  return (
    <div style={{ flex: '1 1 140px', background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {value}<span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{unit}</span>
      </div>
    </div>
  );
}

// ── Matrix View ──

function MatrixView({ adapters }: { adapters: AdapterItem[] }) {
  const [hover, setHover] = useState<{ adapter: string; merchant: string } | null>(null);

  // Collect all unique merchant names across adapters
  const allMerchants = useMemo(() => {
    const set = new Set<string>();
    for (const a of adapters) {
      for (const m of a.merchants) set.add(m.name);
    }
    return Array.from(set).sort();
  }, [adapters]);

  // Build a lookup: adapter.id -> merchant.name -> MerchantLink
  const lookup = useMemo(() => {
    const map = new Map<string, Map<string, MerchantLink>>();
    for (const a of adapters) {
      const inner = new Map<string, MerchantLink>();
      for (const m of a.merchants) inner.set(m.name, m);
      map.set(a.id, inner);
    }
    return map;
  }, [adapters]);

  const cols = allMerchants.length + 1; // +1 for row header

  return (
    <div style={{ background: C.surface, borderRadius: 12, padding: 20, border: `1px solid ${C.border}`, overflow: 'auto' }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 16 }}>适配器 x 商户 矩阵</div>
      <div style={{ position: 'relative' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: `140px repeat(${allMerchants.length}, 1fr)`,
          gap: 2,
          fontSize: 11,
        }}>
          {/* Header row */}
          <div style={{ padding: 6, color: C.text3, fontWeight: 600 }} />
          {allMerchants.map(m => (
            <div key={m} style={{
              padding: '6px 4px', color: C.text2, fontWeight: 600, textAlign: 'center',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>{m}</div>
          ))}

          {/* Data rows */}
          {adapters.map(adapter => (
            <div key={adapter.id} style={{ display: 'contents' }}>
              <div style={{
                padding: '8px 6px', color: C.text, fontWeight: 600, fontSize: 12,
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: STATUS_COLOR[adapter.status], flexShrink: 0 }} />
                {adapter.displayName}
              </div>
              {allMerchants.map(merchant => {
                const link = lookup.get(adapter.id)?.get(merchant);
                const cellStatus = link?.status || 'inactive';
                const isHovered = hover?.adapter === adapter.id && hover?.merchant === merchant;

                return (
                  <div
                    key={merchant}
                    style={{
                      background: CELL_COLOR[cellStatus],
                      borderRadius: 3,
                      minHeight: 28,
                      cursor: link ? 'pointer' : 'default',
                      opacity: cellStatus === 'inactive' ? 0.3 : 1,
                      position: 'relative',
                      transition: 'transform 0.1s',
                      transform: isHovered ? 'scale(1.15)' : 'scale(1)',
                      zIndex: isHovered ? 10 : 1,
                    }}
                    onMouseEnter={() => setHover({ adapter: adapter.id, merchant })}
                    onMouseLeave={() => setHover(null)}
                  >
                    {/* Tooltip */}
                    {isHovered && link && (
                      <div style={{
                        position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)',
                        background: C.surface2, border: `1px solid ${C.border2}`, borderRadius: 8, padding: 10,
                        whiteSpace: 'nowrap', zIndex: 100, marginBottom: 4,
                        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                      }}>
                        <div style={{ fontWeight: 600, color: C.text, marginBottom: 4 }}>{adapter.displayName} - {merchant}</div>
                        <div style={{ color: C.text2 }}>成功率: <span style={{ color: link.successRate > 99 ? C.green : link.successRate > 95 ? C.yellow : C.red, fontWeight: 600 }}>{link.successRate.toFixed(1)}%</span></div>
                        <div style={{ color: C.text2 }}>P95延迟: <span style={{ color: link.p95Latency < 100 ? C.green : link.p95Latency < 300 ? C.yellow : C.red, fontWeight: 600 }}>{link.p95Latency}ms</span></div>
                        <div style={{ color: C.text3 }}>最近同步: {link.lastSync}</div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, marginTop: 16, fontSize: 11, color: C.text3 }}>
          {([
            ['正常', C.green], ['延迟高', C.yellow], ['失败', C.red], ['未接入', C.text3 + '44'],
          ] as const).map(([label, color]) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 12, height: 12, borderRadius: 2, background: color, opacity: label === '未接入' ? 0.3 : 1 }} />
              {label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Overview Tab ──

function AdapterOverviewTab({ adapter }: { adapter: AdapterItem }) {
  const rateColor = adapter.successRate >= 99 ? C.green : adapter.successRate >= 95 ? C.yellow : C.red;
  const latColor = adapter.p95Latency <= 100 ? C.green : adapter.p95Latency <= 300 ? C.yellow : C.red;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 适配器信息 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>适配器信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['名称', adapter.displayName],
            ['版本', `v${adapter.version}`],
            ['协议', adapter.protocol],
            ['最后更新', adapter.lastUpdate],
          ] as const).map(([label, val]) => (
            <div key={label}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{ color: C.text }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 4 个指标卡 */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <MetricCard label="成功率" value={adapter.successRate > 0 ? adapter.successRate.toFixed(1) : '-'} unit="%" color={rateColor} />
        <MetricCard label="P95 延迟" value={adapter.p95Latency > 0 ? adapter.p95Latency : '-'} unit="ms" color={latColor} />
        <MetricCard label="今日同步数" value={adapter.todaySyncCount.toLocaleString()} color={C.blue} />
        <MetricCard label="失败重试队列" value={adapter.failedRetryQueue} color={adapter.failedRetryQueue > 5 ? C.red : adapter.failedRetryQueue > 0 ? C.yellow : C.green} />
      </div>

      {/* 接入商户列表 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>接入商户 ({adapter.merchants.length})</div>
        {adapter.merchants.length === 0 ? (
          <div style={{ color: C.text3, fontSize: 12 }}>暂无接入商户</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {adapter.merchants.map(m => {
              const mColor = m.status === 'normal' ? C.green : m.status === 'slow' ? C.yellow : m.status === 'error' ? C.red : C.text3;
              return (
                <div key={m.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', background: C.surface2, borderRadius: 6, border: `1px solid ${C.border}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 4, background: mColor }} />
                    <span style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{m.name}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 16, fontSize: 11, color: C.text3 }}>
                    <span>成功率 <span style={{ color: mColor, fontWeight: 600 }}>{m.successRate.toFixed(1)}%</span></span>
                    <span>P95 {m.p95Latency}ms</span>
                    <span>{m.lastSync}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 最近同步事件 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>最近同步事件</div>
        {adapter.recentEvents.length === 0 ? (
          <div style={{ color: C.text3, fontSize: 12 }}>暂无同步事件</div>
        ) : adapter.recentEvents.map(evt => (
          <div key={evt.id} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: `1px solid ${C.border}`, alignItems: 'center' }}>
            <span style={{ width: 8, height: 8, borderRadius: 4, background: EVENT_COLOR[evt.type], flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', minWidth: 120 }}>{evt.time}</span>
            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: EVENT_COLOR[evt.type] + '22', color: EVENT_COLOR[evt.type], fontWeight: 600 }}>{EVENT_LABEL[evt.type]}</span>
            <span style={{ fontSize: 13, color: C.text }}>{evt.description}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function AdapterTimelineTab({ adapter }: { adapter: AdapterItem }) {
  return (
    <div style={{ position: 'relative', paddingLeft: 24 }}>
      <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
      {adapter.recentEvents.length === 0 ? (
        <div style={{ color: C.text3, fontSize: 13, paddingLeft: 16 }}>暂无事件</div>
      ) : adapter.recentEvents.map((evt, i) => (
        <div key={evt.id} style={{ display: 'flex', gap: 12, marginBottom: i < adapter.recentEvents.length - 1 ? 20 : 0, position: 'relative' }}>
          <div style={{
            position: 'absolute', left: -20, top: 2, width: 12, height: 12, borderRadius: 6,
            background: EVENT_COLOR[evt.type], border: `2px solid ${C.surface}`,
          }} />
          <div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
              <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{evt.time}</span>
              <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: EVENT_COLOR[evt.type] + '22', color: EVENT_COLOR[evt.type], fontWeight: 600 }}>{EVENT_LABEL[evt.type]}</span>
            </div>
            <div style={{ fontSize: 13, color: C.text }}>{evt.description}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Actions Tab (Field Mapping + Operations) ──

function AdapterActionsTab({ adapter }: { adapter: AdapterItem }) {
  const [confirm, setConfirm] = useState<{ title: string; desc: string; action: () => void } | null>(null);

  const doAction = useCallback(async (path: string, body?: unknown) => {
    try {
      await hubPost(path, body);
    } catch {
      // API 未就绪
    }
    setConfirm(null);
  }, []);

  const MAPPING_COLOR: Record<FieldMapping['status'], string> = { mapped: C.green, unmapped: C.yellow, conflict: C.red };
  const MAPPING_LABEL: Record<FieldMapping['status'], string> = { mapped: '已映射', unmapped: '未映射', conflict: '冲突' };

  const mapped = adapter.fieldMappings.filter(f => f.status === 'mapped').length;
  const unmapped = adapter.fieldMappings.filter(f => f.status === 'unmapped').length;
  const conflict = adapter.fieldMappings.filter(f => f.status === 'conflict').length;

  const actions = [
    { icon: '\u{1F504}', title: '手动触发同步', desc: '立即执行一次全量同步', color: C.blue, onClick: () => setConfirm({ title: '手动同步', desc: `确认对「${adapter.displayName}」执行手动同步？`, action: () => doAction(`/adapters/${adapter.id}/sync`) }) },
    { icon: '\u{1F501}', title: '重放失败队列', desc: `当前失败队列 ${adapter.failedRetryQueue} 条`, color: C.orange, onClick: () => setConfirm({ title: '重放失败队列', desc: `确认重放「${adapter.displayName}」的 ${adapter.failedRetryQueue} 条失败记录？`, action: () => doAction(`/adapters/${adapter.id}/replay-failed`) }) },
    { icon: '\u{1F4E4}', title: '导出映射配置', desc: '导出字段映射为 JSON 文件', color: C.purple, onClick: () => doAction(`/adapters/${adapter.id}/export-mapping`) },
    { icon: '\u23F8', title: '暂停同步', desc: '暂停此适配器的所有同步任务', color: C.yellow, onClick: () => setConfirm({ title: '暂停同步', desc: `确认暂停「${adapter.displayName}」的所有同步任务？`, action: () => doAction(`/adapters/${adapter.id}/pause`) }) },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {confirm && <ConfirmDialog title={confirm.title} description={confirm.desc} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}

      {/* 字段映射可视化 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>字段映射</div>
          <div style={{ display: 'flex', gap: 12, fontSize: 11 }}>
            <span style={{ color: C.green }}>已映射 {mapped}</span>
            <span style={{ color: C.yellow }}>未映射 {unmapped}</span>
            <span style={{ color: C.red }}>冲突 {conflict}</span>
          </div>
        </div>

        {/* 两列映射表 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 40px 1fr 60px', gap: '4px 0', fontSize: 12, alignItems: 'center' }}>
          {/* Header */}
          <div style={{ padding: '6px 8px', color: C.text3, fontWeight: 600, borderBottom: `1px solid ${C.border}` }}>源系统字段</div>
          <div style={{ borderBottom: `1px solid ${C.border}` }} />
          <div style={{ padding: '6px 8px', color: C.text3, fontWeight: 600, borderBottom: `1px solid ${C.border}` }}>屯象Ontology字段</div>
          <div style={{ padding: '6px 8px', color: C.text3, fontWeight: 600, borderBottom: `1px solid ${C.border}`, textAlign: 'center' }}>状态</div>

          {adapter.fieldMappings.map((fm, i) => {
            const color = MAPPING_COLOR[fm.status];
            return (
              <div key={i} style={{ display: 'contents' }}>
                <div style={{ padding: '6px 8px', color: C.text, fontFamily: 'monospace', background: i % 2 === 0 ? C.surface2 : 'transparent', borderRadius: '4px 0 0 4px' }}>
                  {fm.sourceField}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', background: i % 2 === 0 ? C.surface2 : 'transparent' }}>
                  <div style={{ width: 20, height: 2, background: color, borderRadius: 1 }} />
                  <div style={{ width: 0, height: 0, borderTop: '3px solid transparent', borderBottom: '3px solid transparent', borderLeft: `4px solid ${color}` }} />
                </div>
                <div style={{ padding: '6px 8px', color: fm.targetField ? C.text : C.text3, fontFamily: 'monospace', fontStyle: fm.targetField ? 'normal' : 'italic', background: i % 2 === 0 ? C.surface2 : 'transparent' }}>
                  {fm.targetField || '(未映射)'}
                </div>
                <div style={{ textAlign: 'center', background: i % 2 === 0 ? C.surface2 : 'transparent', borderRadius: '0 4px 4px 0' }}>
                  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: color + '22', color, fontWeight: 600 }}>
                    {MAPPING_LABEL[fm.status]}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 操作按钮 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {actions.map(a => (
          <button key={a.title} onClick={a.onClick} style={{
            background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16,
            cursor: 'pointer', textAlign: 'left', display: 'flex', gap: 12, alignItems: 'flex-start',
          }}>
            <span style={{ fontSize: 20, width: 28, textAlign: 'center' }}>{a.icon}</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: a.color, marginBottom: 4 }}>{a.title}</div>
              <div style={{ fontSize: 12, color: C.text3 }}>{a.desc}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Related Tab ──

function AdapterRelatedTab({ adapter }: { adapter: AdapterItem }) {
  const relations = [
    ...adapter.merchants.map(m => ({ type: '商户', name: m.name, id: `merchant-${m.name}` })),
    { type: '迁移项目', name: `${adapter.displayName}相关迁移`, id: `mig-${adapter.id}` },
    { type: '工单', name: `${adapter.displayName}-同步异常处理`, id: `ticket-${adapter.id}-001` },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {relations.map(r => (
        <div key={r.id} style={{ background: C.surface, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span style={{ fontSize: 11, color: C.text3, marginRight: 8 }}>{r.type}</span>
            <span style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{r.name}</span>
          </div>
          <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{r.id}</span>
        </div>
      ))}
    </div>
  );
}

// ── Main Export ──

export function AdaptersWorkspace() {
  const [adapters, setAdapters] = useState<AdapterItem[]>(MOCK_ADAPTERS);
  const [selected, setSelected] = useState<AdapterItem | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');
  const [view, setView] = useState<ViewMode>('list');

  useEffect(() => {
    hubGet<AdapterItem[]>('/adapters')
      .then(data => { if (Array.isArray(data) && data.length > 0) setAdapters(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    if (filter === 'all') return adapters;
    return adapters.filter(a => a.status === filter);
  }, [adapters, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: adapters.length };
    for (const a of adapters) m[a.status] = (m[a.status] || 0) + 1;
    return m;
  }, [adapters]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>适配器</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['list', 'matrix'] as const).map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              background: view === v ? C.orange + '22' : 'transparent',
              color: view === v ? C.orange : C.text3,
              border: `1px solid ${view === v ? C.orange : C.border}`,
              borderRadius: 6, padding: '5px 14px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
            }}>{v === 'list' ? '列表' : '矩阵'}</button>
          ))}
        </div>
      </div>

      {view === 'matrix' ? (
        <MatrixView adapters={adapters} />
      ) : (
        <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
          {/* 左侧列表 */}
          <div style={{ width: 360, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
            {/* 筛选 chips */}
            <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {FILTERS.map(f => (
                <button key={f.key} onClick={() => setFilter(f.key)} style={{
                  background: filter === f.key ? C.orange + '22' : 'transparent',
                  color: filter === f.key ? C.orange : C.text3,
                  border: `1px solid ${filter === f.key ? C.orange : C.border}`,
                  borderRadius: 20, padding: '3px 10px', fontSize: 11, cursor: 'pointer',
                }}>
                  {f.label} {counts[f.key] ?? 0}
                </button>
              ))}
            </div>
            {/* 列表项 */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {filtered.map(adapter => {
                const isActive = selected?.id === adapter.id;
                return (
                  <div key={adapter.id} onClick={() => { setSelected(adapter); setTab('overview'); }} style={{
                    padding: '10px 14px', cursor: 'pointer',
                    borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                    background: isActive ? C.orange + '0D' : 'transparent',
                    borderBottom: `1px solid ${C.border}`,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOR[adapter.status], flexShrink: 0 }} />
                      <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{adapter.displayName}</span>
                      <span style={{ fontSize: 11, color: C.text3 }}>{adapter.name}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.text3 }}>
                      <span>{adapter.merchantsCount} 商户</span>
                      <div style={{ display: 'flex', gap: 12 }}>
                        <span>{adapter.successRate > 0 ? `${adapter.successRate.toFixed(1)}%` : '-'}</span>
                        <span>{adapter.p95Latency > 0 ? `${adapter.p95Latency}ms` : '-'}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 右侧 Object Page */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {!selected ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.text3, fontSize: 14 }}>
                选择一个适配器查看详情
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 5, background: STATUS_COLOR[selected.status] }} />
                  <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.displayName}</span>
                  <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace' }}>{selected.name}</span>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: STATUS_COLOR[selected.status] + '22', color: STATUS_COLOR[selected.status], fontWeight: 600 }}>
                    {STATUS_LABEL[selected.status]}
                  </span>
                </div>
                {/* Tab bar */}
                <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 16 }}>
                  {TABS.map(t => (
                    <button key={t.key} onClick={() => setTab(t.key)} style={{
                      padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                      color: tab === t.key ? C.orange : C.text3,
                      borderBottom: tab === t.key ? `2px solid ${C.orange}` : '2px solid transparent',
                      background: 'transparent', border: 'none', borderBottomStyle: 'solid' as const,
                    }}>{t.label}</button>
                  ))}
                </div>
                {/* Tab content */}
                <div style={{ flex: 1, overflowY: 'auto' }}>
                  {tab === 'overview' && <AdapterOverviewTab adapter={selected} />}
                  {tab === 'timeline' && <AdapterTimelineTab adapter={selected} />}
                  {tab === 'actions' && <AdapterActionsTab adapter={selected} />}
                  {tab === 'traces' && <Placeholder label="Trace 数据接入中" />}
                  {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                  {tab === 'logs' && <Placeholder label="日志接入中" />}
                  {tab === 'related' && <AdapterRelatedTab adapter={selected} />}
                  {tab === 'playbooks' && <Placeholder label="关联剧本列表" />}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
