/**
 * ReceiptEditorPage — 小票模板可视化编辑器
 * 三栏布局：左侧元素面板 | 中间画布 | 右侧属性面板
 * 可选：右侧附加模板列表侧边栏
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { ElementPalette } from '../components/receipt-editor/ElementPalette';
import { ReceiptCanvas } from '../components/receipt-editor/ReceiptCanvas';
import { PropertyPanel } from '../components/receipt-editor/PropertyPanel';
import { TemplateListPanel } from '../components/receipt-editor/TemplateListPanel';
import { receiptTemplateApi } from '../api/receiptTemplateApi';
import type {
  TemplateElement,
  TemplateConfig,
  ReceiptTemplate,
  ElementType,
} from '../api/receiptTemplateApi';

// ─── 默认模板配置（新建时使用） ───

const DEFAULT_CONFIG: TemplateConfig = {
  paper_width: 80,
  elements: [
    { id: 'el-1', type: 'store_name', align: 'center', bold: true, size: 'double_both' },
    { id: 'el-2', type: 'separator', char: '=', align: 'center' },
    { id: 'el-3', type: 'order_info', fields: ['table_no', 'order_no', 'cashier', 'datetime'] },
    { id: 'el-4', type: 'separator', char: '-', align: 'center' },
    { id: 'el-5', type: 'order_items', show_price: true, show_qty: true, show_subtotal: true },
    { id: 'el-6', type: 'separator', char: '-', align: 'center' },
    { id: 'el-7', type: 'total_summary', show_discount: true, show_service_fee: false },
    { id: 'el-8', type: 'payment_method', align: 'left' },
    { id: 'el-9', type: 'separator', char: '=', align: 'center' },
    { id: 'el-10', type: 'custom_text', content: '感谢您的光临，欢迎再次惠顾！', align: 'center' },
    { id: 'el-11', type: 'blank_lines', count: 2 },
  ],
};

// 生成唯一ID
function genId(): string {
  return `el-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

// ─── 主页面 ───

export function ReceiptEditorPage() {
  const { templateId } = useParams<{ templateId?: string }>();

  // 从localStorage读取storeId（实际业务中应从门店上下文获取）
  const storeId = (() => {
    try {
      const u = JSON.parse(localStorage.getItem('tx_user') || '{}');
      return u.store_id || u.storeId || 'demo-store';
    } catch {
      return 'demo-store';
    }
  })();

  // ─── 状态 ───
  const [templateName, setTemplateName] = useState('新模板');
  const [currentTemplateId, setCurrentTemplateId] = useState<string | null>(templateId || null);
  const [paperWidth, setPaperWidth] = useState<58 | 80>(80);
  const [elements, setElements] = useState<TemplateElement[]>(DEFAULT_CONFIG.elements);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [listRefreshKey, setListRefreshKey] = useState(0);
  const [isDirty, setIsDirty] = useState(false);

  const saveMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── 初始加载指定模板 ───
  useEffect(() => {
    if (templateId) {
      loadTemplate(templateId);
    }
  }, [templateId]);

  const loadTemplate = async (id: string) => {
    try {
      const tpl = await receiptTemplateApi.get(id);
      applyTemplate(tpl);
    } catch {
      showMsg('模板加载失败', true);
    }
  };

  const applyTemplate = (tpl: ReceiptTemplate) => {
    setCurrentTemplateId(tpl.id);
    setTemplateName(tpl.name);
    setPaperWidth(tpl.config.paper_width);
    setElements(tpl.config.elements);
    setSelectedId(null);
    setIsDirty(false);
  };

  // ─── 显示操作消息 ───
  const showMsg = (msg: string, isError = false) => {
    setSaveMsg((isError ? '⚠ ' : '✓ ') + msg);
    if (saveMsgTimer.current) clearTimeout(saveMsgTimer.current);
    saveMsgTimer.current = setTimeout(() => setSaveMsg(null), 3000);
  };

  // ─── 添加元素 ───
  const handleAddElement = useCallback((type: ElementType, defaults: Partial<TemplateElement>) => {
    const newEl: TemplateElement = {
      id: genId(),
      type,
      ...defaults,
    };
    setElements((prev) => [...prev, newEl]);
    setSelectedId(newEl.id);
    setIsDirty(true);
  }, []);

  // ─── 属性更新 ───
  const handlePropChange = useCallback((id: string, updates: Partial<TemplateElement>) => {
    setElements((prev) =>
      prev.map((el) => (el.id === id ? { ...el, ...updates } : el)),
    );
    setIsDirty(true);
  }, []);

  // ─── 元素排序 ───
  const handleReorder = useCallback((fromIndex: number, toIndex: number) => {
    if (toIndex < 0 || toIndex >= elements.length) return;
    setElements((prev) => {
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
    setIsDirty(true);
  }, [elements.length]);

  // ─── 删除元素 ───
  const handleDelete = useCallback((id: string) => {
    setElements((prev) => prev.filter((el) => el.id !== id));
    setSelectedId((sel) => (sel === id ? null : sel));
    setIsDirty(true);
  }, []);

  // ─── 保存 ───
  const handleSave = async () => {
    setSaving(true);
    const config: TemplateConfig = { paper_width: paperWidth, elements };
    try {
      if (currentTemplateId) {
        await receiptTemplateApi.update(currentTemplateId, { name: templateName, config });
        showMsg('保存成功');
      } else {
        const created = await receiptTemplateApi.create({
          store_id: storeId,
          name: templateName,
          print_type: 'receipt',
          config,
        });
        setCurrentTemplateId(created.id);
        showMsg('创建成功');
        setListRefreshKey((k) => k + 1);
      }
      setIsDirty(false);
    } catch {
      showMsg('保存失败，请重试', true);
    } finally {
      setSaving(false);
    }
  };

  // ─── 另存为 ───
  const handleSaveAs = async () => {
    const newName = prompt('请输入新模板名称：', templateName + '（副本）');
    if (!newName) return;
    setSaving(true);
    const config: TemplateConfig = { paper_width: paperWidth, elements };
    try {
      const created = await receiptTemplateApi.create({
        store_id: storeId,
        name: newName,
        print_type: 'receipt',
        config,
      });
      setCurrentTemplateId(created.id);
      setTemplateName(newName);
      showMsg(`已另存为「${newName}」`);
      setIsDirty(false);
      setListRefreshKey((k) => k + 1);
    } catch {
      showMsg('另存为失败', true);
    } finally {
      setSaving(false);
    }
  };

  // ─── 预览 ───
  const handlePreview = async () => {
    setPreviewLoading(true);
    try {
      const res = await receiptTemplateApi.preview({ paper_width: paperWidth, elements });
      // 在新标签页打开预览
      const win = window.open('', '_blank');
      if (win) {
        win.document.write(res.html);
        win.document.close();
      } else {
        alert('请允许弹出窗口以查看预览');
      }
    } catch {
      showMsg('预览失败，请检查配置', true);
    } finally {
      setPreviewLoading(false);
    }
  };

  // ─── 新建 ───
  const handleNew = () => {
    if (isDirty && !confirm('当前有未保存的更改，确定新建吗？')) return;
    setCurrentTemplateId(null);
    setTemplateName('新模板');
    setPaperWidth(80);
    setElements(DEFAULT_CONFIG.elements);
    setSelectedId(null);
    setIsDirty(false);
  };

  // ─── 选中元素 ───
  const selectedElement = elements.find((el) => el.id === selectedId) || null;

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--bg-0, #0B1A20)',
      color: 'var(--text-1, #fff)',
      overflow: 'hidden',
    }}>
      {/* ── 顶部工具栏 ── */}
      <Toolbar
        templateName={templateName}
        onNameChange={(v) => { setTemplateName(v); setIsDirty(true); }}
        paperWidth={paperWidth}
        onPaperWidthChange={(w) => { setPaperWidth(w); setIsDirty(true); }}
        onSave={handleSave}
        onSaveAs={handleSaveAs}
        onPreview={handlePreview}
        onNew={handleNew}
        saving={saving}
        previewLoading={previewLoading}
        isDirty={isDirty}
        saveMsg={saveMsg}
        elementCount={elements.length}
      />

      {/* ── 主体三栏 ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧：元素面板 */}
        <div style={{ width: 200, flexShrink: 0, overflow: 'hidden' }}>
          <ElementPalette onAdd={handleAddElement} />
        </div>

        {/* 中间：画布区 */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'flex-start',
          padding: '32px 24px',
          background: 'var(--bg-0, #0B1A20)',
        }}>
          <div>
            {/* 纸宽提示 */}
            <div style={{
              textAlign: 'center',
              fontSize: 11,
              color: 'var(--text-4, #666)',
              marginBottom: 8,
              letterSpacing: 1,
            }}>
              {paperWidth}mm 热敏纸 · {paperWidth === 80 ? 320 : 232}px
            </div>
            <ReceiptCanvas
              elements={elements}
              paperWidth={paperWidth}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onReorder={handleReorder}
              onDelete={handleDelete}
            />
          </div>
        </div>

        {/* 右侧：属性面板 */}
        <div style={{ width: 240, flexShrink: 0, overflow: 'hidden', borderLeft: '1px solid var(--bg-2, #1a2a33)' }}>
          <PropertyPanel
            element={selectedElement}
            onChange={handlePropChange}
          />
        </div>

        {/* 最右：模板列表侧边栏 */}
        <TemplateListPanel
          storeId={storeId}
          currentTemplateId={currentTemplateId}
          onSelect={applyTemplate}
          onNew={handleNew}
          refreshKey={listRefreshKey}
        />
      </div>
    </div>
  );
}

