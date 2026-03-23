import React from 'react';

const BRAND = '#FF6B2C';

const capabilities = [
  { number: '190+', label: 'API 端点', desc: '覆盖餐饮全业务链路的 RESTful API' },
  { number: '10', label: '域服务', desc: 'trade / menu / member / supply / finance / org / analytics / agent / ops / gateway' },
  { number: '73', label: 'Agent Action', desc: '可被 AI Agent 调用的标准化动作接口' },
  { number: '10', label: 'POS Adapter', desc: '主流 POS 硬件的统一适配层' },
];

const curlExample = `# 1. 检查 Gateway 健康状态
curl -X GET https://api.tunxiang.os/gateway/health \\
  -H "Authorization: Bearer <YOUR_API_KEY>"

# 响应
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": "72h 15m",
  "services": {
    "trade": "up",
    "menu": "up",
    "member": "up",
    "supply": "up",
    "finance": "up"
  }
}

# 2. 获取菜单列表
curl -X GET https://api.tunxiang.os/menu/v1/dishes \\
  -H "Authorization: Bearer <YOUR_API_KEY>" \\
  -H "X-Tenant-Id: your-tenant-id"`;

interface Props {
  onNavigate: (page: 'docs' | 'sdk' | 'sandbox') => void;
}

export default function HomePage({ onNavigate }: Props) {
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '60px 24px 80px' }}>
      {/* Hero */}
      <div style={{ textAlign: 'center', marginBottom: 64 }}>
        <h1 style={{ fontSize: 44, fontWeight: 800, color: '#111', marginBottom: 16, lineHeight: 1.2 }}>
          屯象OS 开放平台
        </h1>
        <p style={{ fontSize: 18, color: '#6b7280', maxWidth: 600, margin: '0 auto 32px', lineHeight: 1.7 }}>
          为餐饮行业开发者提供完整的 API、SDK 和工具链，<br />
          快速构建和集成餐饮数字化解决方案
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
          <button
            onClick={() => onNavigate('docs')}
            style={{
              padding: '12px 28px', background: BRAND, color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: 'pointer',
            }}
          >
            查看文档
          </button>
          <button
            onClick={() => onNavigate('sandbox')}
            style={{
              padding: '12px 28px', background: '#fff', color: '#374151', border: '1px solid #d1d5db',
              borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: 'pointer',
            }}
          >
            在线调试
          </button>
        </div>
      </div>

      {/* Capability Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20, marginBottom: 64 }}>
        {capabilities.map((cap) => (
          <div
            key={cap.label}
            style={{
              background: '#fff', borderRadius: 12, padding: '28px 24px',
              border: '1px solid #e5e7eb', transition: 'box-shadow .2s',
            }}
          >
            <div style={{ fontSize: 36, fontWeight: 800, color: BRAND, marginBottom: 4 }}>{cap.number}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#1f2937', marginBottom: 8 }}>{cap.label}</div>
            <div style={{ fontSize: 13, color: '#6b7280', lineHeight: 1.6 }}>{cap.desc}</div>
          </div>
        ))}
      </div>

      {/* Quick Start */}
      <div>
        <h2 style={{ fontSize: 26, fontWeight: 700, color: '#111', marginBottom: 8 }}>
          5 分钟快速开始
        </h2>
        <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 20 }}>
          只需一个 API Key，即可开始调用屯象OS的全部能力
        </p>

        {/* Steps */}
        <div style={{ display: 'flex', gap: 20, marginBottom: 24 }}>
          {[
            { step: '1', title: '注册应用', desc: '在控制台创建应用并获取 API Key' },
            { step: '2', title: '选择 SDK', desc: '支持 Python / Node.js / Java' },
            { step: '3', title: '发起调用', desc: '通过 Gateway 统一入口调用任意域服务' },
          ].map((s) => (
            <div key={s.step} style={{ flex: 1, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <div
                style={{
                  width: 28, height: 28, borderRadius: '50%', background: BRAND, color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 14, fontWeight: 700, flexShrink: 0,
                }}
              >
                {s.step}
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14, color: '#1f2937', marginBottom: 4 }}>{s.title}</div>
                <div style={{ fontSize: 13, color: '#6b7280' }}>{s.desc}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Code Block */}
        <div style={{ background: '#1e293b', borderRadius: 12, padding: '20px 24px', overflowX: 'auto' }}>
          <pre style={{ color: '#e2e8f0', fontSize: 13, lineHeight: 1.7, fontFamily: '"Fira Code", "SF Mono", Consolas, monospace', margin: 0 }}>
            {curlExample}
          </pre>
        </div>
      </div>
    </div>
  );
}
