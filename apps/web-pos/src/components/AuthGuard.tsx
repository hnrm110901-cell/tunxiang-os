/**
 * 路由守卫 — 未登录用户重定向到 /login
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading, checkSession } = useAuthStore();
  const navigate = useNavigate();

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      navigate('/login', { replace: true });
    }
  }, [loading, isAuthenticated, navigate]);

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          background: '#0B1A20',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              border: '4px solid #1E3A45',
              borderTopColor: '#FF6B2C',
              borderRadius: '50%',
              animation: 'tx-spin 0.8s linear infinite',
              margin: '0 auto 16px',
            }}
          />
          <div style={{ color: '#6B8A99', fontSize: '14px' }}>加载中...</div>
          <style>{`@keyframes tx-spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
