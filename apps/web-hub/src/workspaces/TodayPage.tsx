/**
 * Today 页面 — 今日看板
 *
 * 问候语 + KPI卡片 + 待办 + 活跃Incident + 续约提醒
 */
import { useState, useEffect } from 'react';
import { hubGet } from '../api/hubApi';

const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6',
};

// ── 类型 ──

interface TodoItem {
  id: string;
  title: string;
  priority: 'high' | 'medium' | 'low';
  due: string;
  done: boolean;
}

interface AlertItem {
  id: string;
  severity: 'critical' | 'warning';
  title: string;
  source: string;
  time: string;
}

interface IncidentItem {
  id: string;
  title: string;
  status: 'active' | 'investigating' | 'resolved';
  started: string;
  affected: string[];
}

interface RenewalItem {
  id: string;
  merchant: string;
  contract_end: string;
  days_left: number;
  value_yuan: number;
}

interface TodayData {
  todos: TodoItem[];
  alerts: AlertItem[];
  incidents: IncidentItem[];
  renewals: RenewalItem[];
  kpi: { active_alerts: number; online_nodes: number; today_tickets: number; service_availability: number };
}

// ── Mock ──

const MOCK_TODAY: TodayData = {
  kpi: { active_alerts: 3, online_nodes: 7, today_tickets: 5, service_availability: 99.87 },
  todos: [
    { id: 'td1', title: '审核 tx-supply 降级原因并决定是否回滚', priority: 'high', due: '2026-04-26 12:00', done: false },
    { id: 'td2', title: '检查 mcp-server 启动失败日志', priority: 'high', due: '2026-04-26 14:00', done: false },
    { id: 'td3', title: '更新 TX-MAC-010 磁盘清理，解除隔离', priority: 'medium', due: '2026-04-26 17:00', done: false },
  ],
  alerts: [
    { id: 'al1', severity: 'critical', title: 'mcp-server 错误率 2.5%，持续超阈值', source: 'mcp-server', time: '08:15' },
    { id: 'al2', severity: 'warning', title: 'tx-supply P95延迟 180ms，接近 SLO 上限', source: 'tx-supply', time: '08:30' },
    { id: 'al3', severity: 'warning', title: 'TX-MAC-010 磁盘使用率 88%', source: '边缘节点', time: '07:00' },
  ],
  incidents: [
    { id: 'inc1', title: 'mcp-server 服务不可用', status: 'investigating', started: '2026-04-26 07:45', affected: ['mcp-server'] },
  ],
  renewals: [
    { id: 'rn1', merchant: '最黔线', contract_end: '2026-05-15', days_left: 19, value_yuan: 36000 },
    { id: 'rn2', merchant: '尚宫厨', contract_end: '2026-06-01', days_left: 36, value_yuan: 48000 },
  ],
};

// ── Helpers ──

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 6) return '凌晨好';
  if (h < 12) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

function formatTime(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  return `${y}年${m}月${d}日 星期${weekdays[now.getDay()]}`;
}

const PRIORITY_COLOR: Record<string, string> = { high: C.red, medium: C.yellow, low: C.text3 };
const PRIORITY_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' };
const SEVERITY_COLOR: Record<string, string> = { critical: C.red, warning: C.yellow };
const INCIDENT_COLOR: Record<string, string> = { active: C.red, investigating: C.yellow, resolved: C.green };
const INCIDENT_LABEL: Record<string, string> = { active: '活跃', investigating: '调查中', resolved: '已解决' };

// ── Main ──

export function TodayPage() {
  const [data, setData] = useState<TodayData>(MOCK_TODAY);
  const [time, setTime] = useState(formatTime());

  useEffect(() => {
    hubGet<TodayData>('/today')
      .then(d => { if (d && d.kpi) setData(d); })
      .catch(() => { /* Mock */ });
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setTime(formatTime()), 60000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{ color: C.text }}>
      {/* 问候语 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 24, fontWeight: 700, color: C.text, marginBottom: 4 }}>
          {getGreeting()}，运维团队
        </div>
        <div style={{ fontSize: 13, color: C.text3 }}>{time}</div>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 24, flexWrap: 'wrap' }}>
        {[
          { label: '活跃告警', value: data.kpi.active_alerts, color: data.kpi.active_alerts > 0 ? C.red : C.green },
          { label: '在线节点', value: `${data.kpi.online_nodes}/10`, color: C.green },
          { label: '今日工单', value: data.kpi.today_tickets, color: C.orange },
          { label: '服务可用性', value: `${data.kpi.service_availability}%`, color: data.kpi.service_availability >= 99.9 ? C.green : C.yellow },
        ].map(kpi => (
          <div key={kpi.label} style={{ flex: '1 1 180px', background: C.surface, borderRadius: 10, padding: '16px 18px', border: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {/* 左列：待办 + Incident */}
        <div style={{ flex: '1 1 400px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 待办 */}
          <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 12 }}>待办事项</div>
            {data.todos.map(todo => (
              <div key={todo.id} style={{ display: 'flex', gap: 10, padding: '10px 0', borderBottom: `1px solid ${C.border}`, alignItems: 'flex-start' }}>
                <span style={{ width: 16, height: 16, borderRadius: 3, border: `2px solid ${todo.done ? C.green : C.border2}`, background: todo.done ? C.green : 'transparent', flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 2 }}>{todo.title}</div>
                  <div style={{ display: 'flex', gap: 8, fontSize: 11 }}>
                    <span style={{ color: PRIORITY_COLOR[todo.priority], fontWeight: 600 }}>{PRIORITY_LABEL[todo.priority]}</span>
                    <span style={{ color: C.text3 }}>截止 {todo.due}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* 活跃 Incident */}
          {data.incidents.length > 0 && (
            <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.red}44` }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: C.red, marginBottom: 12 }}>活跃 Incident</div>
              {data.incidents.map(inc => (
                <div key={inc.id} style={{ padding: '10px 0', borderBottom: `1px solid ${C.border}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{inc.title}</span>
                    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: INCIDENT_COLOR[inc.status] + '22', color: INCIDENT_COLOR[inc.status], fontWeight: 600 }}>
                      {INCIDENT_LABEL[inc.status]}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: C.text3 }}>
                    开始于 {inc.started} / 影响：{inc.affected.join(', ')}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 右列：告警 + 续约 */}
        <div style={{ flex: '1 1 360px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 告警 */}
          <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 12 }}>告警</div>
            {data.alerts.map(al => (
              <div key={al.id} style={{ display: 'flex', gap: 10, padding: '10px 0', borderBottom: `1px solid ${C.border}`, alignItems: 'flex-start' }}>
                <span style={{ width: 8, height: 8, borderRadius: 4, background: SEVERITY_COLOR[al.severity], flexShrink: 0, marginTop: 5 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: C.text, marginBottom: 2 }}>{al.title}</div>
                  <div style={{ fontSize: 11, color: C.text3 }}>
                    {al.source} / {al.time}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* 续约提醒 */}
          <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 12 }}>续约提醒</div>
            {data.renewals.map(r => (
              <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: `1px solid ${C.border}` }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{r.merchant}</div>
                  <div style={{ fontSize: 11, color: C.text3 }}>到期 {r.contract_end}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: r.days_left <= 30 ? C.yellow : C.text2 }}>
                    {r.days_left}天
                  </div>
                  <div style={{ fontSize: 11, color: C.text3 }}>{(r.value_yuan / 10000).toFixed(1)}万/年</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