// ─── 顶部工具栏组件 ───

interface ToolbarProps {
  templateName: string;
  onNameChange: (v: string) => void;
  paperWidth: 58 | 80;
  onPaperWidthChange: (w: 58 | 80) => void;
  onSave: () => void;
  onSaveAs: () => void;
  onPreview: () => void;
  onNew: () => void;
  saving: boolean;
  previewLoading: boolean;
  isDirty: boolean;
  saveMsg: string | null;
  elementCount: number;
}

function Toolbar({
  templateName,
  onNameChange,
  paperWidth,
  onPaperWidthChange,
  onSave,
  onSaveAs,
  onPreview,
  onNew,
  saving,
  previewLoading,
  isDirty,
  saveMsg,
  elementCount,
}: ToolbarProps) {
  return (
    <div style={{
      height: 48,
      background: 'var(--bg-1, #112228)',
      borderBottom: '1px solid var(--bg-2, #1a2a33)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 16px',
      gap: 10,
      flexShrink: 0,
    }}>
      {/* 页面图标 + 标题 */}
      <span style={{ fontSize: 16, marginRight: 4 }}>🧾</span>
      <span style={{ fontSize: 12, color: 'var(--text-3, #999)', marginRight: 4, whiteSpace: 'nowrap' }}>
        小票模板
      </span>
      <span style={{ color: 'var(--bg-2, #1a2a33)' }}>|</span>

      {/* 模板名称输入 */}
      <input
        value={templateName}
        onChange={(e) => onNameChange(e.target.value)}
        style={{
          background: 'var(--bg-2, #1a2a33)',
          border: '1px solid transparent',
          borderRadius: 5,
          padding: '4px 10px',
          color: 'var(--text-1, #fff)',
          fontSize: 13,
          fontWeight: 600,
          outline: 'none',
          width: 180,
          transition: 'border-color 0.15s',
        }}
        onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--brand, #FF6B35)')}
        onBlur={(e) => (e.currentTarget.style.borderColor = 'transparent')}
        placeholder="输入模板名称..."
      />

      {/* 未保存标记 */}
      {isDirty && (
        <span style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: '#FF6B35',
          flexShrink: 0,
        }} />
      )}

      {/* 分隔 */}
      <div style={{ flex: 1 }} />

      {/* 元素计数 */}
      <span style={{ fontSize: 11, color: 'var(--text-4, #666)', whiteSpace: 'nowrap' }}>
        {elementCount} 个元素
      </span>

      {/* 纸宽切换 */}
      <PaperWidthToggle value={paperWidth} onChange={onPaperWidthChange} />

      {/* 分隔 */}
      <span style={{ color: 'var(--bg-2, #1a2a33)' }}>|</span>

      {/* 操作按钮组 */}
      <ToolBtn onClick={onNew} title="新建空白模板">
        新建
      </ToolBtn>
      <ToolBtn onClick={onPreview} disabled={previewLoading} title="预览小票效果">
        {previewLoading ? '加载中...' : '预览'}
      </ToolBtn>
      <ToolBtn onClick={onSaveAs} disabled={saving} title="另存为新模板">
        另存为
      </ToolBtn>
      <ToolBtn
        onClick={onSave}
        disabled={saving}
        primary
        title="保存当前模板"
      >
        {saving ? '保存中...' : '保存'}
      </ToolBtn>

      {/* 保存提示 */}
      {saveMsg && (
        <span style={{
          fontSize: 12,
          color: saveMsg.startsWith('⚠') ? '#c66' : '#6a9',
          whiteSpace: 'nowrap',
          maxWidth: 160,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {saveMsg}
        </span>
      )}
    </div>
  );
}

