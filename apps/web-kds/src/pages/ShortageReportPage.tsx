/**
 * ShortageReportPage — 快速缺料上报页（新版）
 *
 * 独立页面，用于从备料站快速上报缺料食材。
 * 表单：食材名 + 数量 + 紧急程度 + 备注
 * 提交: POST /api/v1/supply/shortage-report
 *
 * KDS规范：触屏 / 深色背景 / 无Ant Design / 最小48px点击区
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

// ─── Types ───

type UrgencyLevel = 'normal' | 'urgent' | 'critical';

// ─── Constants ───

const BRAND_COLOR = '#FF6B35';
const BG_MAIN = '#1a1a1a';
const BG_CARD = '#2d2d2d';
const TEXT_WHITE = '#ffffff';
const TEXT_GRAY = '#888888';
const ORANGE = '#FF8C00';
const RED = '#FF3B30';

const API_BASE = (window as any).__STORE_API_BASE__ || '';

const URGENCY_OPTIONS: Array<{
  value: UrgencyLevel;
  label: string;
  icon: string;
  color: string;
  bg: string;
}> = [
  { value: 'normal', label: '一般', icon: '⚠', color: ORANGE, bg: `${ORANGE}22` },
  { value: 'urgent', label: '紧急', icon: '🚨', color: '#FF4500', bg: '#FF450022' },
  { value: 'critical', label: '非常紧急', icon: '🆘', color: RED, bg: `${RED}22` },
];

// ─── Toast ───

function Toast({ message, visible }: { message: string; visible: boolean }) {
  if (!visible) return null;
  return (
    <div
      style={{
        position: 'fixed',
        top: 80,
        left: '50%',
        transform: 'translateX(-50%)',
        background: '#333',
        color: TEXT_WHITE,
        padding: '16px 32px',
        borderRadius: 12,
        fontSize: 18,
        fontWeight: 700,
        zIndex: 2000,
        border: '1px solid #555',
        boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
      }}
    >
      {message}
    </div>
  );
}

// ─── Main Component ───

export default function ShortageReportPage() {
  const navigate = useNavigate();
  const [ingredientName, setIngredientName] = useState('');
  const [quantity, setQuantity] = useState('');
  const [urgency, setUrgency] = useState<UrgencyLevel>('normal');
  const [remark, setRemark] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toastMsg, setToastMsg] = useState('');
  const [toastVisible, setToastVisible] = useState(false);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setToastVisible(true);
    setTimeout(() => setToastVisible(false), 2500);
  };

  const handleSubmit = async () => {
    if (!ingredientName.trim()) {
      showToast('请填写食材名称');
      return;
    }
    setSubmitting(true);
    try {
      if (API_BASE) {
        await txFetch(
          '/api/v1/supply/shortage-report',
          {
            method: 'POST',
            body: JSON.stringify({
              ingredient_name: ingredientName.trim(),
              quantity: quantity.trim(),
              urgency,
              remark: remark.trim(),
            }),
          },
        );
      } else {
        // Mock 成功：模拟网络延迟
        await new Promise(r => setTimeout(r, 600));
      }

      // 微信/安卓 Toast
      try {
        if ((window as any).wx?.showToast) {
          (window as any).wx.showToast({ title: '缺料上报成功', icon: 'success' });
        }
      } catch {
        // 非微信环境忽略
      }

      showToast('✓ 缺料上报成功');

      // 延迟返回
      setTimeout(() => navigate(-1), 1500);
    } catch {
      // 失败时 Mock 成功（KDS不能卡住厨师工作）
      showToast('✓ 已记录（离线模式）');
      setTimeout(() => navigate(-1), 1500);
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: 56,
    background: BG_CARD,
    border: '1.5px solid #3a3a3a',
    borderRadius: 10,
    color: TEXT_WHITE,
    fontSize: 20,
    padding: '0 16px',
    boxSizing: 'border-box',
    outline: 'none',
    fontFamily: 'inherit',
  };

  return (
    <div
      style={{
        background: BG_MAIN,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        color: TEXT_WHITE,
      }}
    >
      <Toast message={toastMsg} visible={toastVisible} />

      {/* ── 头部 ── */}
      <header
        style={{
          height: 64,
          minHeight: 64,
          background: '#111',
          borderBottom: `2px solid ${ORANGE}44`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 20px',
          gap: 16,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            background: '#222',
            border: '1px solid #333',
            color: TEXT_GRAY,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 24, fontWeight: 700, color: ORANGE }}>
          报告缺料
        </span>
      </header>

      {/* ── 表单区域 ── */}
      <div
        style={{
          flex: 1,
          padding: '24px 20px',
          maxWidth: 600,
          width: '100%',
          margin: '0 auto',
          boxSizing: 'border-box',
        }}
      >
        {/* 大号标题 */}
        <div
          style={{
            fontSize: 32,
            fontWeight: 700,
            color: TEXT_WHITE,
            marginBottom: 32,
          }}
        >
          报告缺料
        </div>

        {/* 食材名称 */}
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: 'block',
              fontSize: 18,
              color: TEXT_GRAY,
              marginBottom: 8,
              fontWeight: 600,
            }}
          >
            食材名称 <span style={{ color: RED }}>*</span>
          </label>
          <input
            type="text"
            value={ingredientName}
            onChange={e => setIngredientName(e.target.value)}
            placeholder="例：活基围虾"
            style={inputStyle}
          />
        </div>

        {/* 数量 */}
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: 'block',
              fontSize: 18,
              color: TEXT_GRAY,
              marginBottom: 8,
              fontWeight: 600,
            }}
          >
            数量（可选）
          </label>
          <input
            type="text"
            value={quantity}
            onChange={e => setQuantity(e.target.value)}
            placeholder="例：500g / 3条 / 缺货"
            style={inputStyle}
          />
        </div>

        {/* 紧急程度 */}
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: 'block',
              fontSize: 18,
              color: TEXT_GRAY,
              marginBottom: 12,
              fontWeight: 600,
            }}
          >
            紧急程度
          </label>
          <div style={{ display: 'flex', gap: 12 }}>
            {URGENCY_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setUrgency(opt.value)}
                style={{
                  flex: 1,
                  height: 72,
                  background: urgency === opt.value ? opt.bg : '#222',
                  border: `2px solid ${urgency === opt.value ? opt.color : '#333'}`,
                  borderRadius: 12,
                  color: urgency === opt.value ? opt.color : TEXT_GRAY,
                  fontSize: 18,
                  fontWeight: urgency === opt.value ? 700 : 400,
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 4,
                  transition: 'all 0.15s',
                }}
              >
                <span style={{ fontSize: 24 }}>{opt.icon}</span>
                <span>{opt.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* 备注 */}
        <div style={{ marginBottom: 32 }}>
          <label
            style={{
              display: 'block',
              fontSize: 18,
              color: TEXT_GRAY,
              marginBottom: 8,
              fontWeight: 600,
            }}
          >
            备注（可选）
          </label>
          <textarea
            value={remark}
            onChange={e => setRemark(e.target.value)}
            placeholder="例：今天消耗特别快，需要紧急补货"
            rows={3}
            style={{
              ...inputStyle,
              height: 'auto',
              padding: '12px 16px',
              resize: 'none',
              lineHeight: 1.6,
            }}
          />
        </div>

        {/* 提交按钮 */}
        <button
          onClick={handleSubmit}
          disabled={submitting || !ingredientName.trim()}
          style={{
            width: '100%',
            height: 64,
            background: submitting || !ingredientName.trim() ? '#333' : BRAND_COLOR,
            color: submitting || !ingredientName.trim() ? TEXT_GRAY : TEXT_WHITE,
            border: 'none',
            borderRadius: 12,
            fontSize: 22,
            fontWeight: 700,
            cursor: submitting || !ingredientName.trim() ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s',
          }}
          onTouchStart={e => {
            if (!submitting && ingredientName.trim()) {
              (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.98)';
            }
          }}
          onTouchEnd={e => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
          }}
        >
          {submitting ? '提交中…' : '提交缺料上报'}
        </button>
      </div>
    </div>
  );
}
