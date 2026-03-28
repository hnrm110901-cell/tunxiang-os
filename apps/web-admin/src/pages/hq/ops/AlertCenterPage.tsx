/**
 * 异常中心 — 异常列表(按严重度)、异常详情+处理记录、统计图表
 * 调用 GET /api/v1/dashboard/alerts/*
 */
import { useState } from 'react';

type AlertSeverity = 'critical' | 'warning' | 'info';
type AlertCategory = 'cost' | 'quality' | 'efficiency' | 'compliance' | 'equipment';
type AlertStatus = 'open' | 'processing' | 'resolved';

interface AlertItem {
  id: string;
  severity: AlertSeverity;
  category: AlertCategory;
  store: string;
  title: string;
  detail: string;
  time: string;
  status: AlertStatus;
  handler?: string;
  logs: { time: string; action: string; operator: string }[];
}

const SEVERITY_CONFIG: Record<AlertSeverity, { label: string; color: string }> = {
  critical: { label: '严重', color: '#ff4d4f' },
  warning: { label: '警告', color: '#faad14' },
  info: { label: '提示', color: '#1890ff' },
};

const CATEGORY_CONFIG: Record<AlertCategory, { label: string; icon: string }> = {
  cost: { label: '成本', icon: '💰' },
  quality: { label: '品质', icon: '🍽' },
  efficiency: { label: '效率', icon: '⏱' },
  compliance: { label: '合规', icon: '📋' },
  equipment: { label: '设备', icon: '🔧' },
};

const STATUS_CONFIG: Record<AlertStatus, { label: string; color: string }> = {
  open: { label: '待处理', color: '#ff4d4f' },
  processing: { label: '处理中', color: '#faad14' },
  resolved: { label: '已解决', color: '#52c41a' },
};

const MOCK_ALERTS: AlertItem[] = [
  {
    id: 'ALT001', severity: 'critical', category: 'cost', store: '河西店',
    title: '食材成本率超标', detail: '河西店当日食材成本率达到38.5%，超过设定阈值35%。主要原因：鲈鱼损耗¥320、蔬菜类过期报损¥180。',
    time: '10:32', status: 'open', logs: [
      { time: '10:32', action: '系统自动检测并生成预警', operator: '系统' },
    ],
  },
  {
    id: 'ALT002', severity: 'critical', category: 'quality', store: '星沙店',
    title: '出餐超时连续告警', detail: '星沙店午市出餐超时达12单，占比15.3%。平均超时8.5分钟。后厨报告：煎炸工位一人请假。',
    time: '12:45', status: 'processing', handler: '陈店长', logs: [
      { time: '12:45', action: '系统自动检测并生成预警', operator: '系统' },
      { time: '12:50', action: '已通知店长处理', operator: '系统' },
      { time: '13:00', action: '调配服务员支援后厨', operator: '陈店长' },
    ],
  },
  {
    id: 'ALT003', severity: 'warning', category: 'compliance', store: '芙蓉路店',
    title: '折扣审批超限提醒', detail: '今日折扣总额¥1,280，接近日限额¥1,500（85.3%）。如继续审批需总部授权。',
    time: '15:20', status: 'open', logs: [
      { time: '15:20', action: '折扣额度使用超85%预警', operator: '系统' },
    ],
  },
  {
    id: 'ALT004', severity: 'warning', category: 'efficiency', store: '岳麓店',
    title: '翻台率持续偏低', detail: '岳麓店近3天翻台率分别为2.1、1.9、2.0，低于目标值2.5。建议分析原因并制定提升方案。',
    time: '09:00', status: 'open', logs: [
      { time: '09:00', action: '周期性指标检测预警', operator: '系统' },
    ],
  },
  {
    id: 'ALT005', severity: 'info', category: 'equipment', store: '开福店',
    title: 'POS打印机墨量不足', detail: '开福店1号POS打印机墨量低于20%，预计可打印约200张小票。建议提前更换。',
    time: '08:15', status: 'resolved', handler: '李收银', logs: [
      { time: '08:15', action: '设备墨量低预警', operator: '系统' },
      { time: '09:30', action: '已更换打印纸和墨盒', operator: '李收银' },
      { time: '09:35', action: '确认打印正常，关闭预警', operator: '李收银' },
    ],
  },
  {
    id: 'ALT006', severity: 'warning', category: 'cost', store: '芙蓉路店',
    title: '鲈鱼库存临近效期', detail: '芙蓉路店鲈鱼库存5份，其中3份明日到期。建议今日消化或做特价处理。',
    time: '07:00', status: 'processing', handler: '张厨师长', logs: [
      { time: '07:00', action: '食材效期预警', operator: '系统' },
      { time: '07:30', action: '已安排今日推荐菜单增加鲈鱼菜品', operator: '张厨师长' },
    ],
  },
];

