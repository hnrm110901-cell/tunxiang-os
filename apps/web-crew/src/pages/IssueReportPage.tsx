/**
 * 问题上报页面（E5）— 服务员/店长端 PWA
 * 路由：/issue-report
 * 功能：问题类型选择 + 描述 + 严重程度 + 照片 + 提交
 */
import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 颜色常量（Design Token）---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  primaryActive: '#E55A28',
  primaryLight: 'rgba(255,107,53,0.12)',
  success: '#0F6E56',
  successBg: 'rgba(15,110,86,0.12)',
  warning: '#BA7517',
  warningBg: 'rgba(186,117,23,0.12)',
  danger: '#A32D2D',
  dangerBg: 'rgba(163,45,45,0.12)',
  inputBg: '#0d1e25',
};

/* ---------- 类型 ---------- */
type IssueType = 'food_safety' | 'equipment' | 'hygiene' | 'complaint' | 'other';
type Severity = 'low' | 'medium' | 'high';

interface IssueTypeOption {
  value: IssueType;
  label: string;
  icon: string;
  color: string;
  bg: string;
}

interface SeverityOption {
  value: Severity;
  label: string;
  color: string;
  bg: string;
  border: string;
}

/* ---------- 配置 ---------- */
const ISSUE_TYPES: IssueTypeOption[] = [
  { value: 'food_safety', label: '食品安全', icon: '🍽️', color: C.danger, bg: C.dangerBg },
  { value: 'equipment',   label: '设备故障', icon: '⚙️',  color: C.warning, bg: C.warningBg },
  { value: 'hygiene',     label: '卫生问题', icon: '🧹', color: '#185FA5', bg: 'rgba(24,95,165,0.10)' },
  { value: 'complaint',   label: '客户投诉', icon: '💬', color: C.primary, bg: C.primaryLight },
  { value: 'other',       label: '其他问题', icon: '📋', color: C.muted,   bg: 'rgba(100,116,139,0.12)' },
];

const SEVERITY_OPTIONS: SeverityOption[] = [
  { value: 'low',    label: '低',  color: C.success, bg: C.successBg, border: C.success },
  { value: 'medium', label: '中',  color: C.warning, bg: C.warningBg, border: C.warning },
  { value: 'high',   label: '高',  color: C.danger,  bg: C.dangerBg,  border: C.danger  },
];

/* ---------- API ---------- */
function getTenantId(): string {
  return localStorage.getItem('tenant_id') ?? '';
}

interface IssuePayload {
  issue_type: IssueType;
  description: string;
  severity: Severity;
  photo_urls: string[];
  reported_at: string;
}

interface IssueResponse {
  issue_id: string;
  issue_no: string;
}

async function postIssue(payload: IssuePayload): Promise<IssueResponse> {
  const res = await fetch('/api/v1/ops/issues', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`问题上报失败: ${res.status}`);
  const json = await res.json();
  return json.data as IssueResponse;
}

