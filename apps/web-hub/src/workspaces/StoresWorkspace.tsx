/**
 * Workspace: Stores -- 门店管理（替代 v1 StoresPage）
 *
 * 左侧列表 + 右侧 Object Page (8 Tab)
 * 以门店为中心聚合订单/设备/工单/客诉
 */
import { useState, useEffect, useMemo } from 'react';
import { hubGet } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型定义 ──

type StoreStatus = 'open' | 'closed' | 'abnormal' | 'new';

interface DeviceInfo {
  type: string;
  model: string;
  status: 'online' | 'offline' | 'ready' | 'error';
  count?: number;
  onlineCount?: number;
  version?: string;
}

interface StoreAlert {
  id: string;
  time: string;
  level: 'warning' | 'error' | 'info';
  message: string;
}

interface TimelineEvent {
  id: string;
  time: string;
  type: string;
  description: string;
  icon: string;
}

interface Store {
  id: string;
  name: string;
  merchant: string;
  address: string;
  city: string;
  status: StoreStatus;
  businessHours: string;
  tableCount: number;
  area: number;
  format: 'Pro' | 'Lite';
  todayRevenue: number;
  todayOrders: number;
  avgTicket: number;
  turnoverRate: number;
  onlineDevices: number;
  totalDevices: number;
  devices: DeviceInfo[];
  alerts: StoreAlert[];
  timeline: TimelineEvent[];
  edgeNode: string;
  merchantId: string;
}

// ── Mock 数据 ──

const MOCK_ALERTS: StoreAlert[] = [
  { id: 'a1', time: '2026-04-26 08:30', level: 'warning', message: '2号打印机纸张即将用尽' },
  { id: 'a2', time: '2026-04-26 07:15', level: 'error', message: 'KDS屏幕3号离线超过10分钟' },
  { id: 'a3', time: '2026-04-25 22:00', level: 'info', message: '日结报表已自动生成' },
];

const MOCK_TIMELINE: TimelineEvent[] = [
  { id: 't1', time: '2026-04-26 06:30', type: 'open', description: '门店开业，系统启动', icon: '🟢' },
  { id: 't2', time: '2026-04-25 23:00', type: 'close', description: '门店打烊，日结完成', icon: '🔴' },
  { id: 't3', time: '2026-04-24 14:00', type: 'device', description: 'Mac mini 推送更新 3.3.0', icon: '📦' },
  { id: 't4', time: '2026-04-23 10:00', type: 'inspection', description: '食安巡检通过（评分95）', icon: '✅' },
  { id: 't5', time: '2026-04-22 09:00', type: 'complaint', description: '顾客投诉：出餐慢（已处理）', icon: '📋' },
  { id: 't6', time: '2026-04-20 08:00', type: 'maintenance', description: '空调维修完成', icon: '🔧' },
  { id: 't7', time: '2026-04-15 10:00', type: 'system', description: 'POS 系统上线', icon: '💻' },
  { id: 't8', time: '2026-03-01 09:00', type: 'opening', description: '门店开业', icon: '🎉' },
];

const MOCK_DEVICES: DeviceInfo[] = [
  { type: 'Mac mini', model: 'Mac mini M4', status: 'online', version: '3.3.0' },
  { type: 'POS主机', model: '商米 T2', status: 'online' },
  { type: 'KDS屏', model: '商米 D2', status: 'online', count: 3, onlineCount: 3 },
  { type: '打印机', model: '商米云打印', status: 'ready', count: 4, onlineCount: 4 },
];

