/**
 * LoginPage — 登录页面
 */
import { useState, FormEvent } from 'react';

interface LoginPageProps { onLogin: () => void; }

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res = await fetch('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
      const json = await res.json();
      if (json.ok) { localStorage.setItem('tx_token', json.data.token); localStorage.setItem('tx_user', JSON.stringify(json.data.user)); onLogin(); }
      else { setError(json.error?.message || '登录失败'); }
    } catch (_err) { setError('网络错误，请检查连接'); } finally { setLoading(false); }

      if (json.ok) {
        localStorage.setItem('tx_token', json.data.token);
        localStorage.setItem('tx_user', JSON.stringify(json.data.user));
        const u = json.data.user as { tenant_id?: string } | undefined;
        if (u?.tenant_id) {
          localStorage.setItem('tx_tenant_id', u.tenant_id);
        }
        onLogin();
      } else {
        setError(json.error?.message || '登录失败');
      }
    } catch (_err) {
      setError('网络错误，请检查连接');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: '#0a1929', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: "'Inter', 'Noto Sans SC', -apple-system, sans-serif" }}>
      <div style={{ position: 'fixed', top: '35%', left: '50%', transform: 'translate(-50%, -50%)', width: 600, height: 600, borderRadius: '50%', background: 'radial-gradient(circle, rgba(255,107,44,0.06) 0%, transparent 70%)', pointerEvents: 'none' }} />
      <div style={{ width: 400, background: '#0f2233', borderRadius: 16, padding: '48px 40px', boxShadow: '0 4px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.05)', position: 'relative', zIndex: 1 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ width: 56, height: 56, borderRadius: 14, background: 'linear-gradient(135deg, #ff6b2c, #ff8f5e)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, fontWeight: 'bold', color: '#fff', marginBottom: 16, boxShadow: '0 4px 20px rgba(255,107,44,0.3)' }}>TX</div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#fff', letterSpacing: 1 }}>屯象OS</h1>
          <p style={{ margin: '8px 0 0', fontSize: 13, color: 'rgba(255,255,255,0.45)', letterSpacing: 0.5 }}>AI-Native 连锁餐饮经营操作系统</p>
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <input type="text" placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus style={{ width: '100%', height: 44, padding: '0 14px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.04)', color: '#fff', fontSize: 14, outline: 'none', boxSizing: 'border-box' }} />
          </div>
          <div style={{ marginBottom: 24 }}>
            <input type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} style={{ width: '100%', height: 44, padding: '0 14px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.04)', color: '#fff', fontSize: 14, outline: 'none', boxSizing: 'border-box' }} />
          </div>
          {error && (<div style={{ marginBottom: 16, padding: '10px 14px', borderRadius: 8, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', color: '#f87171', fontSize: 13, textAlign: 'center' }}>{error}</div>)}
          <button type="submit" disabled={loading || !username || !password} style={{ width: '100%', height: 44, borderRadius: 10, border: 'none', background: (!loading && username && password) ? 'linear-gradient(135deg, #ff6b2c, #ff8f5e)' : 'rgba(255,107,44,0.3)', color: '#fff', fontSize: 15, fontWeight: 600, cursor: (!loading && username && password) ? 'pointer' : 'not-allowed' }}>
            {loading ? '登录中...' : '登 录'}
          </button>
        </form>
        {/* Demo: czq_admin/czq2024! zqx_admin/zqx2024! sgc_admin/sgc2024! tx_superadmin/tunxiang2024! */}
        <p style={{ marginTop: 28, fontSize: 11, color: 'rgba(255,255,255,0.25)', textAlign: 'center' }}>请使用分配的商户账号登录</p>
      </div>
    </div>
  );
}