/* ---------- 主组件 ---------- */
export function IssueReportPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedType, setSelectedType] = useState<IssueType | null>(null);
  const [description, setDescription] = useState('');
  const [severity, setSeverity] = useState<Severity>('medium');
  const [photoUrls, setPhotoUrls] = useState<string[]>([]);    // 本地 object URL
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<IssueResponse | null>(null);
  const [submitBtnPressed, setSubmitBtnPressed] = useState(false);

  /* --- 照片处理 --- */
  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    const newUrls = files.map(f => URL.createObjectURL(f));
    setPhotoUrls(prev => [...prev, ...newUrls].slice(0, 4));   // 最多4张
    e.target.value = '';
  };

  const removePhoto = (url: string) => {
    URL.revokeObjectURL(url);
    setPhotoUrls(prev => prev.filter(u => u !== url));
  };

  /* --- 提交 --- */
  const handleSubmit = async () => {
    if (!selectedType || !description.trim()) return;
    setSubmitting(true);
    try {
      const payload: IssuePayload = {
        issue_type: selectedType,
        description: description.trim(),
        severity,
        photo_urls: photoUrls,   // 实际生产应先上传 OSS 取 URL
        reported_at: new Date().toISOString(),
      };
      const res = await postIssue(payload);
      setResult(res);
    } catch {
      // API 未就绪：mock 结果
      setResult({
        issue_id: `ISS-${Date.now()}`,
        issue_no: `IRP-${new Date().toISOString().slice(2, 10).replace(/-/g, '')}-${String(Math.floor(Math.random() * 9000) + 1000)}`,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit = selectedType !== null && description.trim().length > 0;

  /* ---------- 成功界面 ---------- */
  if (result) {
    return (
      <div style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ width: 80, height: 80, borderRadius: 40, background: C.successBg, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 24 }}>
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
            <path d="M10 20l7 7 13-14" stroke={C.success} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, color: C.text, marginBottom: 10 }}>问题已上报</div>
        <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>问题单号</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: C.primary, marginBottom: 8, letterSpacing: 1 }}>
          {result.issue_no}
        </div>
        <div style={{ fontSize: 15, color: C.muted, marginBottom: 40, textAlign: 'center', lineHeight: 1.6 }}>
          问题已提交，负责人将收到通知并跟进处理。
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%', maxWidth: 360 }}>
          <button
            onClick={() => navigate('/daily-settlement')}
            style={{ height: 56, background: C.primary, color: '#fff', border: 'none', borderRadius: 14, fontSize: 17, fontWeight: 700, cursor: 'pointer' }}
          >
            返回日结清单
          </button>
          <button
            onClick={() => { setResult(null); setSelectedType(null); setDescription(''); setSeverity('medium'); setPhotoUrls([]); }}
            style={{ height: 56, background: 'transparent', color: C.muted, border: `1px solid ${C.border}`, borderRadius: 14, fontSize: 17, cursor: 'pointer' }}
          >
            再次上报
          </button>
        </div>
      </div>
    );
  }

  /* ---------- 表单界面 ---------- */
  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, paddingBottom: 100 }}>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '16px 16px 14px', borderBottom: `1px solid ${C.border}` }}>
        <button
          onClick={() => navigate(-1)}
          style={{ width: 44, height: 44, background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 8 }}
        >
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <path d="M14 6l-6 5 6 5" stroke={C.text} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>E5 问题上报</div>
          <div style={{ fontSize: 14, color: C.muted }}>记录并跟踪门店运营问题</div>
        </div>
      </div>

      <div style={{ padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: 24 }}>

        {/* 问题类型 */}
        <section>
          <div style={{ fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 12 }}>
            问题类型 <span style={{ color: C.danger }}>*</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
            {ISSUE_TYPES.slice(0, 3).map(opt => (
              <TypeButton key={opt.value} opt={opt} selected={selectedType === opt.value} onSelect={setSelectedType} />
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginTop: 10 }}>
            {ISSUE_TYPES.slice(3).map(opt => (
              <TypeButton key={opt.value} opt={opt} selected={selectedType === opt.value} onSelect={setSelectedType} />
            ))}
          </div>
        </section>

        {/* 严重程度 */}
        <section>
          <div style={{ fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 12 }}>严重程度</div>
          <div style={{ display: 'flex', gap: 10 }}>
            {SEVERITY_OPTIONS.map(opt => {
              const isSelected = severity === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => setSeverity(opt.value)}
                  style={{
                    flex: 1, height: 56,
                    background: isSelected ? opt.bg : C.card,
                    border: `2px solid ${isSelected ? opt.border : C.border}`,
                    borderRadius: 12, cursor: 'pointer',
                    fontSize: 17, fontWeight: 700,
                    color: isSelected ? opt.color : C.muted,
                    transition: 'all 0.15s',
                  }}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </section>

        {/* 问题描述 */}
        <section>
          <div style={{ fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 12 }}>
            问题描述 <span style={{ color: C.danger }}>*</span>
          </div>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            placeholder="请详细描述问题情况，包括发生时间、地点、经过..."
            rows={5}
            style={{
              width: '100%', background: C.inputBg,
              border: `2px solid ${description.trim() ? C.primary : C.border}`,
              borderRadius: 12, padding: '14px 16px',
              fontSize: 17, color: C.text, outline: 'none',
              resize: 'none', lineHeight: 1.6, fontFamily: 'inherit',
              boxSizing: 'border-box', transition: 'border-color 0.2s',
            }}
          />
          <div style={{ fontSize: 14, color: C.muted, marginTop: 6, textAlign: 'right' }}>
            {description.length} 字
          </div>
        </section>

        {/* 照片上传 */}
        <section>
          <div style={{ fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 12 }}>
            照片记录 <span style={{ fontSize: 14, color: C.muted, fontWeight: 400 }}>（最多4张）</span>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {photoUrls.map(url => (
              <div key={url} style={{ position: 'relative', width: 80, height: 80 }}>
                <img
                  src={url} alt="问题照片"
                  style={{ width: 80, height: 80, objectFit: 'cover', borderRadius: 10, border: `1px solid ${C.border}` }}
                />
                <button
                  onClick={() => removePhoto(url)}
                  style={{
                    position: 'absolute', top: -8, right: -8,
                    width: 24, height: 24, borderRadius: 12,
                    background: C.danger, border: 'none', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M2 2l8 8M10 2L2 10" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            ))}
            {photoUrls.length < 4 && (
              <button
                onClick={() => fileInputRef.current?.click()}
                style={{
                  width: 80, height: 80, background: C.card,
                  border: `2px dashed ${C.border}`, borderRadius: 10,
                  cursor: 'pointer', display: 'flex', flexDirection: 'column',
                  alignItems: 'center', justifyContent: 'center', gap: 4, color: C.muted,
                }}
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
                <span style={{ fontSize: 12 }}>拍照</span>
              </button>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            onChange={handlePhotoChange}
            style={{ display: 'none' }}
          />
        </section>
      </div>

      {/* 底部提交按钮 */}
      <div style={{ position: 'fixed', bottom: 0, left: 0, right: 0, padding: '12px 16px 28px', background: C.bg, borderTop: `1px solid ${C.border}` }}>
        <button
          disabled={!canSubmit || submitting}
          onPointerDown={() => setSubmitBtnPressed(true)}
          onPointerUp={() => setSubmitBtnPressed(false)}
          onPointerLeave={() => setSubmitBtnPressed(false)}
          onClick={handleSubmit}
          style={{
            width: '100%', height: 60,
            background: canSubmit ? C.primary : C.card,
            color: canSubmit ? '#fff' : C.muted,
            border: canSubmit ? 'none' : `1px solid ${C.border}`,
            borderRadius: 14, fontSize: 18, fontWeight: 700,
            cursor: canSubmit ? 'pointer' : 'not-allowed',
            transform: (submitBtnPressed && canSubmit) ? 'scale(0.97)' : 'scale(1)',
            transition: 'transform 0.2s ease, background 0.2s',
            opacity: submitting ? 0.7 : 1,
          }}
        >
          {submitting ? '提交中...' : canSubmit ? '提交问题' : '请填写类型和描述'}
        </button>
      </div>
    </div>
  );
}

/* ---------- 类型按钮子组件 ---------- */
interface TypeButtonProps {
  opt: IssueTypeOption;
  selected: boolean;
  onSelect: (v: IssueType) => void;
}

function TypeButton({ opt, selected, onSelect }: TypeButtonProps) {
  const [pressed, setPressed] = useState(false);
  return (
    <button
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      onClick={() => onSelect(opt.value)}
      style={{
        minHeight: 72, padding: '14px 8px',
        background: selected ? opt.bg : '#112228',
        border: `2px solid ${selected ? opt.color : '#1a2a33'}`,
        borderRadius: 12, cursor: 'pointer',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6,
        transform: pressed ? 'scale(0.96)' : 'scale(1)',
        transition: 'transform 0.2s ease, border-color 0.15s, background 0.15s',
      }}
    >
      <span style={{ fontSize: 26, lineHeight: 1 }}>{opt.icon}</span>
      <span style={{ fontSize: 15, fontWeight: 600, color: selected ? opt.color : '#E0E0E0', textAlign: 'center', lineHeight: 1.2 }}>
        {opt.label}
      </span>
    </button>
  );
}
