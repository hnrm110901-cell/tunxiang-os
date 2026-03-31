import { useState } from 'react';

interface Item {
  id: string;
  name: string;
  current_course?: string;
}

interface Props {
  item: Item;
  orderId: string;
  onAssign: (courseName: string) => void;
  onClose: () => void;
}

interface CourseOption {
  name: string;
  label: string;
  icon: string;
}

const COURSE_OPTIONS: CourseOption[] = [
  { name: 'appetizer', label: '前菜', icon: '⏮' },
  { name: 'main', label: '主菜', icon: '🍽' },
  { name: 'dessert', label: '甜品', icon: '🍰' },
  { name: 'drink', label: '饮品', icon: '🍹' },
  { name: '', label: '不分课程', icon: '⬜' },
];

const API_BASE = '/api/v1/orders';

export function CourseAssignModal({ item, orderId, onAssign, onClose }: Props) {
  const [selected, setSelected] = useState<string>(item.current_course ?? '');
  const [loading, setLoading] = useState(false);

  const handleSelect = async (courseName: string) => {
    setSelected(courseName);
    setLoading(true);
    try {
      await fetch(`${API_BASE}/${orderId}/items/${item.id}/course`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': 'demo' },
        body: JSON.stringify({ course_name: courseName }),
      });
      onAssign(courseName);
    } catch {
      // API call failed — still close modal
      onAssign(courseName);
    } finally {
      setLoading(false);
      onClose();
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#112228',
          borderRadius: '16px 16px 0 0',
          width: '100%',
          maxWidth: 480,
          padding: '20px 16px 32px',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <div style={{ width: 36, height: 4, background: '#1a2a33', borderRadius: 2, margin: '0 auto 16px' }} />
        </div>

        <div style={{ color: '#e2e8f0', fontSize: 17, fontWeight: 700, marginBottom: 4 }}>
          选择上菜课程
        </div>
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: 20 }}>
          {item.name}
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 10,
        }}>
          {COURSE_OPTIONS.map(opt => {
            const isSelected = selected === opt.name;
            return (
              <button
                key={opt.name}
                onClick={() => !loading && handleSelect(opt.name)}
                style={{
                  background: isSelected ? '#FF6B35' : '#1a2a33',
                  color: isSelected ? '#fff' : '#e2e8f0',
                  border: isSelected ? '2px solid #FF6B35' : '2px solid #1a2a33',
                  borderRadius: 12,
                  padding: '16px 12px',
                  fontSize: 16,
                  fontWeight: isSelected ? 700 : 400,
                  minHeight: 64,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  opacity: loading ? 0.7 : 1,
                  gridColumn: opt.name === '' ? 'span 2' : undefined,
                }}
              >
                <span style={{ fontSize: 20 }}>{opt.icon}</span>
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>

        <button
          onClick={onClose}
          style={{
            width: '100%',
            marginTop: 16,
            background: 'transparent',
            color: '#64748b',
            border: 'none',
            fontSize: 16,
            minHeight: 48,
            cursor: 'pointer',
          }}
        >
          取消
        </button>
      </div>
    </div>
  );
}
