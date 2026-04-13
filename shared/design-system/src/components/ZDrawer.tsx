import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import styles from './ZDrawer.module.css';

interface ZDrawerProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}

export default function ZDrawer({ open, onClose, title, children, footer, width }: ZDrawerProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Prevent body scroll while open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <>
      <div className={styles.overlay} onClick={onClose} />
      <div className={styles.drawer} style={width ? { width } : undefined}>
        {title && (
          <div className={styles.header}>
            <div className={styles.title}>{title}</div>
            <button className={styles.closeBtn} onClick={onClose} aria-label="关闭">✕</button>
          </div>
        )}
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </>,
    document.body,
  );
}
