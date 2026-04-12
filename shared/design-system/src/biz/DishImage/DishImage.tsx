/**
 * DishImage -- 菜品图片渐进加载组件
 *
 * - 加载中：灰底 shimmer 动画
 * - 加载完成：300ms crossfade 过渡
 * - 加载失败：内联 SVG 食物图标占位
 * - 支持 lazy loading + IntersectionObserver 预加载
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '../../utils/cn';
import styles from './DishImage.module.css';

type ImageState = 'loading' | 'loaded' | 'error';

export interface DishImageProps {
  src?: string;
  alt: string;
  width?: number | string;
  height?: number | string;
  aspectRatio?: string;
  className?: string;
  lazy?: boolean;
}

/** Inline SVG: simple dish/food icon placeholder */
function FoodIconPlaceholder() {
  return (
    <svg
      className={styles.errorIcon}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <ellipse cx="24" cy="34" rx="18" ry="6" fill="currentColor" opacity="0.5" />
      <path
        d="M6 34c0-9.941 8.059-18 18-18s18 8.059 18 18"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
      />
      <line x1="24" y1="8" x2="24" y2="16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="20" y1="10" x2="20" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="28" y1="10" x2="28" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export default function DishImage({
  src,
  alt,
  width,
  height,
  aspectRatio = '4/3',
  className,
  lazy = true,
}: DishImageProps) {
  const [state, setState] = useState<ImageState>(src ? 'loading' : 'error');
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Reset state when src changes
  useEffect(() => {
    setState(src ? 'loading' : 'error');
  }, [src]);

  // IntersectionObserver: eagerly preload image when 200px from viewport
  useEffect(() => {
    if (!lazy || !src || state !== 'loading') return;

    const container = containerRef.current;
    if (!container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && imgRef.current) {
            // Force load by setting src if browser hasn't started yet
            imgRef.current.src = src;
            observer.disconnect();
          }
        }
      },
      { rootMargin: '200px' },
    );

    observer.observe(container);
    return () => observer.disconnect();
  }, [lazy, src, state]);

  const handleLoad = useCallback(() => {
    setState('loaded');
  }, []);

  const handleError = useCallback(() => {
    setState('error');
  }, []);

  const containerStyle: React.CSSProperties = {
    width,
    height,
    aspectRatio,
  };

  return (
    <div
      ref={containerRef}
      className={cn(styles.container, className)}
      style={containerStyle}
    >
      {/* Placeholder layer (visible while loading or on error) */}
      {state !== 'loaded' && (
        <div className={styles.placeholder}>
          {state === 'loading' && <div className={styles.shimmer} />}
          {state === 'error' && <FoodIconPlaceholder />}
        </div>
      )}

      {/* Actual image */}
      {src && state !== 'error' && (
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          className={cn(styles.image, state === 'loaded' && styles.loaded)}
          loading={lazy ? 'lazy' : undefined}
          onLoad={handleLoad}
          onError={handleError}
        />
      )}
    </div>
  );
}
