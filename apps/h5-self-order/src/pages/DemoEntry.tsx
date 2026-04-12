/**
 * 演示入口页 — /m?store=[STORE_ID]&table=[TABLE_NO]&demo=true
 *
 * 功能：
 *   1. 读取 URL 参数 store / table / demo
 *   2. 无参数时自动使用演示默认值（尝在一起·文化城店 A03 桌）
 *   3. 展示 logo 动画 + 欢迎语 → 2 秒后自动跳转菜单页
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useOrderStore } from '@/store/useOrderStore';
import { setApiTenantId } from '@/api/index';

/** 演示默认配置 — 尝在一起·文化城店 A03 桌 */
const DEMO_DEFAULTS = {
  storeId: 'czyz-wh001',
  storeName: '尝在一起·文化城店',
  tableNo: 'A03',
  tenantId: 'demo-tenant-czyz',
  templateType: 'default' as const,
};

export default function DemoEntry() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const setStoreInfo = useOrderStore((s) => s.setStoreInfo);

  const [progress, setProgress] = useState(0);
  const [storeName, setStoreName] = useState('');
  const [tableNo, setTableNo] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    // 读取 URL 参数，缺失时用演示默认值
    const storeId = searchParams.get('store') || DEMO_DEFAULTS.storeId;
    const table   = searchParams.get('table') || DEMO_DEFAULTS.tableNo;
    const name    = searchParams.get('name')  || DEMO_DEFAULTS.storeName;
    const tenantId = DEMO_DEFAULTS.tenantId;

    setStoreName(name);
    setTableNo(table);

    // 写入全局 store
    setStoreInfo({
      storeId,
      storeName: name,
      tableNo: table,
      tenantId,
      templateType: 'default',
    });
    setApiTenantId(tenantId);

    // 进度条动画：2 秒后跳转
    let pct = 0;
    timerRef.current = setInterval(() => {
      pct += 4;
      setProgress(Math.min(pct, 100));
      if (pct >= 100) {
        clearInterval(timerRef.current);
        navigate('/menu');
      }
    }, 80);

    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      style={{
        minHeight: '100vh',
        maxWidth: 390,
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--tx-bg-primary)',
        padding: '40px 32px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* 背景装饰圆 */}
      <div
        style={{
          position: 'absolute',
          top: -120,
          right: -80,
          width: 320,
          height: 320,
          borderRadius: '50%',
          background: 'rgba(255,107,44,0.06)',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: -80,
          left: -60,
          width: 240,
          height: 240,
          borderRadius: '50%',
          background: 'rgba(255,107,44,0.04)',
          pointerEvents: 'none',
        }}
      />

      {/* Logo 区 */}
      <div
        className="tx-fade-in"
        style={{
          width: 88,
          height: 88,
          borderRadius: 24,
          background: 'var(--tx-brand)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 24,
          boxShadow: '0 12px 32px rgba(255,107,44,0.35)',
        }}
      >
        {/* 筷子图标 SVG */}
        <svg width="44" height="44" viewBox="0 0 44 44" fill="none">
          <rect x="18" y="6" width="4" height="28" rx="2" fill="white" opacity="0.9"/>
          <rect x="26" y="10" width="4" height="24" rx="2" fill="white"/>
          <ellipse cx="22" cy="38" rx="10" ry="3" fill="white" opacity="0.3"/>
        </svg>
      </div>

      {/* 品牌名 */}
      <h1
        className="tx-fade-in"
        style={{
          fontSize: 28,
          fontWeight: 800,
          color: 'var(--tx-text-primary)',
          textAlign: 'center',
          letterSpacing: 2,
          marginBottom: 6,
        }}
      >
        {storeName || '尝在一起'}
      </h1>

      {/* 桌号标签 */}
      {tableNo && (
        <div
          className="tx-fade-in"
          style={{
            marginTop: 8,
            padding: '6px 18px',
            borderRadius: 'var(--tx-radius-full)',
            background: 'var(--tx-brand-light)',
            border: '1px solid rgba(255,107,44,0.25)',
          }}
        >
          <span style={{ fontSize: 14, color: 'var(--tx-brand)', fontWeight: 600 }}>
            桌号：{tableNo}
          </span>
        </div>
      )}

      {/* 欢迎语 */}
      <p
        className="tx-fade-in"
        style={{
          marginTop: 24,
          fontSize: 16,
          color: 'var(--tx-text-secondary)',
          textAlign: 'center',
          lineHeight: 1.7,
        }}
      >
        欢迎光临，请稍等片刻
        <br />
        正在为您准备菜单...
      </p>

      {/* 进度条 */}
      <div
        style={{
          width: '100%',
          maxWidth: 240,
          height: 4,
          borderRadius: 2,
          background: 'var(--tx-bg-tertiary)',
          marginTop: 40,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${progress}%`,
            borderRadius: 2,
            background: 'var(--tx-brand)',
            transition: 'width 0.08s linear',
          }}
        />
      </div>

      {/* 提示文字 */}
      <p
        style={{
          marginTop: 12,
          fontSize: 13,
          color: 'var(--tx-text-tertiary)',
        }}
      >
        正在进入点餐页面...
      </p>

      {/* 跳过按钮（演示用） */}
      <button
        className="tx-pressable"
        onClick={() => navigate('/menu')}
        style={{
          position: 'absolute',
          bottom: 40,
          right: 24,
          padding: '8px 18px',
          borderRadius: 'var(--tx-radius-full)',
          background: 'var(--tx-bg-tertiary)',
          color: 'var(--tx-text-tertiary)',
          fontSize: 13,
        }}
      >
        跳过
      </button>
    </div>
  );
}
