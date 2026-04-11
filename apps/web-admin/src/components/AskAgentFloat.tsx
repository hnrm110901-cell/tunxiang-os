/**
 * AskAgentFloat — 右下角悬浮 AI 问答按钮
 * 默认收起，点击后展开 NLQChatPanel
 */
import { useState } from 'react';
import { Card } from 'antd';
import NLQChatPanel from './NLQChatPanel';

const AskAgentFloat = () => {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      {/* 展开面板 */}
      <div style={{
        position: 'fixed',
        right: 24,
        bottom: 84,
        width: 240,
        zIndex: 1000,
        opacity: expanded ? 1 : 0,
        pointerEvents: expanded ? 'auto' : 'none',
        transform: expanded ? 'translateY(0) scale(1)' : 'translateY(20px) scale(0.95)',
        transition: 'opacity 0.25s ease, transform 0.25s ease',
      }}>
        <Card
          title={
            <span style={{ fontSize: 13, fontWeight: 600 }}>
              🤖 AI 智能问答
            </span>
          }
          styles={{
            header: { padding: '8px 12px', minHeight: 40 },
            body: { padding: 12 },
          }}
          style={{
            boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
            borderRadius: 12,
          }}
          extra={
            <button
              onClick={() => setExpanded(false)}
              style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#888', fontSize: 16, lineHeight: 1 }}
            >
              ×
            </button>
          }
        >
          <NLQChatPanel height={240} placeholder="问我任何经营问题…" />
        </Card>
      </div>

      {/* 悬浮按钮 */}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          width: 48,
          height: 48,
          borderRadius: '50%',
          background: '#FF6B35',
          border: 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 22,
          boxShadow: '0 4px 16px rgba(255,107,53,0.45)',
          zIndex: 1001,
          transition: 'transform 0.2s ease, box-shadow 0.2s ease',
          color: '#fff',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'scale(1.1)';
          e.currentTarget.style.boxShadow = '0 6px 24px rgba(255,107,53,0.55)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'scale(1)';
          e.currentTarget.style.boxShadow = '0 4px 16px rgba(255,107,53,0.45)';
        }}
        title="AI 智能问答"
        aria-label="打开 AI 问答"
      >
        🤖
      </button>
    </>
  );
};

export default AskAgentFloat;
