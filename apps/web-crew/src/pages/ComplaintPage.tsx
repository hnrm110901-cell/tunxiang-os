/**
 * 客诉记录页面 — 选择客诉类型 + 描述 + 拍照 + 提交
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState } from 'react';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
  warning: '#BA7517',
};

/* ---------- 类型 ---------- */
type ComplaintType = 'dish' | 'service' | 'environment' | 'wait';

interface TypeOption {
  value: ComplaintType;
  label: string;
  desc: string;
}

const COMPLAINT_TYPES: TypeOption[] = [
  { value: 'dish', label: '菜品问题', desc: '口味异常、异物、分量不足等' },
  { value: 'service', label: '服务问题', desc: '服务态度、响应慢、操作失误等' },
  { value: 'environment', label: '环境问题', desc: '卫生、温度、噪音、设施等' },
  { value: 'wait', label: '等待时间', desc: '排队过久、上菜太慢、结账等待等' },
];

const QUICK_TAGS: Record<ComplaintType, string[]> = {
  dish: ['口味偏咸', '口味偏辣', '菜品有异物', '分量太少', '菜品不新鲜', '上错菜'],
  service: ['服务态度差', '响应太慢', '不主动服务', '操作失误'],
  environment: ['桌面不干净', '地面湿滑', '空调太冷', '空调太热', '噪音大'],
  wait: ['排队超30分钟', '上菜超30分钟', '催菜无响应', '结账等待过久'],
};

/* ---------- 组件 ---------- */
export function ComplaintPage() {
  const [selectedType, setSelectedType] = useState<ComplaintType | null>(null);
  const [description, setDescription] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [tableNo, setTableNo] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const toggleTag = (tag: string) => {
    setSelectedTags(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag],
    );
  };

  const handleSubmit = () => {
    if (!selectedType) return;
    setSubmitting(true);
    setTimeout(() => {
      setSubmitting(false);
      setSubmitted(true);
    }, 800);
  };

  const handleReset = () => {
    setSelectedType(null);
    setDescription('');
    setSelectedTags([]);
    setTableNo('');
    setSubmitted(false);
  };

  if (submitted) {
    return (
      <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
        <div style={{
          textAlign: 'center', padding: 40,
          background: C.card, borderRadius: 12,
          border: `1px solid ${C.border}`,
          marginTop: 40,
        }}>
          <div style={{
            width: 64, height: 64, borderRadius: 32,
            background: C.green, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            fontSize: 32, color: C.white, margin: '0 auto 16px',
          }}>
            {'\u2713'}
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginBottom: 8 }}>
            客诉已提交
          </div>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 24 }}>
            已进入异常处置工作流，店长将收到通知
          </div>
          <button
            onClick={handleReset}
            style={{
              minHeight: 48, padding: '10px 24px', borderRadius: 12,
              background: C.accent, color: C.white, border: 'none',
              fontSize: 16, fontWeight: 700, cursor: 'pointer',
            }}
          >
            继续记录
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        客诉记录
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        记录客户投诉，提交到异常处置工作流
      </p>

      {/* 桌号 */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
          桌号（可选）
        </label>
        <input
          type="text"
          value={tableNo}
          onChange={e => setTableNo(e.target.value)}
          placeholder="如 A01"
          style={{
            width: '100%', padding: 14, fontSize: 18,
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 12, color: C.white,
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* 客诉类型 */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
          客诉类型
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {COMPLAINT_TYPES.map(ct => {
            const isSelected = selectedType === ct.value;
            return (
              <button
                key={ct.value}
                onClick={() => { setSelectedType(ct.value); setSelectedTags([]); }}
                style={{
                  minHeight: 72, padding: 14, borderRadius: 12,
                  background: isSelected ? `${C.accent}22` : C.card,
                  border: isSelected ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                  cursor: 'pointer', textAlign: 'left',
                }}
              >
                <div style={{ fontSize: 18, fontWeight: 600, color: isSelected ? C.accent : C.white }}>
                  {ct.label}
                </div>
                <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>
                  {ct.desc}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 快捷标签 */}
      {selectedType && (
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
            快捷标签（可多选）
          </label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {QUICK_TAGS[selectedType].map(tag => {
              const isActive = selectedTags.includes(tag);
              return (
                <button
                  key={tag}
                  onClick={() => toggleTag(tag)}
                  style={{
                    minHeight: 48, padding: '10px 14px', borderRadius: 8,
                    background: isActive ? `${C.accent}22` : C.card,
                    border: isActive ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                    color: isActive ? C.accent : C.text,
                    fontSize: 16, cursor: 'pointer',
                  }}
                >
                  {tag}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 详细描述 */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
          详细描述
        </label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="请描述客诉具体情况..."
          rows={4}
          style={{
            width: '100%', padding: 14, fontSize: 16,
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 12, color: C.white, resize: 'vertical',
            boxSizing: 'border-box', lineHeight: 1.6,
          }}
        />
      </div>

      {/* 拍照按钮(占位) */}
      <div style={{ marginBottom: 24 }}>
        <button
          onClick={() => { /* 调用 camera API */ }}
          style={{
            minHeight: 56, padding: '12px 20px', borderRadius: 12,
            background: C.card, border: `1px dashed ${C.border}`,
            color: C.muted, fontSize: 16, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 8,
          }}
        >
          <span style={{ fontSize: 24 }}>+</span>
          拍照取证（可选）
        </button>
      </div>

      {/* 提交 */}
      <button
        onClick={handleSubmit}
        disabled={!selectedType || submitting}
        style={{
          width: '100%', minHeight: 56, borderRadius: 12,
          background: (!selectedType || submitting) ? C.muted : C.accent,
          color: C.white, border: 'none',
          fontSize: 18, fontWeight: 700,
          cursor: (!selectedType || submitting) ? 'not-allowed' : 'pointer',
          opacity: !selectedType ? 0.5 : 1,
        }}
      >
        {submitting ? '提交中...' : '提交客诉'}
      </button>
    </div>
  );
}
