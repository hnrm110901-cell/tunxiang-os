/**
 * POS 终端登录页 — 触控优化，横屏
 * 符合 TXTouch 规范：最小点击区域 56px，字体 ≥ 16px
 */
import { useState, FormEvent } from 'react';
import { setStoreToken } from '../api/index';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface PosLoginPageProps {
  onLogin: () => void;
}

export function PosLoginPage({ onLogin }: PosLoginPageProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const json = await res.json();
      if (json.ok) {
        setStoreToken(json.data.token);
        onLogin();
      } else {
        setError(json.error?.message || '用户名或密码错误');
      }
    } catch {
      setError('网络错误，请检查连接');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0B1A20',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, "PingFang SC", sans-serif',
    }}>
      <div style={{
        width: 480,
        background: '#112228',
        borderRadius: 20,
        padding: '48px 40px',
        boxShadow: '0 8px 48px rgba(0,0,0,0.5)',
      }}>
        {/* 品牌 */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <div style={{
            width: 64, height: 64, borderRadius: 16,
            background: 'linear-gradient(135deg, #FF6B2C, #FF8F5E)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, fontWeight: 900, color: '#fff', marginBottom: 16,
          }}>TX</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>屯象收银</div>
          <div style={{ fontSize: 16, color: 'rgba(255,255,255,0.45)', marginTop: 6 }}>请刷卡或输入员工账号登录</div>
        </div>

        <form onSubmit={handleSubmit}>
          {/* 用户名 */}
          <div style={{ marginBottom: 16 }}>
            <input
              type="text"
              placeholder="员工账号"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              style={{
                width: '100%', height: 56, padding: '0 18px',
                borderRadius: 12, border: '1.5px solid rgba(255,255,255,0.12)',
                background: 'rgba(255,255,255,0.05)', color: '#fff',
                fontSize: 18, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          {/* 密码 */}
          <div style={{ marginBottom: 24 }}>
            <input
              type="password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              style={{
                width: '100%', height: 56, padding: '0 18px',
                borderRadius: 12, border: '1.5px solid rgba(255,255,255,0.12)',
                background: 'rgba(255,255,255,0.05)', color: '#fff',
                fontSize: 18, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          {/* 错误提示 */}
          {error && (
            <div style={{
              marginBottom: 16, padding: '12px 16px', borderRadius: 10,
              background: 'rgba(163,45,45,0.15)', border: '1px solid rgba(163,45,45,0.4)',
              color: '#f87171', fontSize: 16, textAlign: 'center',
            }}>{error}</div>
          )}

          {/* 登录按钮 72px 高 */}
          <button
            type="submit"
            disabled={loading || !username || !password}
            style={{
              width: '100%', height: 72, borderRadius: 14, border: 'none',
              background: (!loading && username && password)
                ? 'linear-gradient(135deg, #FF6B2C, #FF8F5E)'
                : 'rgba(255,107,44,0.25)',
              color: '#fff', fontSize: 20, fontWeight: 700,
              cursor: (!loading && username && password) ? 'pointer' : 'not-allowed',
              transition: 'transform 200ms, opacity 200ms',
              letterSpacing: 2,
            }}
            onPointerDown={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onPointerUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            {loading ? '登录中...' : '登 录'}
          </button>
        </form>
      </div>
    </div>
  );
}
