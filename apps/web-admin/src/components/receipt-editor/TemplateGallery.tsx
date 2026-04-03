/**
 * TemplateGallery — 预置模板库弹窗
 * 5种风格供选择，支持微型预览缩略图
 */
import { useState, useEffect, useCallback } from 'react';
import { receiptTemplateApi } from '../../api/receiptTemplateApi';
import type { TemplateConfig } from '../../api/receiptTemplateApi';

interface TemplateGalleryProps {
  open: boolean;
  onClose: () => void;
  onSelect: (config: TemplateConfig) => void;
}

// ─── 本地风格元数据 ───

interface PresetMeta {
  color: string;
  icon: string;
  desc: string;
  name: string;
}

const PRESET_META: Record<string, PresetMeta> = {
  minimal:  { color: '#F8F8F8', icon: '◦', desc: '留白简约，专注内容', name: '极简' },
  classic:  { color: '#FFF8E7', icon: '龙', desc: '盒型边框，中式美学', name: '经典' },
  business: { color: '#1A1A2E', icon: '▓', desc: '反色标题，商务专业', name: '商务' },
  warm:     { color: '#FFF4E6', icon: '★', desc: '星形装饰，温馨亲切', name: '温馨' },
  premium:  { color: '#0D0D0D', icon: '✦', desc: '多层次设计，高端定位', name: '高端' },
};

const PRESET_ORDER = ['minimal', 'classic', 'business', 'warm', 'premium'];

// ─── 微型预览缩略图 ───

function MiniPreview({ style }: { style: string }) {
  const isDark = style === 'business' || style === 'premium';

  return (
    <div style={{
      width: 80,
      height: 120,
      background: isDark ? '#1a1a2e' : '#fff',
      border: '1px solid #ddd',
      padding: 4,
      fontSize: 4,
      fontFamily: 'monospace',
      display: 'flex',
      flexDirection: 'column',
      gap: 1,
      overflow: 'hidden',
      borderRadius: 2,
      flexShrink: 0,
    }}>
      {isDark ? (
        <>
          <div style={{ background: '#000', color: '#fff', textAlign: 'center', padding: '1px 0', fontSize: 5 }}>STORE</div>
          <div style={{ borderBottom: '1px solid #333', margin: '1px 0' }} />
          <div style={{ color: '#ccc' }}>菜品A × 1  ¥28</div>
          <div style={{ color: '#ccc' }}>菜品B × 2  ¥56</div>
          <div style={{ borderBottom: '1px solid #333', margin: '1px 0' }} />
          <div style={{ fontWeight: 'bold', color: '#fff' }}>合计: ¥84</div>
          {style === 'premium' && (
            <div style={{ textAlign: 'center', color: '#888', fontSize: 3 }}>✦──────✦</div>
          )}
        </>
      ) : style === 'classic' ? (
        <>
          <div style={{ border: '1px solid #333', textAlign: 'center', padding: '1px', fontSize: 5 }}>STORE</div>
          <div style={{ textAlign: 'center' }}>✦────✦</div>
          <div>菜品A × 1  ¥28</div>
          <div>菜品B × 2  ¥56</div>
          <div style={{ textAlign: 'center' }}>✦────✦</div>
          <div style={{ fontWeight: 'bold' }}>合计: ¥84</div>
        </>
      ) : style === 'warm' ? (
        <>
          <div style={{ textAlign: 'center' }}>★★★★★★</div>
          <div style={{ textAlign: 'center', fontWeight: 'bold', fontSize: 6 }}>STORE</div>
          <div style={{ textAlign: 'center' }}>★★★★★★</div>
          <div>菜品A × 1  ¥28</div>
          <div>菜品B × 2  ¥56</div>
          <div style={{ fontWeight: 'bold' }}>合计: ¥84</div>
        </>
      ) : (
        // minimal
        <>
          <div style={{ textAlign: 'center', fontWeight: 'bold', fontSize: 6 }}>STORE</div>
          <div style={{ borderBottom: '1px dotted #ccc', margin: '1px 0' }} />
          <div>菜品A × 1  ¥28</div>
          <div>菜品B × 2  ¥56</div>
          <div style={{ borderBottom: '1px dotted #ccc', margin: '1px 0' }} />
          <div style={{ fontWeight: 'bold' }}>合计: ¥84</div>
        </>
      )}
    </div>
  );
}

// ─── 主组件 ───

