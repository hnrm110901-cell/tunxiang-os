/**
 * KDSRuleConfigPanel — KDS多维标识与颜色规则配置面板
 *
 * 供门店管理员配置KDS超时预警、渠道标识色、标识开关等规则。
 * 保存后通过 /api/v1/kds-rules/{storeId} 持久化，看板实时生效。
 *
 * 使用方式（嵌入 KDSConfigPage 或弹层）：
 *   <KDSRuleConfigPanel storeId="store-123" onSaved={() => {}} />
 */
import React, { useState } from 'react';
import {
  saveKDSRules,
  DEFAULT_KDS_RULES,
  type KDSRuleConfig,
} from '../api/kdsRulesApi';
import { useKDSRules } from '../hooks/useKDSRules';

// ─── 简单颜色选择器（色块 + 文本输入） ───

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-3 py-2">
      <label className="text-sm text-gray-300 w-28 flex-shrink-0">{label}</label>
      <input
        type="color"
        value={value}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        className="w-10 h-8 cursor-pointer rounded border border-gray-600 bg-transparent"
        style={{ padding: 2 }}
      />
      <input
        type="text"
        value={value}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        className="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-1 text-sm text-white font-mono"
        placeholder="#RRGGBB"
        maxLength={20}
      />
    </div>
  );
}

// ─── 数字输入框 ───

function NumberField({
  label,
  value,
  min,
  max,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  unit?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center gap-3 py-2">
      <label className="text-sm text-gray-300 w-28 flex-shrink-0">{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
          const v = parseInt(e.target.value, 10);
          if (!isNaN(v)) onChange(v);
        }}
        className="w-20 bg-gray-800 border border-gray-600 rounded px-3 py-1 text-sm text-white text-center"
      />
      {unit && <span className="text-sm text-gray-400">{unit}</span>}
    </div>
  );
}

// ─── Toggle 开关 ───

function ToggleField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-gray-300">{label}</span>
      <button
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          value ? 'bg-orange-500' : 'bg-gray-600'
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            value ? 'translate-x-6' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  );
}

// ─── 主组件 ───

interface KDSRuleConfigPanelProps {
  storeId: string;
  onSaved?: (config: KDSRuleConfig) => void;
}

