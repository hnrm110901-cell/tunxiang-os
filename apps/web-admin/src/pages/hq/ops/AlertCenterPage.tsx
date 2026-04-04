/**
 * 异常中心 — 异常列表(按严重度)、异常详情+处理记录、统计图表
 * 调用 GET /api/v1/analytics/alerts/*
 */
import { useState, useEffect } from 'react';
import { apiGet, apiPatch } from '../../../api/client';

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

interface AlertSummary {
  critical: number;
  warning: number;
  info: number;
  by_category: Record<AlertCategory, number>;
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

export function AlertCenterPage() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [summary, setSummary] = useState<AlertSummary>({
    critical: 0,
    warning: 0,
    info: 0,
    by_category: { cost: 0, quality: 0, efficiency: 0, compliance: 0, equipment: 0 },
  });
  const [loading, setLoading] = useState(true);

  const [sevFilter, setSevFilter] = useState<AlertSeverity | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<AlertStatus | 'all'>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // 加载告警列表
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const statusParam = statusFilter !== 'all' ? `&status=${statusFilter}` : '';
    const sevParam = sevFilter !== 'all' ? `&severity=${sevFilter}` : '';

    Promise.all([
      apiGet<AlertItem[]>(`/api/v1/analytics/alerts?${statusParam}${sevParam}`).catch(() => [] as AlertItem[]),
      apiGet<AlertSummary>('/api/v1/analytics/alerts/summary').catch(() => null),
    ]).then(([alertData, summaryData]) => {
      if (cancelled) return;
      setAlerts(alertData);
      if (alertData.length > 0 && selectedId === null) {
        setSelectedId(alertData[0].id);
      }
      if (summaryData) {
        setSummary(summaryData);
      } else {
        // 从列表数据推算 summary
        setSummary({
          critical: alertData.filter((a) => a.severity === 'critical').length,
          warning: alertData.filter((a) => a.severity === 'warning').length,
          info: alertData.filter((a) => a.severity === 'info').length,
          by_category: {
            cost: alertData.filter((a) => a.category === 'cost').length,
            quality: alertData.filter((a) => a.category === 'quality').length,
            efficiency: alertData.filter((a) => a.category === 'efficiency').length,
            compliance: alertData.filter((a) => a.category === 'compliance').length,
            equipment: alertData.filter((a) => a.category === 'equipment').length,
          },
        });
      }
      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [sevFilter, statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // 标记已解决
  const handleResolve = async (id: string) => {
    try {
      await apiPatch<AlertItem>(`/api/v1/analytics/alerts/${id}/resolve`, { resolution: '已解决' });
      // 更新本地状态
      setAlerts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: 'resolved' as AlertStatus } : a))
      );
    } catch {
      // 静默失败，不影响 UI
    }
  };

  const filtered = alerts.filter((a) => {
    if (sevFilter !== 'all' && a.severity !== sevFilter) return false;
    if (statusFilter !== 'all' && a.status !== statusFilter) return false;
    return true;
  });

  const selected = alerts.find((a) => a.id === selectedId);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>异常中心</h2>
        <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
          <span style={{ color: '#ff4d4f', fontWeight: 600 }}>严重 {summary.critical}</span>
          <span style={{ color: '#faad14', fontWeight: 600 }}>警告 {summary.warning}</span>
          <span style={{ color: '#1890ff', fontWeight: 600 }}>提示 {summary.info}</span>
        </div>
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {(Object.keys(CATEGORY_CONFIG) as AlertCategory[]).map((cat) => (
          <div key={cat} style={{
            background: '#112228', borderRadius: 8, padding: 14, textAlign: 'center',
          }}>
            <div style={{ fontSize: 20, marginBottom: 4 }}>{CATEGORY_CONFIG[cat].icon}</div>
            <div style={{ fontSize: 20, fontWeight: 'bold' }}>{summary.by_category[cat]}</div>
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
          {loading ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 40 }}>加载中...</div>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 40 }}>暂无异常记录</div>
          ) : (
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
          )}
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
                <button
                  onClick={() => handleResolve(selected.id)}
                  style={{
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
