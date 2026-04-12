import React from 'react';
import styles from './ZSkeleton.module.css';

interface ZSkeletonProps {
  /** 展示几行文字骨架 */
  lines?: number;
  /** 展示一个高方块（如图表占位） */
  block?: boolean;
  /** 展示头像行（圆形 + 文字） */
  avatar?: boolean;
  /** 头像尺寸 */
  avatarSize?: number;
  /** 重复 rows 次（列表场景） */
  rows?: number;
  /** 兼容旧调用：直接指定占位高度 */
  height?: number;
  style?: React.CSSProperties;
}

function SkeletonUnit({ lines, block, avatar, avatarSize, height }: Omit<ZSkeletonProps, 'rows' | 'style'>) {
  if (height != null) {
    return <div className={`${styles.base} ${styles.block}`} style={{ height }} />;
  }
  if (block) {
    return <div className={`${styles.base} ${styles.block}`} />;
  }
  if (avatar) {
    const size = avatarSize ?? 40;
    return (
      <div className={styles.row}>
        <div className={`${styles.base} ${styles.avatar}`} style={{ width: size, height: size }} />
        <div className={styles.rowLines}>
          <div className={`${styles.base} ${styles.line}`} style={{ width: '55%' }} />
          <div className={`${styles.base} ${styles.line}`} style={{ width: '35%' }} />
        </div>
      </div>
    );
  }
  return (
    <div className={styles.wrap}>
      {Array.from({ length: lines ?? 3 }).map((_, i) => (
        <div key={i} className={`${styles.base} ${styles.line}`} />
      ))}
    </div>
  );
}

export default function ZSkeleton({ rows = 1, style, ...rest }: ZSkeletonProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, ...style }}>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonUnit key={i} {...rest} />
      ))}
    </div>
  );
}
