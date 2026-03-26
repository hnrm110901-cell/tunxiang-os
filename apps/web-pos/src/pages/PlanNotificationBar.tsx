/**
 * PlanNotificationBar -- POS 端计划通知条
 * 固定在收银界面顶部，展示今日计划摘要 + 风险预警
 */
import { useState } from 'react';

// ---- 颜色常量 ----
const BRAND = '#FF6B2C';
const BG_BAR = '#112228';
const BG_RISK = '#ff4d4f';
const BG_EXPAND = '#0B1A20';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const GREEN = '#52c41a';
const YELLOW = '#faad14';
const RED = '#ff4d4f';

// ---- Mock 数据（与 DailyPlanPage 对应） ----

interface PlanSummary {
  highlights: string[];    // 一行摘要关键点
  sections: {
    icon: string;
    title: string;
    items: string[];
  }[];
  hasUnresolvedRisk: boolean;
  riskDetail?: string;
}

const MOCK_PLAN: PlanSummary = {
  highlights: [
    '\u4E3B\u63A8\u5241\u6912\u9C7C\u5934',
    '\u51CF\u63A8\u5916\u5A46\u9E21',
    '\u57FA\u56F4\u867E\u9700\u7D27\u6025\u91C7\u8D2D',
  ],
  hasUnresolvedRisk: true,
  riskDetail: '\u4E09\u6587\u9C7C(\u6279\u6B21B2403)\u660E\u65E5\u5230\u671F, \u5269\u4F592.3kg',
  sections: [
    {
      icon: '\uD83D\uDCCB',
      title: '\u6392\u83DC\u5EFA\u8BAE',
      items: [
        '\u5241\u6912\u9C7C\u5934 \u2192 \u4E3B\u63A8 (\u7F6E\u4FE1\u5EA692%)',
        '\u5916\u5A46\u9E21 \u2192 \u51CF\u63A8 (\u9E21\u8089\u5E93\u5B58\u4F4E)',
        '\u9178\u83DC\u9C7C \u2192 \u8BD5\u70B9\u7B2C3\u5929',
      ],
    },
    {
      icon: '\uD83D\uDCE6',
      title: '\u7D27\u6025\u91C7\u8D2D',
      items: [
        '\uD83D\uDD34 \u57FA\u56F4\u867E 15kg (\u6E58\u6C5F\u6C34\u4EA7)',
        '\uD83D\uDFE1 \u9999\u83DC 5kg (\u7EA2\u661F\u519C\u6279)',
      ],
    },
    {
      icon: '\uD83D\uDC65',
      title: '\u6392\u73ED',
      items: [
        '\u5348\u9AD8\u5CF0\u589E\u52A0 1\u540D\u670D\u52A1\u5458 (11:00-14:00)',
      ],
    },
    {
      icon: '\u26A0\uFE0F',
      title: '\u98CE\u9669\u9884\u8B66',
      items: [
        '\u{1F534} \u4E09\u6587\u9C7C(B2403)\u660E\u65E5\u5230\u671F - \u5348\u5E02\u524D\u7528\u5B8C',
        '\u{1F7E1} 2\u53F7\u51FA\u9910\u53E3\u6253\u5370\u673A\u5EF6\u8FDF',
      ],
    },
  ],
};

// ---- 组件 ----

export function PlanNotificationBar() {
  const [expanded, setExpanded] = useState(false);
  const plan = MOCK_PLAN;

  const barBg = plan.hasUnresolvedRisk ? BG_RISK : BG_BAR;

  return (
    <div style={{ position: 'relative', zIndex: 100 }}>
      {/* 通知条 - 一行 */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          background: barBg,
          color: TEXT_1,
          padding: '8px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          userSelect: 'none',
          fontSize: 13,
          fontWeight: 500,
          borderBottom: `1px solid ${plan.hasUnresolvedRisk ? '#cc3333' : '#1a2a33'}`,
          transition: 'background .3s',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden' }}>
          <span style={{ fontSize: 14 }}>{'\uD83D\uDCCB'}</span>
          <span style={{ fontWeight: 700, marginRight: 4 }}>今日计划:</span>
          <span style={{
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {plan.highlights.join(' | ')}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {plan.hasUnresolvedRisk && (
            <span style={{
              padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
              background: '#ffffff33', color: TEXT_1,
              animation: 'pulse 2s infinite',
            }}>
              {'\u26A0\uFE0F'} 风险待处理
            </span>
          )}
          <span style={{ fontSize: 12, color: plan.hasUnresolvedRisk ? '#ffffff88' : TEXT_3 }}>
            {expanded ? '\u25B2' : '\u25BC'}
          </span>
        </div>
      </div>

      {/* 展开的摘要面板 */}
      {expanded && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0,
          background: BG_EXPAND, borderBottom: `2px solid ${BRAND}`,
          padding: '12px 16px',
          maxHeight: 360, overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}>
          {plan.sections.map((section, idx) => (
            <div key={idx} style={{ marginBottom: idx < plan.sections.length - 1 ? 12 : 0 }}>
              <div style={{
                fontSize: 13, fontWeight: 700, color: BRAND,
                display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4,
              }}>
                <span>{section.icon}</span>
                <span>{section.title}</span>
              </div>
              {section.items.map((item, i) => (
                <div key={i} style={{
                  fontSize: 12, color: TEXT_2, padding: '3px 0 3px 24px',
                  borderLeft: `2px solid ${
                    section.title === '\u98CE\u9669\u9884\u8B66' ? RED :
                    section.title === '\u7D27\u6025\u91C7\u8D2D' ? YELLOW : '#1a2a33'
                  }`,
                  marginLeft: 8,
                }}>
                  {item}
                </div>
              ))}
            </div>
          ))}

          {/* 跳转管理端提示 */}
          <div style={{
            marginTop: 12, paddingTop: 10, borderTop: '1px solid #1a2a33',
            fontSize: 11, color: TEXT_3, textAlign: 'center',
          }}>
            详细审批请前往管理后台 \u2192 每日计划
          </div>
        </div>
      )}

      {/* CSS 动画 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
    </div>
  );
}
