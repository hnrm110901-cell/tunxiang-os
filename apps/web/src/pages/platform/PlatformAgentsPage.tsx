/**
 * PlatformAgentsPage — /platform/agents
 *
 * Agent 配置与监控：按品牌查看 / 启停 / 编辑各类 Agent 参数
 * 后端 API: /api/v1/agent-configs/{brand_id}
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ZCard, ZBadge, ZButton, ZEmpty, ZAlert, ZDrawer, ZSkeleton,
} from '../../design-system/components';
import { apiClient } from '../../services/api';
import styles from './PlatformAgentsPage.module.css';

// ── Agent 类型元数据 ────────────────────────────────────────────────────────

interface AgentMeta {
  type: string;
  label: string;
  desc: string;
  icon: string;
  category: 'ops' | 'member' | 'finance' | 'supply';
}

const AGENT_META: AgentMeta[] = [
  {
    type: 'daily_report',
    label: '日报推送',
    desc: '每日自动生成营收、客流、食材成本摘要，推送至企业微信',
    icon: '📊',
    category: 'ops',
  },
  {
    type: 'inventory_alert',
    label: '库存预警',
    desc: '临期/低库存食材自动告警，防止备货断货与过期损耗',
    icon: '🔔',
    category: 'supply',
  },
  {
    type: 'reconciliation',
    label: '对账核查',
    desc: '每日自动比对 POS 收入与库存消耗，检测异常差异',
    icon: '🔍',
    category: 'finance',
  },
  {
    type: 'member_lifecycle',
    label: '会员生命周期',
    desc: 'RFM 分层分析，流失预警 + 生日关怀自动推送',
    icon: '👥',
    category: 'member',
  },
  {
    type: 'revenue_anomaly',
    label: '营收异常监测',
    desc: '实时监控营业额偏差，超过阈值立即告警',
    icon: '⚡',
    category: 'finance',
  },
  {
    type: 'prep_suggestion',
    label: '智能备料建议',
    desc: '基于历史数据预测备料量，自动生成备料建议单',
    icon: '🥡',
    category: 'supply',
  },
];

const AGENT_META_MAP = Object.fromEntries(AGENT_META.map(m => [m.type, m]));

const CATEGORY_LABEL: Record<string, string> = {
  ops: '运营', member: '会员', finance: '财务', supply: '供应链',
};
const CATEGORY_BADGE: Record<string, 'info' | 'success' | 'warning' | 'default'> = {
  ops: 'info', member: 'success', finance: 'warning', supply: 'default',
};

// ── 类型 ──────────────────────────────────────────────────────────────────────

interface AgentConfig {
  id: string;
  brand_id: string;
  agent_type: string;
  is_enabled: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface BrandOption {
  brand_id: string;
  name: string;
}

// ── 配置字段渲染器 ─────────────────────────────────────────────────────────────

function ConfigEditor({
  agentType,
  config,
  onChange,
}: {
  agentType: string;
  config: Record<string, unknown>;
  onChange: (key: string, val: unknown) => void;
}) {
  const renderField = (key: string, val: unknown) => {
    if (typeof val === 'boolean') {
      return (
        <div key={key} className={styles.configRow}>
          <label className={styles.configLabel}>{key}</label>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={val}
              onChange={e => onChange(key, e.target.checked)}
            />
            <span className={styles.toggleTrack} />
          </label>
        </div>
      );
    }
    if (typeof val === 'number') {
      return (
        <div key={key} className={styles.configRow}>
          <label className={styles.configLabel}>{key}</label>
          <input
            className={styles.configInput}
            type="number"
            value={val}
            onChange={e => onChange(key, Number(e.target.value))}
          />
        </div>
      );
    }
    if (Array.isArray(val)) {
      return (
        <div key={key} className={styles.configRow}>
          <label className={styles.configLabel}>{key}</label>
          <input
            className={styles.configInput}
            type="text"
            value={val.join(', ')}
            onChange={e =>
              onChange(key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))
            }
            placeholder="逗号分隔"
          />
        </div>
      );
    }
    // string / time
    return (
      <div key={key} className={styles.configRow}>
        <label className={styles.configLabel}>{key}</label>
        <input
          className={styles.configInput}
          type="text"
          value={String(val)}
          onChange={e => onChange(key, e.target.value)}
        />
      </div>
    );
  };

  return (
    <div className={styles.configEditor}>
      {Object.entries(config).map(([k, v]) => renderField(k, v))}
      {Object.keys(config).length === 0 && (
        <p className={styles.noConfig}>该 Agent 无可配置参数</p>
      )}
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

export default function PlatformAgentsPage() {
  const [brands, setBrands] = useState<BrandOption[]>([]);
  const [selectedBrand, setSelectedBrand] = useState<string>('');
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [loadingBrands, setLoadingBrands] = useState(true);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  // Drawer 状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
  const [editConfig, setEditConfig] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  // 初始化预警
  const [initializing, setInitializing] = useState(false);

  // ── 加载品牌列表 ──
  useEffect(() => {
    (async () => {
      setLoadingBrands(true);
      try {
        const res = await apiClient.get('/api/v1/merchants?page=1&page_size=50');
        const list: any[] = res?.merchants ?? res?.items ?? (Array.isArray(res) ? res : []);
        setBrands(list.map((m: any) => ({ brand_id: m.brand_id ?? m.id, name: m.name })));
        if (list.length > 0) setSelectedBrand(list[0].brand_id ?? list[0].id);
      } catch {
        setBrands([]);
      } finally {
        setLoadingBrands(false);
      }
    })();
  }, []);

  // ── 加载 Agent 配置 ──
  const loadAgents = useCallback(async (brandId: string) => {
    if (!brandId) return;
    setLoadingAgents(true);
    try {
      const res = await apiClient.get(`/api/v1/agent-configs/${brandId}`);
      setAgents(Array.isArray(res) ? res : (res?.agents ?? res?.items ?? []));
    } catch {
      setAgents([]);
    } finally {
      setLoadingAgents(false);
    }
  }, []);

  useEffect(() => {
    if (selectedBrand) loadAgents(selectedBrand);
  }, [selectedBrand, loadAgents]);

  // ── 启停 ──
  const handleToggle = async (agent: AgentConfig) => {
    setTogglingId(agent.id);
    try {
      await apiClient.post(`/api/v1/agent-configs/${selectedBrand}/${agent.agent_type}/toggle`);
      loadAgents(selectedBrand);
    } catch { /* silent */ } finally {
      setTogglingId(null);
    }
  };

  // ── 初始化默认配置 ──
  const handleInit = async () => {
    if (!selectedBrand) return;
    setInitializing(true);
    try {
      await apiClient.post(`/api/v1/agent-configs/${selectedBrand}/init`);
      loadAgents(selectedBrand);
    } catch { /* silent */ } finally {
      setInitializing(false);
    }
  };

  // ── 打开编辑 Drawer ──
  const openEdit = (agent: AgentConfig) => {
    setEditingAgent(agent);
    setEditConfig({ ...agent.config });
    setSaveError(null);
    setSaveOk(false);
    setDrawerOpen(true);
  };

  const handleConfigChange = (key: string, val: unknown) => {
    setEditConfig(prev => ({ ...prev, [key]: val }));
  };

  // ── 保存配置 ──
  const handleSave = async () => {
    if (!editingAgent) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await apiClient.put(
        `/api/v1/agent-configs/${selectedBrand}/${editingAgent.agent_type}`,
        { config: editConfig },
      );
      setSaveOk(true);
      loadAgents(selectedBrand);
      setTimeout(() => setDrawerOpen(false), 800);
    } catch (err: any) {
      setSaveError(err?.message ?? '保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  // ── 统计 ──
  const enabledCount = agents.filter(a => a.is_enabled).length;
  const totalCount = agents.length;

  const brandName = brands.find(b => b.brand_id === selectedBrand)?.name ?? selectedBrand;

  return (
    <div className={styles.page}>
      {/* 页头 */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>Agent 配置与监控</h1>
          <p className={styles.pageSubtitle}>
            按品牌启停 / 调参各 AI Agent，控制自动化推送节奏
          </p>
        </div>
      </div>

      {/* 品牌选择栏 */}
      <div className={styles.brandBar}>
        <span className={styles.brandBarLabel}>选择品牌：</span>
        {loadingBrands ? (
          <ZSkeleton width={200} height={32} />
        ) : brands.length === 0 ? (
          <span className={styles.noData}>暂无商户数据</span>
        ) : (
          <div className={styles.brandTabs}>
            {brands.map(b => (
              <button
                key={b.brand_id}
                className={`${styles.brandTab} ${selectedBrand === b.brand_id ? styles.brandTabActive : ''}`}
                onClick={() => setSelectedBrand(b.brand_id)}
              >
                {b.name}
              </button>
            ))}
          </div>
        )}

        {selectedBrand && (
          <div className={styles.brandActions}>
            {totalCount === 0 && !loadingAgents && (
              <ZButton size="sm" variant="outline" onClick={handleInit}>
                {initializing ? '初始化中…' : '初始化默认配置'}
              </ZButton>
            )}
            {totalCount > 0 && (
              <span className={styles.summaryTag}>
                已启用 {enabledCount} / {totalCount} 个 Agent
              </span>
            )}
          </div>
        )}
      </div>

      {/* Agent 网格 */}
      {loadingAgents ? (
        <div className={styles.skeletonGrid}>
          {[...Array(6)].map((_, i) => (
            <ZSkeleton key={i} height={160} borderRadius={12} />
          ))}
        </div>
      ) : agents.length === 0 ? (
        <ZCard>
          <ZEmpty
            text={selectedBrand ? `${brandName} 尚未初始化 Agent 配置，点击"初始化默认配置"开始` : '请先选择一个品牌'}
          />
        </ZCard>
      ) : (
        <div className={styles.agentGrid}>
          {agents.map(agent => {
            const meta = AGENT_META_MAP[agent.agent_type];
            const isToggling = togglingId === agent.id;
            return (
              <ZCard key={agent.id} className={`${styles.agentCard} ${agent.is_enabled ? styles.agentCardEnabled : styles.agentCardDisabled}`}>
                {/* 卡头 */}
                <div className={styles.agentCardHeader}>
                  <div className={styles.agentIconLabel}>
                    <span className={styles.agentIcon}>{meta?.icon ?? '🤖'}</span>
                    <div>
                      <div className={styles.agentName}>{meta?.label ?? agent.agent_type}</div>
                      {meta && (
                        <ZBadge
                          type={CATEGORY_BADGE[meta.category]}
                          text={CATEGORY_LABEL[meta.category]}
                        />
                      )}
                    </div>
                  </div>
                  <div className={`${styles.statusDot} ${agent.is_enabled ? styles.statusDotOn : styles.statusDotOff}`} />
                </div>

                {/* 描述 */}
                <p className={styles.agentDesc}>{meta?.desc ?? '—'}</p>

                {/* 参数摘要 */}
                {Object.keys(agent.config).length > 0 && (
                  <div className={styles.configSummary}>
                    {Object.entries(agent.config).slice(0, 2).map(([k, v]) => (
                      <span key={k} className={styles.configChip}>
                        {k}: <strong>{Array.isArray(v) ? v.join(',') : String(v)}</strong>
                      </span>
                    ))}
                  </div>
                )}

                {/* 操作 */}
                <div className={styles.agentActions}>
                  <ZButton
                    size="sm"
                    variant={agent.is_enabled ? 'ghost' : 'primary'}
                    onClick={() => handleToggle(agent)}
                  >
                    {isToggling ? '处理中…' : agent.is_enabled ? '停用' : '启用'}
                  </ZButton>
                  <ZButton size="sm" variant="ghost" onClick={() => openEdit(agent)}>
                    配置参数
                  </ZButton>
                </div>
              </ZCard>
            );
          })}
        </div>
      )}

      {/* 编辑参数 Drawer */}
      <ZDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={`配置参数 — ${AGENT_META_MAP[editingAgent?.agent_type ?? '']?.label ?? editingAgent?.agent_type ?? ''}`}
        width={440}
        footer={
          <div className={styles.drawerFooter}>
            <ZButton variant="ghost" onClick={() => setDrawerOpen(false)}>取消</ZButton>
            <ZButton variant="primary" onClick={handleSave}>
              {saving ? '保存中…' : '保存'}
            </ZButton>
          </div>
        }
      >
        <div className={styles.drawerBody}>
          {saveOk && (
            <div className={styles.alertRow}>
              <ZAlert variant="success" title="配置已保存" />
            </div>
          )}
          {saveError && (
            <div className={styles.alertRow}>
              <ZAlert variant="error" title={saveError} />
            </div>
          )}

          {editingAgent && (
            <>
              <div className={styles.drawerAgentInfo}>
                <span className={styles.drawerAgentIcon}>
                  {AGENT_META_MAP[editingAgent.agent_type]?.icon ?? '🤖'}
                </span>
                <div>
                  <div className={styles.drawerAgentName}>
                    {AGENT_META_MAP[editingAgent.agent_type]?.label ?? editingAgent.agent_type}
                  </div>
                  <div className={styles.drawerAgentDesc}>
                    {AGENT_META_MAP[editingAgent.agent_type]?.desc}
                  </div>
                </div>
              </div>

              <div className={styles.sectionDivider}>运行参数</div>
              <ConfigEditor
                agentType={editingAgent.agent_type}
                config={editConfig}
                onChange={handleConfigChange}
              />
            </>
          )}
        </div>
      </ZDrawer>
    </div>
  );
}