function makeStore(
  id: string, name: string, merchant: string, merchantId: string, city: string, address: string,
  status: StoreStatus, format: 'Pro' | 'Lite',
  revenue: number, orders: number, tableCount: number, area: number,
  onlineDev: number, totalDev: number,
): Store {
  return {
    id, name, merchant, merchantId, city, address, status, format,
    businessHours: format === 'Pro' ? '10:00-22:00' : '10:30-21:30',
    tableCount, area,
    todayRevenue: revenue, todayOrders: orders,
    avgTicket: orders > 0 ? Math.round(revenue / orders) : 0,
    turnoverRate: +(Math.random() * 2 + 1.5).toFixed(1),
    onlineDevices: onlineDev, totalDevices: totalDev,
    devices: MOCK_DEVICES.map(d => ({
      ...d,
      status: onlineDev === totalDev ? d.status : (Math.random() > 0.7 ? 'offline' : d.status),
    })),
    alerts: status === 'abnormal' ? MOCK_ALERTS : MOCK_ALERTS.slice(2),
    timeline: MOCK_TIMELINE,
    edgeNode: `TX-MAC-${id.split('-')[1] || '001'}`,
  };
}

const MOCK_STORES: Store[] = [
  makeStore('s-001', '长沙万达店', '徐记海鲜', 'm-001', '长沙', '长沙市开福区万达广场B1层', 'open', 'Pro', 128600, 186, 60, 800, 9, 9),
  makeStore('s-002', '广州天河店', '徐记海鲜', 'm-001', '广州', '广州市天河区正佳广场5层', 'open', 'Pro', 156200, 215, 72, 1000, 10, 10),
  makeStore('s-003', '深圳南山店', '徐记海鲜', 'm-001', '深圳', '深圳市南山区海岸城购物中心3层', 'open', 'Pro', 142800, 198, 65, 900, 9, 9),
  makeStore('s-004', '长沙梅溪湖店', '徐记海鲜', 'm-001', '长沙', '长沙市岳麓区梅溪湖步步高广场', 'closed', 'Pro', 0, 0, 55, 750, 0, 9),
  makeStore('s-005', '武汉光谷店', '徐记海鲜', 'm-001', '武汉', '武汉市洪山区光谷广场K11', 'open', 'Pro', 118500, 168, 50, 700, 8, 8),
  makeStore('s-006', '解放西店', '尝在一起', 'm-002', '长沙', '长沙市天心区解放西路188号', 'open', 'Lite', 45800, 312, 28, 300, 5, 5),
  makeStore('s-007', '五一广场店', '尝在一起', 'm-002', '长沙', '长沙市芙蓉区五一广场地铁站旁', 'open', 'Lite', 52300, 356, 32, 350, 5, 5),
  makeStore('s-008', '万家丽店', '尝在一起', 'm-002', '长沙', '长沙市雨花区万家丽广场B1', 'abnormal', 'Lite', 38200, 268, 25, 280, 3, 5),
  makeStore('s-009', '太平街店', '最黔线', 'm-003', '长沙', '长沙市天心区太平街45号', 'open', 'Lite', 36500, 245, 22, 250, 4, 4),
  makeStore('s-010', '坡子街店', '最黔线', 'm-003', '长沙', '长沙市天心区坡子街火宫殿旁', 'open', 'Lite', 32800, 228, 20, 220, 4, 4),
  makeStore('s-011', '岳麓区店', '尚宫厨', 'm-004', '长沙', '长沙市岳麓区桐梓坡路168号', 'open', 'Pro', 86500, 128, 40, 500, 7, 7),
  makeStore('s-012', '芙蓉路店', '湘粤楼', 'm-005', '长沙', '长沙市芙蓉区芙蓉路CBD中心', 'open', 'Pro', 98200, 145, 45, 600, 8, 8),
  makeStore('s-013', '星沙店', '湘粤楼', 'm-005', '长沙', '长沙县星沙通程商业广场', 'closed', 'Lite', 0, 0, 30, 320, 0, 5),
  makeStore('s-014', '河西新店', '徐记海鲜', 'm-001', '长沙', '长沙市岳麓区河西金融中心', 'new', 'Pro', 15800, 32, 48, 650, 7, 8),
  makeStore('s-015', '雨花区店', '尝在一起', 'm-002', '长沙', '长沙市雨花区德思勤广场', 'open', 'Lite', 41200, 289, 26, 290, 5, 5),
];

// ── 样式 ──