// 统计
const statBySeverity = (severity: AlertSeverity) => MOCK_ALERTS.filter((a) => a.severity === severity).length;
const statByCategory = (cat: AlertCategory) => MOCK_ALERTS.filter((a) => a.category === cat).length;

export function AlertCenterPage() {
  const [sevFilter, setSevFilter] = useState<AlertSeverity | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<AlertStatus | 'all'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(MOCK_ALERTS[0]?.id || null);

  const filtered = MOCK_ALERTS.filter((a) => {
    if (sevFilter !== 'all' && a.severity !== sevFilter) return false;
    if (statusFilter !== 'all' && a.status !== statusFilter) return false;
    return true;
  });

  const selected = MOCK_ALERTS.find((a) => a.id === selectedId);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>异常中心</h2>
        <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
          <span style={{ color: '#ff4d4f', fontWeight: 600 }}>严重 {statBySeverity('critical')}</span>
          <span style={{ color: '#faad14', fontWeight: 600 }}>警告 {statBySeverity('warning')}</span>
          <span style={{ color: '#1890ff', fontWeight: 600 }}>提示 {statBySeverity('info')}</span>
        </div>
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {(Object.keys(CATEGORY_CONFIG) as AlertCategory[]).map((cat) => (
          <div key={cat} style={{
            background: '#112228', borderRadius: 8, padding: 14, textAlign: 'center',
          }}>
            <div style={{ fontSize: 20, marginBottom: 4 }}>{CATEGORY_CONFIG[cat].icon}</div>
            <div style={{ fontSize: 20, fontWeight: 'bold' }}>{statByCategory(cat)}</div>
            <div style={{ fontSize: 11, color: '#999' }}>{CATEGORY_CONFIG[cat].label}</div>
          </div>
        ))}
      </div>

      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{ fontSize: 11, color: '#666', lineHeight: '26px' }}>严重度:</span>
          {(['all', 'critical', 'warning', 'info'] as const).map((s) => (
            <button key={s} onClick={() => setSevFilter(s)} style={{
              padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
              background: sevFilter === s ? '#1a2a33' : 'transparent',
              color: sevFilter === s ? '#fff' : '#666',
            }}>{s === 'all' ? '全部' : SEVERITY_CONFIG[s].label}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{ fontSize: 11, color: '#666', lineHeight: '26px' }}>状态:</span>
          {(['all', 'open', 'processing', 'resolved'] as const).map((s) => (
            <button key={s} onClick={() => setStatusFilter(s)} style={{
              padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
              background: statusFilter === s ? '#1a2a33' : 'transparent',
              color: statusFilter === s ? '#fff' : '#666',
            }}>{s === 'all' ? '全部' : STATUS_CONFIG[s].label}</button>
          ))}
        </div>
      </div>

      {/* 主体：左列表 + 右详情 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 异常列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filtered.map((a) => (
              <div
                key={a.id}
                onClick={() => setSelectedId(a.id)}
                style={{
                  padding: 14, borderRadius: 8, cursor: 'pointer',
                  background: selectedId === a.id ? 'rgba(255,107,44,0.08)' : '#0B1A20',
                  border: selectedId === a.id ? '1px solid #FF6B2C' : '1px solid #1a2a33',
                  borderLeft: `3px solid ${SEVERITY_CONFIG[a.severity].color}`,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 3, fontWeight: 600,
                      background: `${SEVERITY_CONFIG[a.severity].color}20`,
                      color: SEVERITY_CONFIG[a.severity].color,
                    }}>{SEVERITY_CONFIG[a.severity].label}</span>
                    <span style={{ fontSize: 12 }}>{CATEGORY_CONFIG[a.category].icon}</span>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{a.title}</span>
                  </div>
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 3,
                    background: `${STATUS_CONFIG[a.status].color}20`,
                    color: STATUS_CONFIG[a.status].color,
                  }}>{STATUS_CONFIG[a.status].label}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#666' }}>
                  <span>{a.store}</span>
                  <span>{a.time}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 异常详情 + 处理记录 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          {selected ? (
            <>
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                    background: `${SEVERITY_CONFIG[selected.severity].color}20`,
                    color: SEVERITY_CONFIG[selected.severity].color,
                  }}>{SEVERITY_CONFIG[selected.severity].label}</span>
                  <span style={{
                    padding: '2px 8px', borderRadius: 4, fontSize: 11,
                    background: `${STATUS_CONFIG[selected.status].color}20`,
                    color: STATUS_CONFIG[selected.status].color,
                  }}>{STATUS_CONFIG[selected.status].label}</span>
                </div>
                <h3 style={{ margin: '0 0 4px', fontSize: 18 }}>{selected.title}</h3>
                <div style={{ fontSize: 12, color: '#999' }}>
                  {selected.store} | {selected.time}
                  {selected.handler && ` | 处理人: ${selected.handler}`}
                </div>
              </div>

              <div style={{
                padding: 14, borderRadius: 8, background: '#0B1A20', marginBottom: 16,
                fontSize: 13, color: '#ccc', lineHeight: 1.8,
              }}>
                {selected.detail}
              </div>

              {/* 处理记录时间线 */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>处理记录</div>
                <div style={{ position: 'relative', paddingLeft: 20 }}>
                  {selected.logs.map((log, i) => (
                    <div key={i} style={{ position: 'relative', paddingBottom: i < selected.logs.length - 1 ? 16 : 0 }}>
                      {/* 时间线圆点 */}
                      <div style={{
                        position: 'absolute', left: -20, top: 4,
                        width: 8, height: 8, borderRadius: '50%',
                        background: i === selected.logs.length - 1 ? '#FF6B2C' : '#1a2a33',
                      }} />
                      {i < selected.logs.length - 1 && (
                        <div style={{
                          position: 'absolute', left: -17, top: 14, width: 2, height: 'calc(100% - 6px)',
                          background: '#1a2a33',
                        }} />
                      )}
                      <div style={{ fontSize: 12 }}>
                        <span style={{ color: '#999' }}>{log.time}</span>
                        <span style={{ color: '#FF6B2C', marginLeft: 8 }}>{log.operator}</span>
                        <div style={{ color: '#ccc', marginTop: 2 }}>{log.action}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {selected.status !== 'resolved' && (
                <button style={{
                  width: '100%', padding: '10px 0', borderRadius: 8, border: 'none',
                  background: '#FF6B2C', color: '#fff', fontSize: 14, fontWeight: 600,
                  cursor: 'pointer',
                }}>标记为已解决</button>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', color: '#666', padding: 60 }}>选择一条异常记录查看详情</div>
          )}
        </div>
      </div>

      {/* ECharts 占位：统计图表 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{
          background: '#112228', borderRadius: 8, padding: 20,
          minHeight: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ textAlign: 'center', color: '#666' }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>📊</div>
            <div style={{ fontSize: 13 }}>异常类型分布饼图 — ECharts 接入点</div>
            <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>GET /api/v1/dashboard/alerts/stats/by-category</div>
          </div>
        </div>
        <div style={{
          background: '#112228', borderRadius: 8, padding: 20,
          minHeight: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ textAlign: 'center', color: '#666' }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>🏪</div>
            <div style={{ fontSize: 13 }}>门店异常数量柱状图 — ECharts 接入点</div>
            <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>GET /api/v1/dashboard/alerts/stats/by-store</div>
          </div>
        </div>
      </div>
    </div>
  );
}
