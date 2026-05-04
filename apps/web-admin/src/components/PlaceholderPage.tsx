/**
 * 功能开发中的占位页面 — 暗色主题，支持返回导航
 * 替换 web-admin hr/ 目录下 15 个 Ant Design Result 占位页
 */
import { useNavigate } from 'react-router-dom';
import type { CSSProperties } from 'react';

interface PlaceholderPageProps {
  /** 功能模块名称 */
  title: string;
  /** 英文/副标题 */
  subtitle?: string;
  /** 简要说明 */
  description?: string;
  backTo?: string;
  backLabel?: string;
}

const C = {
  wrap: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    minHeight: '100vh', background: '#0B1A20',
  } as CSSProperties,
  card: {
    background: '#112B36',
    borderRadius: 16,
    padding: '60px 48px',
    textAlign: 'center',
    maxWidth: 440,
    width: '100%',
  } as CSSProperties,
  icon: {
    width: 80, height: 80, borderRadius: '50%',
    background: 'rgba(45,156,219,0.12)',
    margin: '0 auto 20px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 32,
  } as CSSProperties,
  title: {
    fontSize: 20, fontWeight: 700, color: '#fff', marginBottom: 8,
  } as CSSProperties,
  subtitle: {
    fontSize: 14, color: 'rgba(255,255,255,0.38)', marginBottom: 4,
  } as CSSProperties,
  desc: {
    fontSize: 14, color: 'rgba(255,255,255,0.45)',
    lineHeight: 1.6, margin: '16px 0 24px',
  } as CSSProperties,
  btn: {
    height: 44, padding: '0 28px', borderRadius: 8, border: 'none',
    background: '#FF6B35', color: '#fff', fontSize: 15, fontWeight: 600,
    cursor: 'pointer',
  } as CSSProperties,
};

export function PlaceholderPage({
  title, subtitle, description, backTo = '/', backLabel = '返回首页',
}: PlaceholderPageProps) {
  const navigate = useNavigate();

  return (
    <div style={C.wrap}>
      <div style={C.card}>
        <div style={C.icon}>🏗️</div>
        <h1 style={C.title}>{title}</h1>
        {subtitle && <div style={C.subtitle}>{subtitle}</div>}
        <div style={C.desc}>
          {description || '该功能模块正在开发中，预计近期上线。'}
        </div>
        <button style={C.btn} onClick={() => navigate(backTo)}>
          {backLabel}
        </button>
      </div>
    </div>
  );
}
