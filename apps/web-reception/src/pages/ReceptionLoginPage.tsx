/**
 * 迎宾端登录页 — iPad 横屏，轻奢风格
 * 符合 TXTouch 规范：56px 按钮，16px+ 字体
 */
import { useState, FormEvent } from 'react';
import { setStoreToken } from '../api/index';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface ReceptionLoginPageProps {
  onLogin: () => void;
}

export function ReceptionLoginPage({ onLogin }: ReceptionLoginPageProps) {
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
        setError(json.error?.message || '账号或密码错误');
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
      background: 'var(--tx-bg-2, #F8F7F5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    }}>
      <div style={{
        width: 480,
        background: '#fff',
        borderRadius: 20,
        padding: '56px 48px',
        boxShadow: '0 8px 40px rgba(0,0,0,0.1)',
      }}>
        {/* 品牌 */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <div style={{
            width: 60, height: 60, borderRadius: 15,
            background: 'linear-gradient(135deg, #FF6B2C, #FF8F5E)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22, fontWeight: 900, color: '#fff', marginBottom: 16,
          }}>TX</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#1E2A3A' }}>屯象迎宾</div>
          <div style={{ fontSize: 16, color: '#8899AA', marginTop: 6 }}>请登录迎宾接待系统</div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <input
              type="text"
              placeholder="账号"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              style={{
                width: '100%', height: 56, padding: '0 16px',
                borderRadius: 12, border: '1.5px solid #E8E6E1',
                background: '#F8F7F5', color: '#2C2C2A',
                fontSize: 17, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: 24 }}>
            <input
              type="password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: '100%', height: 56, padding: '0 16px',
                borderRadius: 12, border: '1.5px solid #E8E6E1',
                background: '#F8F7F5', color: '#2C2C2A',
                fontSize: 17, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          {error && (
            <div style={{
              marginBottom: 16, padding: '12px 16px', borderRadius: 10,
              background: '#FEF2F2', border: '1px solid #FCA5A5',
              color: '#DC2626', fontSize: 16, textAlign: 'center',
            }}>{error}</div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            style={{
              width: '100%', height: 56, borderRadius: 12, border: 'none',
              background: (!loading && username && password)
                ? 'linear-gradient(135deg, #FF6B2C, #FF8F5E)'
                : '#E8E6E1',
              color: (!loading && username && password) ? '#fff' : '#B4B2A9',
              fontSize: 17, fontWeight: 700,
              cursor: (!loading && username && password) ? 'pointer' : 'not-allowed',
              transition: 'transform 150ms',
              letterSpacing: 1,
            }}
            onPointerDown={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onPointerUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            onPointerLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            {loading ? '登录中...' : '登 录'}
          </button>
        </form>
      </div>
    </div>
  );
}
