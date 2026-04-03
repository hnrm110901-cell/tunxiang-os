/**
 * 模板配置 — 检查表模板、超时阈值、毛利底线、角色权限
 */
import { useState } from 'react';

type SettingsTab = 'checklist' | 'threshold' | 'margin' | 'roles';

// ---------- Mock 数据 ----------
const MOCK_CHECKLISTS = [
  { id: 'CL001', name: '开店检查表', items: 12, lastUpdate: '2026-03-20', enabled: true },
  { id: 'CL002', name: '闭店检查表', items: 8, lastUpdate: '2026-03-18', enabled: true },
  { id: 'CL003', name: '食安巡检表', items: 15, lastUpdate: '2026-03-15', enabled: true },
  { id: 'CL004', name: '设备维护检查表', items: 6, lastUpdate: '2026-02-28', enabled: false },
];

const MOCK_THRESHOLDS = [
  { id: 'T001', name: '出餐超时阈值', value: 25, unit: '分钟', scope: '全门店', desc: '超出此时间触发出餐超时预警' },
  { id: 'T002', name: '食材成本率上限', value: 35, unit: '%', scope: '全门店', desc: '超出此比例触发成本预警' },
  { id: 'T003', name: '翻台率下限', value: 2.0, unit: '次/天', scope: '全门店', desc: '低于此值触发翻台率预警' },
  { id: 'T004', name: '客诉率上限', value: 2, unit: '%', scope: '全门店', desc: '超出此比例触发客诉预警' },
  { id: 'T005', name: '折扣日限额', value: 1500, unit: '元', scope: '单店', desc: '单店单日折扣总额上限' },
  { id: 'T006', name: '食材临期预警', value: 2, unit: '天', scope: '全门店', desc: '距保质期到期天数内触发预警' },
];

const MOCK_MARGINS = [
  { category: '热菜', minMargin: 55, currentAvg: 62.3, status: 'ok' as const },
  { category: '凉菜', minMargin: 60, currentAvg: 68.1, status: 'ok' as const },
  { category: '汤品', minMargin: 50, currentAvg: 58.5, status: 'ok' as const },
  { category: '主食', minMargin: 45, currentAvg: 52.0, status: 'ok' as const },
  { category: '饮品', minMargin: 65, currentAvg: 72.4, status: 'ok' as const },
  { category: '小吃', minMargin: 50, currentAvg: 48.2, status: 'warn' as const },
];

const MOCK_ROLES = [
  { id: 'R001', name: '总部管理员', permissions: ['全部权限'], users: 2 },
  { id: 'R002', name: '区域经理', permissions: ['查看所辖门店', '审批折扣', '查看分析', '复盘管理'], users: 3 },
  { id: 'R003', name: '门店店长', permissions: ['查看本店数据', '提交审批', '处理异常'], users: 8 },
  { id: 'R004', name: '财务', permissions: ['查看财务数据', '审批退款', '导出报表'], users: 2 },
  { id: 'R005', name: '运营', permissions: ['查看分析', '管理菜单', '查看复盘'], users: 4 },
];

