/**
 * SystemPage — 系统设置
 * 系统配置（基础/通知/备份/集成）+ 只读系统信息
 */

import React, { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../api';

// ─── 类型定义 ───

interface SystemConfig {
  key: string;
  value: string;
  label: string;
  description?: string;
  type: 'text' | 'boolean' | 'number' | 'select';
  group: 'basic' | 'notification' | 'backup' | 'integration';
  options?: string[];
  readonly?: boolean;
}

interface SystemInfo {
  version: string;
  uptime_seconds: number;
  db_status: string;
  db_version: string;
  api_version: string;
  environment: string;
  last_backup_at: string | null;
}

// ─── 样式 ───

const containerStyle: React.CSSProperties = {
  backgroundColor: '#0d1e28',
  color: '#E0E0E0',
  minHeight: '100vh',
  padding: '24px 32px',
  fontFamily: 'system-ui, -apple-system, sans-serif',
};

const headerStyle: React.CSSProperties = {
  fontSize: '24px',
  fontWeight: 700,
  color: '#FFFFFF',
  marginBottom: '4px',
};

const subtitleStyle: React.CSSProperties = {
  fontSize: '13px',
  color: '#8899A6',
  marginBottom: '24px',
};

const topRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 340px',
  gap: '20px',
  marginBottom: '20px',
};

const cardStyle: React.CSSProperties = {
  backgroundColor: '#1a2a33',
  borderRadius: '12px',
  padding: '20px',
  border: '1px solid #1E3A47',
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: '15px',
  fontWeight: 600,
  color: '#4FC3F7',
  marginBottom: '16px',
};

const tabBarStyle: React.CSSProperties = {
  display: 'flex',
  gap: '4px',
  marginBottom: '16px',
  borderBottom: '1px solid #1E3A47',
  paddingBottom: '0',
};

const configRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
  padding: '12px 0',
  borderBottom: '1px solid #1E3A47',
  gap: '12px',
};

const inputStyle: React.CSSProperties = {
  backgroundColor: '#0d1e28',
  border: '1px solid #2a4a5a',
  color: '#E0E0E0',
  borderRadius: '6px',
  padding: '6px 10px',
  fontSize: '13px',
  width: '200px',
  outline: 'none',
};

const infoRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  padding: '10px 0',
  borderBottom: '1px solid #1E3A47',
  fontSize: '13px',
};

const loadingStyle: React.CSSProperties = {
  color: '#8899A6',
  fontSize: '13px',
  padding: '20px 0',
  textAlign: 'center',
};

const errorStyle: React.CSSProperties = {
  color: '#EF5350',
  fontSize: '13px',
  padding: '12px',
  backgroundColor: 'rgba(239,83,80,0.08)',
  borderRadius: '8px',
  marginBottom: '12px',
};

const successStyle: React.CSSProperties = {
  color: '#66BB6A',
  fontSize: '13px',
  padding: '12px',
  backgroundColor: 'rgba(102,187,106,0.08)',
  borderRadius: '8px',
  marginBottom: '12px',
};

const btnPrimaryStyle: React.CSSProperties = {
  backgroundColor: '#4FC3F7',
  color: '#0d1e28',
  border: 'none',
  padding: '9px 20px',
  borderRadius: '8px',
  cursor: 'pointer',
  fontSize: '13px',
  fontWeight: 600,
};

const btnSecondaryStyle: React.CSSProperties = {
  backgroundColor: '#1E3A47',
  color: '#E0E0E0',
  border: '1px solid #2a4a5a',
  padding: '8px 16px',
  borderRadius: '8px',
  cursor: 'pointer',
  fontSize: '13px',
};

// ─── 配置分组信息 ───

const GROUPS: { key: SystemConfig['group']; label: string; icon: string }[] = [
  { key: 'basic', label: '基础设置', icon: '⚙' },
  { key: 'notification', label: '通知设置', icon: '🔔' },
  { key: 'backup', label: '数据备份', icon: '💾' },
  { key: 'integration', label: '集成设置', icon: '🔗' },
];

