/**
 * 模板配置 — 检查表模板、超时阈值、毛利底线、角色权限
 */
import { useState, useEffect } from 'react';
import { apiGet, apiPost } from '../../../api/client';

type SettingsTab = 'checklist' | 'threshold' | 'margin' | 'roles';

// ---------- 类型 ----------
interface ChecklistTemplate {
  id: string;
  name: string;
  items: number;
  lastUpdate: string;
  enabled: boolean;
}

interface ThresholdItem {
  id: string;
  name: string;
  value: number;
  unit: string;
  scope: string;
  desc: string;
}

interface MarginItem {
  category: string;
  minMargin: number;
  currentAvg: number;
  status: 'ok' | 'warn';
}

interface RoleConfig {
  id: string;
  name: string;
  permissions: string[];
  users: number;
}

interface SystemSettings {
  checklists?: ChecklistTemplate[];
  thresholds?: ThresholdItem[];
  margins?: MarginItem[];
}

// ---------- 保存设置 ----------
async function saveSystemSetting(key: string, value: unknown): Promise<void> {
  await apiPost('/api/v1/system/settings', { key, value });
}

// ---------- 主组件 ----------
export function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('checklist');

  const [checklists, setChecklists] = useState<ChecklistTemplate[]>([]);
  const [thresholds, setThresholds] = useState<ThresholdItem[]>([]);
  const [margins, setMargins] = useState<MarginItem[]>([]);
  const [roles, setRoles] = useState<RoleConfig[]>([]);
  const [loading, setLoading] = useState(false);

  // 加载系统配置
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    Promise.all([
      apiGet<SystemSettings>('/api/v1/system/settings').catch(() => null),
      apiGet<{ roles: RoleConfig[] }>('/api/v1/org/role-configs').catch(() => null),
    ]).then(([settings, roleData]) => {
      if (cancelled) return;
      if (settings) {
        setChecklists(settings.checklists ?? []);
        setThresholds(settings.thresholds ?? []);
        setMargins(settings.margins ?? []);
      }
      if (roleData) {
        setRoles(roleData.roles ?? []);
      }
      setLoading(false);
    });

    return () => { cancelled = true; };
  }, []);

  // 切换检查表启用状态
  const handleToggleChecklist = async (id: string, enabled: boolean) => {
    try {
      await saveSystemSetting(`checklist.${id}.enabled`, !enabled);
      setChecklists((prev) =>
        prev.map((cl) => (cl.id === id ? { ...cl, enabled: !cl.enabled } : cl))
      );
    } catch {
      // 静默失败
    }
  };

  // 修改阈值
  const handleEditThreshold = async (id: string, currentValue: number) => {
    const input = window.prompt('请输入新阈值', String(currentValue));
    if (input === null) return;
    const newVal = parseFloat(input);
    if (isNaN(newVal)) return;
    try {
      await saveSystemSetting(`threshold.${id}.value`, newVal);
      setThresholds((prev) =>
        prev.map((t) => (t.id === id ? { ...t, value: newVal } : t))
      );
    } catch {
      // 静默失败
    }
  };

  // 修改毛利底线
  const handleEditMargin = async (category: string, currentMin: number) => {
    const input = window.prompt(`请输入 ${category} 的毛利底线 (%)`, String(currentMin));
    if (input === null) return;
    const newVal = parseFloat(input);
    if (isNaN(newVal)) return;
    try {
      await saveSystemSetting(`margin.${category}.minMargin`, newVal);
      setMargins((prev) =>
        prev.map((m) => {
          if (m.category !== category) return m;
          const gap = m.currentAvg - newVal;
          return { ...m, minMargin: newVal, status: gap >= 0 ? 'ok' : 'warn' };
        })
      );
    } catch {
      // 静默失败
    }
  };

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

      {loading && (
        <div style={{ textAlign: 'center', color: '#666', padding: 40 }}>加载中...</div>
      )}

      {/* 检查表模板 */}
      {!loading && tab === 'checklist' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>检查表模板</h3>
            <button style={{
              padding: '6px 16px', borderRadius: 6, border: 'none',
              background: '#FF6B2C', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>+ 新建模板</button>
          </div>
          {checklists.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无检查表模板</div>
          ) : (
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
                {checklists.map((cl) => (
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
                      <span
                        style={{ color: '#999', cursor: 'pointer', fontSize: 12 }}
                        onClick={() => handleToggleChecklist(cl.id, cl.enabled)}
                      >
                        {cl.enabled ? '停用' : '启用'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 超时阈值配置 */}
      {!loading && tab === 'threshold' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>预警阈值配置</h3>
          {thresholds.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无阈值配置</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {thresholds.map((t) => (
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
                    <span
                      style={{ color: '#FF6B2C', cursor: 'pointer', fontSize: 12 }}
                      onClick={() => handleEditThreshold(t.id, t.value)}
                    >
                      修改
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 毛利底线配置 */}
      {!loading && tab === 'margin' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>毛利底线配置</h3>
            <div style={{ fontSize: 12, color: '#999' }}>
              硬约束：任何折扣/赠送不可使单笔毛利低于设定阈值
            </div>
          </div>
          {margins.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无毛利底线配置</div>
          ) : (
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
                {margins.map((m) => {
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
                        <span
                          style={{ color: '#FF6B2C', cursor: 'pointer', fontSize: 12 }}
                          onClick={() => handleEditMargin(m.category, m.minMargin)}
                        >
                          修改
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 角色权限管理 */}
      {!loading && tab === 'roles' && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>角色权限管理</h3>
            <button style={{
              padding: '6px 16px', borderRadius: 6, border: 'none',
              background: '#FF6B2C', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>+ 新建角色</button>
          </div>
          {roles.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无角色配置</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {roles.map((r) => (
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
          )}
        </div>
      )}
    </div>
  );
}
