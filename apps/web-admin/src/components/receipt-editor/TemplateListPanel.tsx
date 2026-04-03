/**
 * TemplateListPanel — 模板管理侧边栏（可折叠）
 * 列出当前门店的所有模板，支持新建、复制、删除、设为默认
 */
import { useState, useEffect } from 'react';
import type { ReactNode, MouseEvent } from 'react';
import { receiptTemplateApi } from '../../api/receiptTemplateApi';
import type { ReceiptTemplate } from '../../api/receiptTemplateApi';

interface TemplateListPanelProps {
  storeId: string;
  currentTemplateId: string | null;
  onSelect: (template: ReceiptTemplate) => void;
  onNew: () => void;
  refreshKey?: number; // 外部触发刷新
}

export function TemplateListPanel({
  storeId,
  currentTemplateId,
  onSelect,
  onNew,
  refreshKey,
}: TemplateListPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [templates, setTemplates] = useState<ReceiptTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载模板列表
  const loadTemplates = async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await receiptTemplateApi.list(storeId, 'receipt');
      setTemplates(res.items);
    } catch (e) {
      setError('加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTemplates();
  }, [storeId, refreshKey]);

  const handleSetDefault = async (e: MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await receiptTemplateApi.setDefault(id);
      await loadTemplates();
    } catch {
      alert('设置默认失败');
    }
  };

  const handleDuplicate = async (e: MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await receiptTemplateApi.duplicate(id);
      await loadTemplates();
    } catch {
      alert('复制失败');
    }
  };

  const handleDelete = async (e: MouseEvent, id: string, name: string) => {
    e.stopPropagation();
    if (!confirm(`确定删除模板「${name}」吗？此操作不可撤销。`)) return;
    try {
      await receiptTemplateApi.delete(id);
      await loadTemplates();
    } catch {
      alert('删除失败');
    }
  };

  // 折叠态：只显示一个竖向切换条
  if (collapsed) {
    return (
      <div
        onClick={() => setCollapsed(false)}
        title="展开模板列表"
        style={{
          width: 24,
          background: 'var(--bg-1, #112228)',
          borderLeft: '1px solid var(--bg-2, #1a2a33)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          flexShrink: 0,
          writingMode: 'vertical-rl',
          fontSize: 11,
          color: 'var(--text-4, #666)',
          letterSpacing: 2,
          userSelect: 'none',
        }}
      >
        模板列表 ›
      </div>
    );
  }

  return (
    <div style={{
      width: 200,
      background: 'var(--bg-1, #112228)',
      borderLeft: '1px solid var(--bg-2, #1a2a33)',
      display: 'flex',
      flexDirection: 'column',
      flexShrink: 0,
      overflow: 'hidden',
    }}>
      {/* 面板标题栏 */}
      <div style={{
        padding: '10px 12px 8px',
        borderBottom: '1px solid var(--bg-2, #1a2a33)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: 'var(--text-3, #999)',
        }}>
          模板列表
        </span>
        <div style={{ display: 'flex', gap: 4 }}>
          <IconBtn title="新建模板" onClick={onNew}>＋</IconBtn>
          <IconBtn title="收起面板" onClick={() => setCollapsed(true)}>‹</IconBtn>
        </div>
      </div>

      {/* 模板列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '6px 8px' }}>
        {loading && (
          <div style={{ fontSize: 12, color: 'var(--text-4, #666)', textAlign: 'center', padding: 16 }}>
            加载中...
          </div>
        )}
        {error && (
          <div style={{
            fontSize: 12, color: '#c00', textAlign: 'center', padding: 8,
            cursor: 'pointer', textDecoration: 'underline',
          }} onClick={loadTemplates}>
            {error}，点击重试
          </div>
        )}
        {!loading && !error && templates.length === 0 && (
          <div style={{
            fontSize: 12,
            color: 'var(--text-4, #666)',
            textAlign: 'center',
            padding: 16,
            lineHeight: 1.6,
          }}>
            暂无模板<br />
            <span
              style={{ color: 'var(--brand, #FF6B35)', cursor: 'pointer' }}
              onClick={onNew}
            >
              点击新建
            </span>
          </div>
        )}
        {templates.map((tpl) => (
          <TemplateCard
            key={tpl.id}
            template={tpl}
            isActive={currentTemplateId === tpl.id}
            onSelect={() => onSelect(tpl)}
            onSetDefault={(e) => handleSetDefault(e, tpl.id)}
            onDuplicate={(e) => handleDuplicate(e, tpl.id)}
            onDelete={(e) => handleDelete(e, tpl.id, tpl.name)}
          />
        ))}
      </div>
    </div>
  );
}

// ─── 单个模板卡片 ───

interface TemplateCardProps {
  template: ReceiptTemplate;
  isActive: boolean;
  onSelect: () => void;
  onSetDefault: (e: MouseEvent) => void;
  onDuplicate: (e: MouseEvent) => void;
  onDelete: (e: MouseEvent) => void;
}

function TemplateCard({
  template,
  isActive,
  onSelect,
  onSetDefault,
  onDuplicate,
  onDelete,
}: TemplateCardProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: '8px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        marginBottom: 4,
        background: isActive
          ? 'rgba(255,107,53,0.12)'
          : hovered
          ? 'var(--bg-2, #1a2a33)'
          : 'transparent',
        border: `1px solid ${isActive ? 'rgba(255,107,53,0.4)' : 'transparent'}`,
        transition: 'all 0.15s',
      }}
    >
      {/* 模板名称 + 默认标识 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
        <span
          style={{
            fontSize: 10,
            color: template.is_default ? '#FFD700' : 'var(--text-4, #666)',
            cursor: template.is_default ? 'default' : 'pointer',
          }}
          onClick={template.is_default ? undefined : onSetDefault}
          title={template.is_default ? '当前默认模板' : '设为默认'}
        >
          {template.is_default ? '★' : '☆'}
        </span>
        <span style={{
          flex: 1,
          fontSize: 12,
          fontWeight: isActive ? 600 : 400,
          color: isActive ? 'var(--brand, #FF6B35)' : 'var(--text-2, #ccc)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {template.name}
        </span>
      </div>

      {/* 纸宽信息 */}
      <div style={{ fontSize: 10, color: 'var(--text-4, #666)', marginBottom: 4 }}>
        {template.config.paper_width}mm · {template.config.elements.length} 个元素
      </div>

      {/* 操作按钮（悬停显示） */}
      {(hovered || isActive) && (
        <div
          style={{ display: 'flex', gap: 4 }}
          onClick={(e) => e.stopPropagation()}
        >
          <SmallBtn onClick={onSetDefault} title="设为默认" disabled={template.is_default}>
            默认
          </SmallBtn>
          <SmallBtn onClick={onDuplicate} title="复制模板">
            复制
          </SmallBtn>
          <SmallBtn onClick={onDelete} title="删除模板" danger>
            删除
          </SmallBtn>
        </div>
      )}
    </div>
  );
}

// ─── 工具按钮 ───

function IconBtn({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: ReactNode;
}) {
  const [hov, setHov] = useState(false);
  return (
    <button
      title={title}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        width: 22,
        height: 22,
        border: 'none',
        borderRadius: 4,
        background: hov ? 'var(--bg-2, #1a2a33)' : 'transparent',
        color: 'var(--text-3, #999)',
        fontSize: 14,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 0,
        transition: 'background 0.15s',
      }}
    >
      {children}
    </button>
  );
}

function SmallBtn({
  title,
  onClick,
  disabled,
  danger,
  children,
}: {
  title: string;
  onClick: (e: MouseEvent) => void;
  disabled?: boolean;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      style={{
        flex: 1,
        padding: '2px 0',
        borderRadius: 3,
        border: '1px solid var(--bg-2, #1a2a33)',
        background: 'var(--bg-0, #0B1A20)',
        color: disabled
          ? 'var(--text-4, #666)'
          : danger
          ? '#c66'
          : 'var(--text-3, #999)',
        fontSize: 10,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  );
}
