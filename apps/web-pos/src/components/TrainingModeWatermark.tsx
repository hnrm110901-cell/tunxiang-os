/**
 * TrainingModeWatermark — 演示模式半透明全屏水印
 *
 * 在演示模式激活时，在整个应用右下角叠加半透明水印文字。
 * 使用 pointer-events: none 确保不干扰触控操作。
 *
 * 编码规范：TypeScript strict，纯 inline style，Store终端规范
 */

interface TrainingModeWatermarkProps {
  /** 水印文字，来自后端配置（默认"演示模式"） */
  text?: string;
}

/**
 * 注入水印旋转动画的 style 标签（只注入一次）
 */
function ensureWatermarkStyle(): void {
  const STYLE_ID = 'tx-training-watermark-style';
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    @keyframes tx-watermark-fade {
      0%, 100% { opacity: 0.12; }
      50% { opacity: 0.2; }
    }
  `;
  document.head.appendChild(style);
}

export function TrainingModeWatermark({ text = '演示模式' }: TrainingModeWatermarkProps) {
  // 注入动画样式
  ensureWatermarkStyle();

  return (
    <div
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9997,
        pointerEvents: 'none',
        overflow: 'hidden',
        userSelect: 'none',
        WebkitUserSelect: 'none',
      }}
    >
      {/* 右下角大水印 */}
      <div
        style={{
          position: 'absolute',
          right: 24,
          bottom: 24,
          color: '#D97706',
          fontSize: 48,
          fontWeight: 900,
          letterSpacing: 8,
          transform: 'rotate(-20deg)',
          transformOrigin: 'right bottom',
          animation: 'tx-watermark-fade 3s ease-in-out infinite',
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
          whiteSpace: 'nowrap',
        }}
      >
        {text}
      </div>

      {/* 全屏平铺水印（较小字体，多行重复）*/}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexWrap: 'wrap',
          alignContent: 'flex-start',
          gap: 0,
          opacity: 0.045,
        }}
      >
        {Array.from({ length: 40 }).map((_, i) => (
          <div
            key={i}
            style={{
              width: '25%',
              padding: '32px 0',
              textAlign: 'center',
              color: '#D97706',
              fontSize: 20,
              fontWeight: 700,
              transform: 'rotate(-20deg)',
              letterSpacing: 4,
              fontFamily: 'inherit',
              whiteSpace: 'nowrap',
            }}
          >
            {text}
          </div>
        ))}
      </div>
    </div>
  );
}