const STATUS_COLOR: Record<StoreStatus, string> = {
  open: C.green, closed: C.text3, abnormal: C.red, new: C.blue,
};
const STATUS_LABEL: Record<StoreStatus, string> = {
  open: '营业中', closed: '已打烊', abnormal: '异常', new: '新开业',
};

type FilterKey = 'all' | StoreStatus;
type TabKey = 'overview' | 'timeline' | 'related' | 'actions' | 'traces' | 'cost' | 'logs' | 'playbooks';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'related', label: 'Related' },
  { key: 'actions', label: 'Actions' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
  { key: 'playbooks', label: 'Playbooks' },
];

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'open', label: '营业中' },
  { key: 'closed', label: '已打烊' },
  { key: 'abnormal', label: '异常' },
  { key: 'new', label: '新开业' },
];

const ALERT_COLOR: Record<string, string> = { warning: C.yellow, error: C.red, info: C.blue };

// ── Helpers ──

function Placeholder({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>
      {label}
    </div>
  );
}

function KpiCard({ label, value, color, suffix }: { label: string; value: string | number; color: string; suffix?: string }) {
  return (
    <div style={{ flex: '1 1 140px', background: C.surface, borderRadius: 10, padding: '14px 16px', border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, color: C.text3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {value}{suffix && <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{suffix}</span>}
      </div>
    </div>
  );
}

// ── Overview Tab ──

function OverviewTab({ store }: { store: Store }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 门店信息 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>门店信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['门店名称', store.name],
            ['所属商户', store.merchant],
            ['地址', store.address],
            ['营业时间', store.businessHours],
            ['桌台数', `${store.tableCount} 桌`],
            ['面积', `${store.area} m\u00B2`],
            ['业态', store.format === 'Pro' ? '大店 Pro' : '小店 Lite'],
            ['城市', store.city],
            ['状态', STATUS_LABEL[store.status]],
          ] as const).map(([label, val]) => (
            <div key={label}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{ color: label === '状态' ? STATUS_COLOR[store.status] : C.text, fontWeight: label === '状态' ? 600 : 400 }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* KPI */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <KpiCard label="今日营收" value={`\u00A5${(store.todayRevenue / 100).toLocaleString()}`} color={C.orange} />
        <KpiCard label="今日订单" value={store.todayOrders} color={C.blue} suffix="单" />
        <KpiCard label="平均客单价" value={`\u00A5${(store.avgTicket / 100).toFixed(0)}`} color={C.green} />
        <KpiCard label="翻台率" value={store.turnoverRate} color={C.purple} suffix="次" />
      </div>

      {/* 设备状态网格 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>设备状态</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
          {store.devices.map(dev => {
            const isOnline = dev.status === 'online' || dev.status === 'ready';
            const statusColor = isOnline ? C.green : C.red;
            return (
              <div key={dev.type} style={{ background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: statusColor }} />
                  <span style={{ fontWeight: 600, fontSize: 13, color: C.text }}>{dev.type}</span>
                </div>
                <div style={{ fontSize: 11, color: C.text3 }}>
                  {dev.model}
                  {dev.version && <span style={{ marginLeft: 6 }}>v{dev.version}</span>}
                </div>
                {dev.count != null && (
                  <div style={{ fontSize: 11, color: C.text3, marginTop: 2 }}>
                    {dev.onlineCount}/{dev.count} 在线
                  </div>
                )}
                {!dev.count && (
                  <div style={{ fontSize: 11, color: statusColor, fontWeight: 600, marginTop: 2 }}>
                    {isOnline ? '在线' : '离线'}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 最近告警 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>最近告警</div>
        {store.alerts.length === 0 ? (
          <div style={{ color: C.text3, fontSize: 13 }}>暂无告警</div>
        ) : (
          store.alerts.map(alert => (
            <div key={alert.id} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: `1px solid ${C.border}`, alignItems: 'center' }}>
              <span style={{
                display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                background: (ALERT_COLOR[alert.level] || C.text3) + '22', color: ALERT_COLOR[alert.level] || C.text3,
              }}>{alert.level.toUpperCase()}</span>
              <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', minWidth: 120 }}>{alert.time}</span>
              <span style={{ fontSize: 13, color: C.text }}>{alert.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function TimelineTab({ store }: { store: Store }) {
  const [range, setRange] = useState<'24h' | '7d' | '30d'>('30d');

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['24h', '7d', '30d'] as const).map(r => (
          <button key={r} onClick={() => setRange(r)} style={{
            background: range === r ? C.orange + '22' : 'transparent',
            color: range === r ? C.orange : C.text3,
            border: `1px solid ${range === r ? C.orange : C.border}`,
            borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer',
          }}>{r}</button>
        ))}
      </div>
      <div style={{ position: 'relative', paddingLeft: 24 }}>
        <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
        {store.timeline.map((evt, i) => (
          <div key={evt.id} style={{ display: 'flex', gap: 12, marginBottom: i < store.timeline.length - 1 ? 20 : 0, position: 'relative' }}>
            <div style={{ position: 'absolute', left: -20, top: 2, width: 16, height: 16, borderRadius: 8, background: C.surface, border: `2px solid ${C.border2}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9 }}>
              {evt.icon}
            </div>
            <div>
              <div style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', marginBottom: 2 }}>{evt.time}</div>
              <div style={{ fontSize: 13, color: C.text }}>{evt.description}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Related Tab ──

function RelatedTab({ store }: { store: Store }) {
  const relations = [
    { type: '所属商户', name: store.merchant, id: store.merchantId, note: '点击跳转' },
    { type: '边缘节点', name: `Mac mini (${store.edgeNode})`, id: store.edgeNode, note: 'Mac mini M4' },
  ];

  const mockTickets = [
    { id: 'TK-001', title: 'POS打印机卡纸', status: '处理中', time: '2026-04-25' },
    { id: 'TK-002', title: 'WiFi信号弱', status: '已解决', time: '2026-04-23' },
    { id: 'TK-003', title: 'KDS屏幕花屏', status: '待处理', time: '2026-04-26' },
  ];

  const mockComplaints = [
    { id: 'CP-001', content: '上菜太慢，等了40分钟', time: '2026-04-24', status: '已处理' },
    { id: 'CP-002', content: '服务员态度不好', time: '2026-04-22', status: '已处理' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 关联对象 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {relations.map(r => (
          <div key={r.id} style={{ background: C.surface, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
            <div>
              <span style={{ fontSize: 11, color: C.text3, marginRight: 8 }}>{r.type}</span>
              <span style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{r.name}</span>
            </div>
            <span style={{ fontSize: 11, color: C.orange }}>{r.note}</span>
          </div>
        ))}
      </div>

      {/* 近7天工单 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>近7天工单</div>
        {mockTickets.map(t => (
          <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div>
              <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace', marginRight: 8 }}>{t.id}</span>
              <span style={{ fontSize: 13, color: C.text }}>{t.title}</span>
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: C.text3 }}>{t.time}</span>
              <span style={{
                fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                background: t.status === '已解决' ? C.green + '22' : t.status === '处理中' ? C.yellow + '22' : C.red + '22',
                color: t.status === '已解决' ? C.green : t.status === '处理中' ? C.yellow : C.red,
              }}>{t.status}</span>
            </div>
          </div>
        ))}
      </div>

      {/* 近7天客诉 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>近7天客诉</div>
        {mockComplaints.map(c => (
          <div key={c.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div>
              <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace', marginRight: 8 }}>{c.id}</span>
              <span style={{ fontSize: 13, color: C.text }}>{c.content}</span>
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: C.text3 }}>{c.time}</span>
              <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4, background: C.green + '22', color: C.green }}>{c.status}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Actions Tab ──

function ActionsTab({ store }: { store: Store }) {
  const [actionResult, setActionResult] = useState<string | null>(null);

  const actions = [
    { icon: '🔍', title: '远程巡店', desc: '查看门店实时经营数据、设备状态', color: C.blue, onClick: () => setActionResult(`正在加载 ${store.name} 实时数据...`) },
    { icon: '📦', title: '推送更新', desc: '向门店所有设备推送最新版本', color: C.orange, onClick: () => setActionResult(`已向 ${store.name} 推送更新指令`) },
    { icon: '📋', title: '创建工单', desc: '为该门店创建维修/运维工单', color: C.green, onClick: () => setActionResult(`工单创建面板（开发中）`) },
    { icon: '🕐', title: '调整营业时间', desc: '修改门店的营业时间段', color: C.yellow, onClick: () => setActionResult(`营业时间编辑面板（开发中）`) },
  ];

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        {actions.map(a => (
          <button key={a.title} onClick={a.onClick} style={{
            background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16,
            cursor: 'pointer', textAlign: 'left', display: 'flex', gap: 12, alignItems: 'flex-start',
          }}>
            <span style={{ fontSize: 24 }}>{a.icon}</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: a.color, marginBottom: 4 }}>{a.title}</div>
              <div style={{ fontSize: 12, color: C.text3 }}>{a.desc}</div>
            </div>
          </button>
        ))}
      </div>
      {actionResult && (
        <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}`, fontSize: 13, color: C.text2 }}>
          {actionResult}
        </div>
      )}
    </div>
  );
}

// ── Main Export ──

export function StoresWorkspace() {
  const [stores, setStores] = useState<Store[]>(MOCK_STORES);
  const [selected, setSelected] = useState<Store | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');

  // 尝试从 API 加载
  useEffect(() => {
    hubGet<Store[]>('/stores')
      .then(data => { if (Array.isArray(data) && data.length > 0) setStores(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    if (filter === 'all') return stores;
    return stores.filter(s => s.status === filter);
  }, [stores, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: stores.length };
    for (const s of stores) m[s.status] = (m[s.status] || 0) + 1;
    return m;
  }, [stores]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* 顶部栏 */}
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text, marginBottom: 16 }}>门店</div>

      <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
        {/* 左侧列表 */}
        <div style={{ width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
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
            {filtered.map(store => {
              const isActive = selected?.id === store.id;
              return (
                <div key={store.id} onClick={() => { setSelected(store); setTab('overview'); }} style={{
                  padding: '10px 14px', cursor: 'pointer',
                  borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                  background: isActive ? C.orange + '0D' : 'transparent',
                  borderBottom: `1px solid ${C.border}`,
                  transition: 'background 0.15s',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOR[store.status], flexShrink: 0 }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{store.name}</span>
                    <span style={{ fontSize: 11, color: C.text3, marginLeft: 'auto' }}>{store.merchant}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingLeft: 16 }}>
                    <span style={{ fontSize: 12, color: C.text2 }}>
                      {store.todayRevenue > 0 ? `\u00A5${(store.todayRevenue / 100).toLocaleString()}` : '--'}
                    </span>
                    <div style={{ display: 'flex', gap: 8, fontSize: 11, color: C.text3 }}>
                      <span>{store.onlineDevices}/{store.totalDevices} 设备</span>
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
              选择一个门店查看详情
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: 5, background: STATUS_COLOR[selected.status] }} />
                <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.merchant} - {selected.name}</span>
                <span style={{
                  fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                  background: (selected.format === 'Pro' ? C.purple : C.blue) + '22',
                  color: selected.format === 'Pro' ? C.purple : C.blue,
                }}>{selected.format === 'Pro' ? '大店 Pro' : '小店 Lite'}</span>
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
                {tab === 'overview' && <OverviewTab store={selected} />}
                {tab === 'timeline' && <TimelineTab store={selected} />}
                {tab === 'related' && <RelatedTab store={selected} />}
                {tab === 'actions' && <ActionsTab store={selected} />}
                {tab === 'traces' && <Placeholder label="Trace 数据接入中" />}
                {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                {tab === 'logs' && <Placeholder label="日志接入中" />}
                {tab === 'playbooks' && <Placeholder label="关联剧本列表" />}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
