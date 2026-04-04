/**
 * KDSStatBar — 出餐统计顶栏
 *
 * 4格横排：待出餐 / 已完成 / 平均出餐时间 / 超时单数
 * 背景 #1E2A3A，高72px
 * overtime>0 时超时格显示红色字体+浅红背景
 * 30秒自动刷新（通过父组件传入 stats，刷新逻辑在父组件）
 */

interface KDSStatBarProps {
  stats: {
    pending: number;
    completed: number;
    avgTimeMinutes: number;
    overtime: number;
  };
}

export function KDSStatBar({ stats }: KDSStatBarProps) {
  const { pending, completed, avgTimeMinutes, overtime } = stats;

  return (
    <>
      {/* keyframes 只注入一次即可，放在最外层 */}
      <style>{`
        @keyframes kds-stat-blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>

      <div
        style={{
          display: 'flex',
          height: 72,
          background: '#1E2A3A',
          borderBottom: '2px solid #0F1C2A',
          flexShrink: 0,
        }}
      >
        {/* 待出餐 */}
        <StatCell
          label="待出餐"
          value={pending}
          unit="单"
          valueColor="#BA7517"
        />

        <StatDivider />

        {/* 已完成 */}
        <StatCell
          label="今日已完成"
          value={completed}
          unit="单"
          valueColor="#0F6E56"
        />

        <StatDivider />

        {/* 平均出餐时间 */}
        <StatCell
          label="平均出餐"
          value={avgTimeMinutes}
          unit="分钟"
          valueColor="#E0E0E0"
        />

        <StatDivider />

        {/* 超时单数 */}
        <StatCell
          label="超时单"
          value={overtime}
          unit="单"
          valueColor={overtime > 0 ? '#FF4444' : '#666'}
          highlight={overtime > 0}
          blinking={overtime > 0}
        />
      </div>
    </>
  );
}

// ─── 单格 ───

function StatCell({
  label,
  value,
  unit,
  valueColor,
  highlight = false,
  blinking = false,
}: {
  label: string;
  value: number;
  unit: string;
  valueColor: string;
  highlight?: boolean;
  blinking?: boolean;
}) {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: highlight ? 'rgba(163,45,45,0.15)' : 'transparent',
        transition: 'background 0.3s ease',
        animation: blinking ? 'kds-stat-blink 1.5s infinite' : undefined,
      }}
    >
      <span
        style={{
          fontSize: 16,
          color: '#8A9BB0',
          lineHeight: 1.2,
          letterSpacing: 1,
        }}
      >
        {label}
      </span>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 3 }}>
        <span
          style={{
            fontSize: 28,
            fontWeight: 'bold',
            color: valueColor,
            fontFamily: 'JetBrains Mono, monospace',
            lineHeight: 1.1,
          }}
        >
          {value}
        </span>
        <span style={{ fontSize: 16, color: '#8A9BB0' }}>{unit}</span>
      </div>
    </div>
  );
}

// ─── 分隔线 ───

function StatDivider() {
  return (
    <div
      style={{
        width: 1,
        margin: '14px 0',
        background: '#2C3E50',
      }}
    />
  );
}
