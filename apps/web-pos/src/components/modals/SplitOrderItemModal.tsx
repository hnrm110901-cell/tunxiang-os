import { useState } from 'react';
import { txColors } from '@tx/tokens';

/**
 * 多人合点拆单弹层 — 改 OrderItem 的 share_count (PRD-11 sub-C / W12).
 *
 * 业务场景:
 *   收银员在徐记海鲜场景下, 当客人 "这个酸菜鱼三个人分" 时, 用本 modal 把
 *   OrderItem.share_count 改为 3, 后端 (tx-trade PUT /cashier/orders/{id}/items/{itemId})
 *   会校验 share_split_rules (allow_share / max_share_count) 并在 settle 时 emit
 *   ITEMS_SETTLED 让 tx-supply 触发 BOM 物理扣料 + cost attribution 切分.
 *
 * 错误处理:
 *   - 后端 422 (规则禁用 / 超 max_share_count / 单人下不可拆) → 显示后端 error message
 *   - 网络 / 其他错误 → 由调用方 toast 兜底, 本组件透传 message
 */

export interface SplitOrderItemModalProps {
  visible: boolean;
  dishName: string;
  currentShareCount: number;
  /** 异步提交; 抛出 Error 时 modal 显示 message, 成功后调用方负责关闭 */
  onSubmit: (shareCount: number) => Promise<void>;
  onClose: () => void;
  /** 后端 share_split_rules 配置的 max_share_count (UI 防超上限). 缺省 20 (硬上限) */
  maxShareCount?: number;
}

export function SplitOrderItemModal({
  visible,
  dishName,
  currentShareCount,
  onSubmit,
  onClose,
  maxShareCount = 20,
}: SplitOrderItemModalProps) {
  const [shareCount, setShareCount] = useState<number>(
    Math.max(1, currentShareCount || 1),
  );
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!visible) return null;

  const handleConfirm = async () => {
    if (submitting) return;
    if (shareCount < 1 || shareCount > maxShareCount) {
      setErrorMsg(`拆分人数必须在 1 到 ${maxShareCount} 之间`);
      return;
    }
    setErrorMsg(null);
    setSubmitting(true);
    try {
      await onSubmit(shareCount);
      // 成功不本地关闭, 由调用方判断 (一般 onSubmit 内 onClose + refetch)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '拆单提交失败';
      setErrorMsg(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    if (submitting) return;
    setErrorMsg(null);
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-label="多人合点拆单"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          width: 380,
          background: '#112228',
          borderRadius: 12,
          padding: 24,
          border: `2px solid ${txColors.primary}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>👥</span>
          <h3 style={{ margin: 0, color: txColors.primary }}>多人合点拆单</h3>
        </div>

        <div
          style={{
            fontSize: 16,
            color: '#ccc',
            lineHeight: 1.8,
            marginBottom: 16,
          }}
        >
          <div>
            菜品: <b style={{ color: txColors.primary }}>{dishName}</b>
          </div>
          <div>
            当前拆分人数: <b>{currentShareCount}</b>
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label htmlFor="split-share-count" style={{ fontSize: 16, color: '#999' }}>
            新拆分人数（1-{maxShareCount}）
          </label>
          <input
            id="split-share-count"
            type="number"
            min={1}
            max={maxShareCount}
            value={shareCount}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (Number.isNaN(v)) {
                setShareCount(1);
              } else {
                setShareCount(v);
              }
            }}
            disabled={submitting}
            aria-label="拆分人数"
            style={{
              width: '100%',
              padding: 12,
              marginTop: 4,
              borderRadius: 6,
              border: '1px solid #333',
              background: '#0B1A20',
              color: '#fff',
              fontSize: 16,
              minHeight: 48,
            }}
          />
        </div>

        {errorMsg && (
          <div
            role="alert"
            style={{
              marginBottom: 12,
              padding: '10px 12px',
              borderRadius: 6,
              background: 'rgba(235,87,87,0.1)',
              border: '1px solid rgba(235,87,87,0.4)',
              color: '#ff4d4f',
              fontSize: 16,
            }}
          >
            {errorMsg}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            style={{
              flex: 1,
              padding: 14,
              minHeight: 48,
              fontSize: 16,
              background: '#333',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.5 : 1,
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            style={{
              flex: 1,
              padding: 14,
              minHeight: 48,
              fontSize: 16,
              background: txColors.primary,
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {submitting ? '提交中...' : '确认拆单'}
          </button>
        </div>
      </div>
    </div>
  );
}