// ─── 工具函数 ───

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d} 天`);
  if (h > 0) parts.push(`${h} 小时`);
  parts.push(`${m} 分钟`);
  return parts.join(' ');
}

function dbStatusColor(status: string): string {
  return status === 'healthy' || status === 'ok' ? '#66BB6A' : '#EF5350';
}

function dbStatusLabel(status: string): string {
  const map: Record<string, string> = {
    healthy: '健康',
    ok: '正常',
    degraded: '降级',
    error: '异常',
    unknown: '未知',
  };
  return map[status] ?? status;
}

// ─── 配置项编辑器 ───

function ConfigEditor({
  config,
  value,
  onChange,
}: {
  config: SystemConfig;
  value: string;
  onChange: (val: string) => void;
}) {
  if (config.readonly) {
    return <span style={{ color: '#8899A6', fontSize: '13px' }}>{value || '—'}</span>;
  }

  if (config.type === 'boolean') {
    const checked = value === 'true';
    return (
      <div
        onClick={() => onChange(checked ? 'false' : 'true')}
        style={{
          width: '44px',
          height: '24px',
          borderRadius: '12px',
          backgroundColor: checked ? '#4FC3F7' : '#1E3A47',
          cursor: 'pointer',
          position: 'relative',
          transition: 'background-color 0.2s',
          border: '1px solid #2a4a5a',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: '3px',
            left: checked ? '21px' : '3px',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            backgroundColor: '#FFFFFF',
            transition: 'left 0.2s',
          }}
        />
      </div>
    );
  }

  if (config.type === 'select' && config.options) {
    return (
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ ...inputStyle, width: '160px' }}
      >
        {config.options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    );
  }

  return (
    <input
      type={config.type === 'number' ? 'number' : 'text'}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={inputStyle}
    />
  );
}

// ─── 主组件 ───

export function SystemPage() {
  const [configs, setConfigs] = useState<SystemConfig[]>([]);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [configsLoading, setConfigsLoading] = useState(true);
  const [configsError, setConfigsError] = useState<string | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null);
  const [sysInfoLoading, setSysInfoLoading] = useState(true);

  const [activeGroup, setActiveGroup] = useState<SystemConfig['group']>('basic');

  const loadConfigs = useCallback(async () => {
    setConfigsLoading(true);
    setConfigsError(null);
    try {
      const data = await txFetchData<{ items: SystemConfig[] }>('/api/v1/system/configs');
      const items = data.items ?? [];
      setConfigs(items);
      const vals: Record<string, string> = {};
      items.forEach((c) => { vals[c.key] = c.value; });
      setEditValues(vals);
    } catch (e) {
      setConfigsError(e instanceof Error ? e.message : '配置加载失败');
    } finally {
      setConfigsLoading(false);
    }
  }, []);

  const loadSysInfo = useCallback(async () => {
    setSysInfoLoading(true);
    try {
      const data = await txFetchData<SystemInfo>('/api/v1/system/info');
      setSysInfo(data);
    } catch {
      setSysInfo(null);
    } finally {
      setSysInfoLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfigs();
    loadSysInfo();
  }, [loadConfigs, loadSysInfo]);

  const handleSave = async () => {
    setSaveLoading(true);
    setSaveMsg(null);
    try {
      await txFetchData('/api/v1/system/configs', {
        method: 'PUT',
        body: JSON.stringify({ configs: editValues }),
      });
      setSaveMsg({ type: 'ok', text: '配置保存成功' });
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (e) {
      setSaveMsg({ type: 'err', text: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setSaveLoading(false);
    }
  };

  const activeConfigs = configs.filter((c) => c.group === activeGroup);

  const sysInfoItems: { label: string; value: string; color?: string }[] = sysInfo
    ? [
        { label: '系统版本', value: sysInfo.version },
        { label: 'API 版本', value: sysInfo.api_version },
        { label: '运行环境', value: sysInfo.environment },
        {
          label: '数据库状态',
          value: dbStatusLabel(sysInfo.db_status),
          color: dbStatusColor(sysInfo.db_status),
        },
        { label: '数据库版本', value: sysInfo.db_version },
        { label: '运行时长', value: formatUptime(sysInfo.uptime_seconds) },
        {
          label: '最近备份',
          value: sysInfo.last_backup_at
            ? new Date(sysInfo.last_backup_at).toLocaleString('zh-CN')
            : '尚未备份',
        },
      ]
    : [];

  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>系统设置</h1>
      <p style={subtitleStyle}>基础设置 / 通知 / 数据备份 / 集成配置</p>

      <div style={topRowStyle}>
        {/* 配置编辑区 */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={cardTitleStyle}>系统配置</div>
            <button
              onClick={handleSave}
              disabled={saveLoading || configsLoading}
              style={{ ...btnPrimaryStyle, opacity: saveLoading ? 0.7 : 1 }}
            >
              {saveLoading ? '保存中...' : '保存配置'}
            </button>
          </div>

          {saveMsg && (
            <div style={saveMsg.type === 'ok' ? successStyle : errorStyle}>
              {saveMsg.text}
            </div>
          )}
          {configsError && <div style={errorStyle}>{configsError}</div>}

          {/* 分组标签 */}
          <div style={tabBarStyle}>
            {GROUPS.map((g) => {
              const isActive = activeGroup === g.key;
              return (
                <button
                  key={g.key}
                  onClick={() => setActiveGroup(g.key)}
                  style={{
                    backgroundColor: isActive ? '#4FC3F7' : 'transparent',
                    color: isActive ? '#0d1e28' : '#8899A6',
                    border: 'none',
                    padding: '7px 14px',
                    borderRadius: '8px 8px 0 0',
                    cursor: 'pointer',
                    fontSize: '13px',
                    fontWeight: isActive ? 600 : 400,
                    marginBottom: '-1px',
                  }}
                >
                  {g.label}
                </button>
              );
            })}
          </div>

          {configsLoading ? (
            <div style={loadingStyle}>加载配置中...</div>
          ) : activeConfigs.length === 0 ? (
            <div style={loadingStyle}>该分组暂无配置项</div>
          ) : (
            activeConfigs.map((c) => (
              <div key={c.key} style={configRowStyle}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: '2px' }}>
                    {c.label}
                  </div>
                  {c.description && (
                    <div style={{ fontSize: '12px', color: '#8899A6' }}>{c.description}</div>
                  )}
                </div>
                <ConfigEditor
                  config={c}
                  value={editValues[c.key] ?? c.value}
                  onChange={(val) => setEditValues((prev) => ({ ...prev, [c.key]: val }))}
                />
              </div>
            ))
          )}
        </div>

        {/* 系统信息（只读） */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={cardStyle}>
            <div style={cardTitleStyle}>系统信息</div>
            {sysInfoLoading ? (
              <div style={loadingStyle}>加载中...</div>
            ) : sysInfo === null ? (
              <div style={{ ...loadingStyle, color: '#EF5350' }}>系统信息不可用</div>
            ) : (
              sysInfoItems.map((item) => (
                <div key={item.label} style={infoRowStyle}>
                  <span style={{ color: '#8899A6' }}>{item.label}</span>
                  <span style={{ color: item.color ?? '#E0E0E0', fontWeight: 500 }}>
                    {item.value}
                  </span>
                </div>
              ))
            )}
          </div>

          {/* 快捷操作 */}
          <div style={cardStyle}>
            <div style={cardTitleStyle}>快捷操作</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <button
                style={btnSecondaryStyle}
                onClick={() => {
                  txFetchData('/api/v1/system/cache/clear', { method: 'POST' }).catch(() => {});
                }}
              >
                清除系统缓存
              </button>
              <button
                style={btnSecondaryStyle}
                onClick={() => {
                  txFetchData('/api/v1/system/backup/trigger', { method: 'POST' }).catch(() => {});
                }}
              >
                立即备份数据
              </button>
              <button
                style={btnSecondaryStyle}
                onClick={() => {
                  txFetchData('/api/v1/system/health').catch(() => {});
                  loadSysInfo();
                }}
              >
                刷新系统状态
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