export function KDSRuleConfigPanel({ storeId, onSaved }: KDSRuleConfigPanelProps) {
  const { rules: initialRules, loading: rulesLoading } = useKDSRules(storeId);
  const [config, setConfig] = useState<KDSRuleConfig>(() => DEFAULT_KDS_RULES);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 当规则加载完成后，同步到本地 state
  // （用 key 强制重建更简单，这里手动合并以保持局部编辑）
  const [synced, setSynced] = useState(false);
  if (!rulesLoading && !synced) {
    setConfig(initialRules);
    setSynced(true);
  }

  function update<K extends keyof KDSRuleConfig>(key: K, value: KDSRuleConfig[K]) {
    setConfig((prev: KDSRuleConfig) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  function updateChannelColor(channel: string, color: string) {
    setConfig((prev: KDSRuleConfig) => ({
      ...prev,
      channel_colors: { ...prev.channel_colors, [channel]: color },
    }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const saved = await saveKDSRules(storeId, config);
      setConfig(saved);
      setSaved(true);
      onSaved?.(saved);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '保存失败，请重试');
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    setConfig(DEFAULT_KDS_RULES);
    setSaved(false);
  }

  return (
    <div
      style={{
        background: '#111827',
        color: '#F0F0F0',
        borderRadius: 16,
        padding: 24,
        maxWidth: 480,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
      }}
    >
      <div style={{ fontSize: 20, fontWeight: 700, color: '#FF6B35', marginBottom: 20 }}>
        KDS 标识规则配置
      </div>

      {/* 超时预警 */}
      <section style={{ marginBottom: 20 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.5)',
          marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1,
        }}>
          超时预警
        </div>
        <div style={{ background: '#1F2937', borderRadius: 12, padding: '8px 16px' }}>
          <NumberField
            label="预警时长"
            value={config.warn_minutes}
            min={1}
            max={config.urgent_minutes - 1}
            unit="分钟"
            onChange={(v) => update('warn_minutes', v)}
          />
          <ColorField
            label="预警颜色"
            value={config.warn_color}
            onChange={(v) => update('warn_color', v)}
          />
          <NumberField
            label="催单阈值"
            value={config.urgent_minutes}
            min={config.warn_minutes + 1}
            max={120}
            unit="分钟"
            onChange={(v) => update('urgent_minutes', v)}
          />
          <ColorField
            label="催单颜色"
            value={config.urgent_color}
            onChange={(v) => update('urgent_color', v)}
          />
        </div>
      </section>

      {/* 渠道标识色 */}
      <section style={{ marginBottom: 20 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.5)',
          marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1,
        }}>
          渠道标识色
        </div>
        <div style={{ background: '#1F2937', borderRadius: 12, padding: '8px 16px' }}>
          <ColorField
            label="堂食"
            value={config.channel_colors.dine_in ?? '#4CAF50'}
            onChange={(v) => updateChannelColor('dine_in', v)}
          />
          <ColorField
            label="外卖"
            value={config.channel_colors.takeout ?? '#2196F3'}
            onChange={(v) => updateChannelColor('takeout', v)}
          />
          <ColorField
            label="自取"
            value={config.channel_colors.pickup ?? '#9C27B0'}
            onChange={(v) => updateChannelColor('pickup', v)}
          />
        </div>
      </section>

      {/* 特殊标识颜色 */}
      <section style={{ marginBottom: 20 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.5)',
          marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1,
        }}>
          特殊标识颜色
        </div>
        <div style={{ background: '#1F2937', borderRadius: 12, padding: '8px 16px' }}>
          <ColorField
            label="赠菜角标"
            value={config.gift_badge_color}
            onChange={(v) => update('gift_badge_color', v)}
          />
          <ColorField
            label="退菜角标"
            value={config.return_badge_color}
            onChange={(v) => update('return_badge_color', v)}
          />
        </div>
      </section>

      {/* 标识开关 */}
      <section style={{ marginBottom: 24 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.5)',
          marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1,
        }}>
          显示开关
        </div>
        <div style={{ background: '#1F2937', borderRadius: 12, padding: '8px 16px' }}>
          <ToggleField
            label="显示客位数"
            value={config.show_guest_seat}
            onChange={(v) => update('show_guest_seat', v)}
          />
          <ToggleField
            label="显示备注"
            value={config.show_remark}
            onChange={(v) => update('show_remark', v)}
          />
          <ToggleField
            label="显示做法"
            value={config.show_cooking_method}
            onChange={(v) => update('show_cooking_method', v)}
          />
          <ToggleField
            label="显示渠道标识"
            value={config.show_channel_badge}
            onChange={(v) => update('show_channel_badge', v)}
          />
        </div>
      </section>

      {/* 错误提示 */}
      {error && (
        <div style={{
          background: '#2D1515', border: '1px solid #A32D2D',
          borderRadius: 8, padding: '10px 14px',
          fontSize: 14, color: '#ff6b6b', marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      {/* 操作按钮 */}
      <div style={{ display: 'flex', gap: 12 }}>
        <button
          onClick={handleReset}
          style={{
            flex: 1, height: 48, borderRadius: 10,
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.1)',
            color: 'rgba(255,255,255,0.5)',
            fontSize: 16, cursor: 'pointer',
          }}
        >
          恢复默认
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            flex: 2, height: 48, borderRadius: 10,
            background: saved ? '#0F6E56' : saving ? '#555' : '#FF6B35',
            border: 'none',
            color: '#fff',
            fontSize: 16, fontWeight: 700,
            cursor: saving ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s',
          }}
        >
          {saved ? '已保存' : saving ? '保存中...' : '保存配置'}
        </button>
      </div>
    </div>
  );
}