export function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('checklist');

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: 'checklist', label: '检查表模板' },
    { key: 'threshold', label: '超时阈值' },
    { key: 'margin', label: '毛利底线' },
    { key: 'roles', label: '角色权限' },
  ];

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>模板配置</h2>

      {/* Tab 栏 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #1a2a33', paddingBottom: 0 }}>
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: '8px 20px', border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 600,
            background: 'transparent',
            color: tab === t.key ? '#FF6B2C' : '#999',
            borderBottom: tab === t.key ? '2px solid #FF6B2C' : '2px solid transparent',
            marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {/* 检查表模板 */}
      {tab === 'checklist' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>检查表模板</h3>
            <button style={{
              padding: '6px 16px', borderRadius: 6, border: 'none',
              background: '#FF6B2C', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>+ 新建模板</button>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>模板名称</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>检查项数</th>
                <th style={{ padding: '8px 4px' }}>最近更新</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>状态</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_CHECKLISTS.map((cl) => (
                <tr key={cl.id} style={{ borderTop: '1px solid #1a2a33' }}>
                  <td style={{ padding: '12px 4px', fontWeight: 600 }}>{cl.name}</td>
                  <td style={{ padding: '12px 4px', textAlign: 'center' }}>{cl.items}</td>
                  <td style={{ padding: '12px 4px', color: '#999' }}>{cl.lastUpdate}</td>
                  <td style={{ padding: '12px 4px', textAlign: 'center' }}>
                    <span style={{
                      padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                      background: cl.enabled ? 'rgba(82,196,26,0.1)' : 'rgba(153,153,153,0.1)',
                      color: cl.enabled ? '#52c41a' : '#999',
                    }}>{cl.enabled ? '启用' : '停用'}</span>
                  </td>
                  <td style={{ padding: '12px 4px', textAlign: 'right' }}>
                    <span style={{ color: '#FF6B2C', cursor: 'pointer', fontSize: 12, marginRight: 12 }}>编辑</span>
                    <span style={{ color: '#999', cursor: 'pointer', fontSize: 12 }}>{cl.enabled ? '停用' : '启用'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 超时阈值配置 */}
      {tab === 'threshold' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>预警阈值配置</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {MOCK_THRESHOLDS.map((t) => (
              <div key={t.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: 16, borderRadius: 8, background: '#0B1A20',
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>{t.name}</div>
                  <div style={{ fontSize: 11, color: '#666' }}>{t.desc}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 16 }}>
                  <span style={{ fontSize: 10, color: '#999', padding: '2px 6px', borderRadius: 3, background: '#1a2a33' }}>{t.scope}</span>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    padding: '4px 12px', borderRadius: 6, background: '#112228',
                    border: '1px solid #1a2a33',
                  }}>
                    <span style={{ fontSize: 18, fontWeight: 'bold', color: '#FF6B2C' }}>{t.value}</span>
                    <span style={{ fontSize: 11, color: '#999' }}>{t.unit}</span>
                  </div>
                  <span style={{ color: '#FF6B2C', cursor: 'pointer', fontSize: 12 }}>修改</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 毛利底线配置 */}
      {tab === 'margin' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>毛利底线配置</h3>
            <div style={{ fontSize: 12, color: '#999' }}>
              硬约束：任何折扣/赠送不可使单笔毛利低于设定阈值
            </div>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>菜品分类</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>毛利底线</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>当前均值</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>状态</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>余量</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_MARGINS.map((m) => {
                const gap = m.currentAvg - m.minMargin;
                return (
                  <tr key={m.category} style={{ borderTop: '1px solid #1a2a33' }}>
                    <td style={{ padding: '12px 4px', fontWeight: 600 }}>{m.category}</td>
                    <td style={{ padding: '12px 4px', textAlign: 'center', color: '#FF6B2C', fontWeight: 600 }}>{m.minMargin}%</td>
                    <td style={{ padding: '12px 4px', textAlign: 'center' }}>{m.currentAvg}%</td>
                    <td style={{ padding: '12px 4px', textAlign: 'center' }}>
                      <span style={{
                        padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                        background: m.status === 'ok' ? 'rgba(82,196,26,0.1)' : 'rgba(255,77,79,0.1)',
                        color: m.status === 'ok' ? '#52c41a' : '#ff4d4f',
                      }}>{m.status === 'ok' ? '达标' : '预警'}</span>
                    </td>
                    <td style={{
                      padding: '12px 4px', textAlign: 'center',
                      color: gap >= 5 ? '#52c41a' : gap >= 0 ? '#faad14' : '#ff4d4f',
                    }}>
                      {gap >= 0 ? '+' : ''}{gap.toFixed(1)}pp
                    </td>
                    <td style={{ padding: '12px 4px', textAlign: 'right' }}>
                      <span style={{ color: '#FF6B2C', cursor: 'pointer', fontSize: 12 }}>修改</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 角色权限管理 */}
      {tab === 'roles' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>角色权限管理</h3>
            <button style={{
              padding: '6px 16px', borderRadius: 6, border: 'none',
              background: '#FF6B2C', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>+ 新建角色</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {MOCK_ROLES.map((r) => (
              <div key={r.id} style={{
                padding: 16, borderRadius: 8, background: '#0B1A20',
                border: '1px solid #1a2a33',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 15, fontWeight: 600 }}>{r.name}</span>
                    <span style={{
                      padding: '1px 8px', borderRadius: 10, fontSize: 10,
                      background: '#1a2a33', color: '#999',
                    }}>{r.users} 人</span>
                  </div>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <span style={{ color: '#FF6B2C', cursor: 'pointer', fontSize: 12 }}>编辑权限</span>
                    <span style={{ color: '#999', cursor: 'pointer', fontSize: 12 }}>查看成员</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {r.permissions.map((p) => (
                    <span key={p} style={{
                      padding: '2px 8px', borderRadius: 4, fontSize: 10,
                      background: 'rgba(255,107,44,0.08)', color: '#FF6B2C',
                    }}>{p}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
