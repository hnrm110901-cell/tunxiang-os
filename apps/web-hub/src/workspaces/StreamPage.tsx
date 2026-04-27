/**
 * Stream 页面 — 全局实时事件流
 *
 * 事件类型过滤 + 暂停/继续 + SSE 实时推送
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { hubStream } from '../api/hubApi';

const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6',
  purple: '#A855F7', cyan: '#06B6D4',
};

// ── 类型 ──

type EventCategory = 'edge' | 'service' | 'ticket' | 'agent' | 'adapter';

interface StreamEvent {
  id: string;
  timestamp: string;
  category: EventCategory;
  title: string;
  description: string;
  source: string;
  link_type?: string;
  link_id?: string;
}

// ── 常量 ──

const CATEGORY_CONFIG: Record<EventCategory, { label: string; color: string }> = {
  edge:    { label: '边缘', color: C.cyan },
  service: { label: '服务', color: C.blue },
  ticket:  { label: '工单', color: C.yellow },
  agent:   { label: 'Agent', color: C.purple },
  adapter: { label: '适配器', color: C.orange },
};

type FilterKey = 'all' | EventCategory;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'edge', label: '边缘' },
  { key: 'service', label: '服务' },
  { key: 'ticket', label: '工单' },
  { key: 'agent', label: 'Agent' },
  { key: 'adapter', label: '适配器' },
];

// ── Mock 数据（初始 20 条） ──

function genMockEvents(): StreamEvent[] {
  const now = new Date();
  const items: Omit<StreamEvent, 'id' | 'timestamp'>[] = [
    { category: 'edge', title: 'TX-MAC-001 心跳正常', description: '芙蓉路店节点在线，延迟 12ms', source: 'TX-MAC-001' },
    { category: 'service', title: 'tx-trade 健康检查通过', description: 'QPS 850/s，P95 45ms', source: 'tx-trade' },
    { category: 'agent', title: '折扣守护拦截异常折扣', description: '芙蓉路店 A05 桌 62% 折扣被拦截', source: 'discount_guard' },
    { category: 'edge', title: 'TX-MAC-006 离线', description: '最黔线开福区店节点心跳超时', source: 'TX-MAC-006' },
    { category: 'ticket', title: '新工单: mcp-server 启动失败', description: '优先级 P1，已分配给运维团队', source: '工单系统' },
    { category: 'service', title: 'tx-supply P95延迟升高', description: '当前 180ms，接近 SLO 阈值 200ms', source: 'tx-supply' },
    { category: 'agent', title: '智能排菜生成推荐', description: '五一广场店今日主推剁椒鱼头', source: 'smart_menu' },
    { category: 'adapter', title: '品智POS数据同步完成', description: '尝在一起天心区店 142 笔订单同步', source: 'adapter-pinzhi' },
    { category: 'edge', title: 'TX-MAC-009 更新进度 60%', description: '雨花区店版本 3.2.9 → 3.3.0', source: 'TX-MAC-009' },
    { category: 'service', title: 'mcp-server 启动失败', description: '第3次重试失败，错误率 2.5%', source: 'mcp-server' },
    { category: 'agent', title: '库存预警：基围虾不足', description: '万家丽店建议紧急采购15kg', source: 'inventory_alert' },
    { category: 'ticket', title: '工单 #1023 已解决', description: 'tx-civic 部署问题已修复', source: '工单系统' },
    { category: 'edge', title: 'TX-MAC-003 CPU峰值', description: '五一广场店 CPU 67%（午高峰）', source: 'TX-MAC-003' },
    { category: 'adapter', title: '美团订单推送', description: '芙蓉路店收到 3 笔美团外卖订单', source: 'adapter-meituan' },
    { category: 'service', title: 'gateway QPS正常', description: '当前 1200/s，无异常', source: 'gateway' },
    { category: 'agent', title: '出餐调度优化', description: '芙蓉路店午高峰增派1名服务员', source: 'serve_dispatch' },
    { category: 'edge', title: 'TX-MAC-010 已隔离', description: '河西店磁盘使用率 88%', source: 'TX-MAC-010' },
    { category: 'ticket', title: '工单 #1024 创建', description: 'TX-MAC-010 磁盘清理任务', source: '工单系统' },
    { category: 'service', title: 'tx-civic 降级告警', description: '可用性降至 99.60%，低于 SLO', source: 'tx-civic' },
    { category: 'adapter', title: '饿了么订单同步', description: '万家丽店 5 笔饿了么订单入库', source: 'adapter-eleme' },
  ];

  return items.map((item, i) => ({
    ...item,
    id: `mock-${i}`,
    timestamp: new Date(now.getTime() - i * 180000).toISOString(),
  }));
}

const MOCK_EVENTS = genMockEvents();

// ── Helpers ──

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  } catch {
    return iso;
  }
}

// ── Main ──

export function StreamPage() {
  const [events, setEvents] = useState<StreamEvent[]>(MOCK_EVENTS);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const addEvent = useCallback((evt: StreamEvent) => {
    if (pausedRef.current) return;
    setEvents(prev => [evt, ...prev].slice(0, 200));
  }, []);

  // SSE 连接
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = hubStream('/stream', (event) => {
        try {
          const data = JSON.parse(event.data) as StreamEvent;
          addEvent(data);
        } catch {
          // 解析失败，忽略
        }
      });
    } catch {
      // SSE 不可用
    }
    return () => {
      if (es) es.close();
    };
  }, [addEvent]);

  const filtered = filter === 'all' ? events : events.filter(e => e.category === filter);

  const counts: Record<string, number> = { all: events.length };
  for (const e of events) counts[e.category] = (counts[e.category] || 0) + 1;

  return (
    <div style={{ color: C.text }}>
      {/* 标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>事件流</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: 4, background: paused ? C.yellow : C.green, animation: paused ? 'none' : undefined }} />
          <span style={{ fontSize: 12, color: paused ? C.yellow : C.green }}>{paused ? '已暂停' : '实时'}</span>
        </div>
      </div>

      {/* 过滤 + 暂停按钮 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        {FILTERS.map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)} style={{
            background: filter === f.key ? C.orange + '22' : 'transparent',
            color: filter === f.key ? C.orange : C.text3,
            border: `1px solid ${filter === f.key ? C.orange : C.border}`,
            borderRadius: 20, padding: '4px 12px', fontSize: 12, cursor: 'pointer',
          }}>
            {f.label} {counts[f.key] ?? 0}
          </button>
        ))}
        <div style={{ marginLeft: 'auto' }}>
          <button onClick={() => setPaused(!paused)} style={{
            background: paused ? C.green + '22' : C.yellow + '22',
            color: paused ? C.green : C.yellow,
            border: `1px solid ${paused ? C.green : C.yellow}`,
            borderRadius: 6, padding: '5px 14px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
          }}>
            {paused ? '继续' : '暂停'}
          </button>
        </div>
      </div>

      {/* 事件列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {filtered.map(evt => {
          const catCfg = CATEGORY_CONFIG[evt.category];
          return (
            <div key={evt.id} style={{
              display: 'flex', gap: 12, padding: '10px 14px', alignItems: 'flex-start',
              background: C.surface, borderRadius: 6, border: `1px solid ${C.border}`,
            }}>
              {/* 时间戳 */}
              <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace', minWidth: 64, flexShrink: 0, paddingTop: 2 }}>
                {formatTs(evt.timestamp)}
              </span>
              {/* 类型标签 */}
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600, flexShrink: 0,
                background: catCfg.color + '22', color: catCfg.color, minWidth: 48, textAlign: 'center',
              }}>
                {catCfg.label}
              </span>
              {/* 内容 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 2 }}>{evt.title}</div>
                <div style={{ fontSize: 12, color: C.text3 }}>{evt.description}</div>
              </div>
              {/* 来源 */}
              <span style={{ fontSize: 11, color: C.text3, flexShrink: 0 }}>{evt.source}</span>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: C.text3, fontSize: 14 }}>
            暂无事件
          </div>
        )}
      </div>
    </div>
  );
}