// ─── 纸宽切换 ───

function PaperWidthToggle({
  value,
  onChange,
}: {
  value: 58 | 80;
  onChange: (v: 58 | 80) => void;
}) {
  return (
    <div style={{
      display: 'flex',
      background: 'var(--bg-2, #1a2a33)',
      borderRadius: 5,
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {([58, 80] as const).map((w) => (
        <button
          key={w}
          onClick={() => onChange(w)}
          style={{
            padding: '4px 10px',
            border: 'none',
            background: value === w ? 'var(--brand, #FF6B35)' : 'transparent',
            color: value === w ? '#fff' : 'var(--text-3, #999)',
            fontSize: 12,
            fontWeight: value === w ? 600 : 400,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {w}mm
        </button>
      ))}
    </div>
  );
}

// ─── 工具栏按钮 ───

function ToolBtn({
  onClick,
  disabled,
  primary,
  title,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  title?: string;
  children: ReactNode;
}) {
  const [hov, setHov] = useState(false);
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        padding: '5px 12px',
        borderRadius: 5,
        border: primary ? 'none' : '1px solid var(--bg-2, #1a2a33)',
        background: disabled
          ? 'var(--bg-2, #1a2a33)'
          : primary
          ? hov ? '#E55A28' : '#FF6B35'
          : hov
          ? 'var(--bg-2, #1a2a33)'
          : 'transparent',
        color: disabled ? 'var(--text-4, #666)' : primary ? '#fff' : 'var(--text-2, #ccc)',
        fontSize: 12,
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'all 0.15s',
        whiteSpace: 'nowrap',
        fontWeight: primary ? 600 : 400,
      }}
    >
      {children}
    </button>
  );
}