export function TemplateGallery({ open, onClose, onSelect }: TemplateGalleryProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [presets, setPresets] = useState<Array<{
    key: string;
    name: string;
    description: string;
    thumbnail_style: string;
    config: TemplateConfig;
  }> | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // ESC 键关闭
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKeyDown);
      // 打开时加载预置模板
      if (!presets) {
        loadPresets();
      }
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, handleKeyDown, presets]);

  const loadPresets = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await receiptTemplateApi.getPresets();
      setPresets(data);
    } catch {
      setError('预置模板加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (key: string) => {
    if (!presets) return;
    const preset = presets.find((p) => p.key === key);
    if (!preset) return;
    setSelectedKey(key);
    setApplying(true);
    // 稍微延迟一下，给视觉反馈
    await new Promise((r) => setTimeout(r, 150));
    onSelect(preset.config);
    setApplying(false);
  };

  if (!open) return null;

  // 按预设顺序排列，未从API获取的用本地元数据兜底
  const displayOrder = presets
    ? PRESET_ORDER.map((k) => {
        const fromApi = presets.find((p) => p.key === k);
        const meta = PRESET_META[k] ?? { color: '#fff', icon: '◦', desc: '', name: k };
        return fromApi
          ? { key: k, name: fromApi.name || meta.name, desc: fromApi.description || meta.desc, meta, config: fromApi.config }
          : null;
      }).filter(Boolean)
    : PRESET_ORDER.map((k) => ({
        key: k,
        name: PRESET_META[k]?.name ?? k,
        desc: PRESET_META[k]?.desc ?? '',
        meta: PRESET_META[k] ?? { color: '#fff', icon: '◦', desc: '', name: k },
        config: null,
      }));

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.6)',
          zIndex: 1000,
          backdropFilter: 'blur(2px)',
        }}
      />

      {/* 弹窗 */}
      <div style={{
        position: 'fixed',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 1001,
        background: 'var(--bg-1, #112228)',
        border: '1px solid var(--bg-2, #1a2a33)',
        borderRadius: 10,
        padding: 24,
        width: 560,
        maxWidth: 'calc(100vw - 32px)',
        maxHeight: 'calc(100vh - 64px)',
        overflow: 'auto',
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
      }}>
        {/* 标题栏 */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 20,
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-1, #fff)' }}>
              🎨 选择模板风格
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-4, #666)', marginTop: 4 }}>
              选择一种风格快速开始，可继续自定义编辑
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              border: 'none',
              background: 'var(--bg-2, #1a2a33)',
              color: 'var(--text-3, #999)',
              fontSize: 14,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* 内容区 */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-4, #666)', fontSize: 13 }}>
            正在加载模板...
          </div>
        ) : error ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div style={{ color: '#c66', fontSize: 13, marginBottom: 12 }}>{error}</div>
            <button
              onClick={loadPresets}
              style={{
                padding: '6px 16px',
                borderRadius: 5,
                border: '1px solid var(--bg-2, #1a2a33)',
                background: 'var(--bg-2, #1a2a33)',
                color: 'var(--text-2, #ccc)',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              重试
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            {displayOrder.map((item) => {
              if (!item) return null;
              const { key, name, desc, meta } = item;
              const isHovered = hoveredKey === key;
              const isSelected = selectedKey === key;
              const isDark = key === 'business' || key === 'premium';

              return (
                <div
                  key={key}
                  onClick={() => !applying && handleSelect(key)}
                  onMouseEnter={() => setHoveredKey(key)}
                  onMouseLeave={() => setHoveredKey(null)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 10,
                    padding: 12,
                    borderRadius: 8,
                    border: '2px solid',
                    borderColor: isSelected
                      ? 'var(--brand, #FF6B35)'
                      : isHovered
                      ? 'rgba(255,107,53,0.4)'
                      : 'var(--bg-2, #1a2a33)',
                    background: isSelected
                      ? 'rgba(255,107,53,0.08)'
                      : isHovered
                      ? 'var(--bg-2, #1a2a33)'
                      : 'transparent',
                    cursor: applying ? 'wait' : 'pointer',
                    transition: 'all 0.15s',
                    width: 'calc(50% - 6px)',
                    boxSizing: 'border-box',
                    userSelect: 'none',
                  }}
                >
                  <MiniPreview style={key} />

                  <div style={{ textAlign: 'center', width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, marginBottom: 3 }}>
                      <span style={{
                        fontSize: 14,
                        background: isDark ? '#1a1a2e' : meta.color,
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: 4,
                        padding: '1px 5px',
                      }}>
                        {meta.icon}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-1, #fff)' }}>
                        {name}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-4, #666)', lineHeight: 1.5 }}>
                      {desc}
                    </div>
                  </div>

                  {isSelected && applying && (
                    <div style={{ fontSize: 11, color: 'var(--brand, #FF6B35)' }}>应用中...</div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 底部提示 */}
        <div style={{
          marginTop: 16,
          paddingTop: 14,
          borderTop: '1px solid var(--bg-2, #1a2a33)',
          fontSize: 11,
          color: 'var(--text-4, #666)',
          textAlign: 'center',
        }}>
          选择模板后将替换当前编辑内容 · 按 ESC 取消
        </div>
      </div>
    </>
  );
}
