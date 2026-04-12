import React, { useState, useEffect, useCallback, useMemo } from 'react';
import styles from './SpecSheet.module.css';
import { formatPrice } from '../../utils/formatPrice';
import { cn } from '../../utils/cn';
import type { SpecSheetProps, SpecGroup } from './types';

/**
 * SpecSheet - 规格选择底部上滑面板
 *
 * 美团/饿了么风格 bottom sheet，支持单选/多选规格组，
 * 自动计算加价，数量调节，加入购物车确认。
 */
export default function SpecSheet({
  visible,
  dishName,
  dishPriceFen,
  dishImage,
  specGroups,
  initialQuantity = 1,
  onConfirm,
  onClose,
}: SpecSheetProps) {
  // ── State ────────────────────────────────────────────────────────────────────

  const [selections, setSelections] = useState<Record<string, string[]>>({});
  const [quantity, setQuantity] = useState(initialQuantity);

  // Reset state when sheet opens
  useEffect(() => {
    if (visible) {
      setQuantity(initialQuantity);
      // Initialize with empty selections
      const initial: Record<string, string[]> = {};
      for (const group of specGroups) {
        initial[group.id] = [];
      }
      setSelections(initial);
    }
  }, [visible, initialQuantity, specGroups]);

  // ── Selection handlers ───────────────────────────────────────────────────────

  const handleOptionToggle = useCallback(
    (group: SpecGroup, optionId: string) => {
      setSelections((prev) => {
        const current = prev[group.id] ?? [];

        if (group.type === 'single') {
          // Radio: toggle off if already selected, otherwise set
          return {
            ...prev,
            [group.id]: current.includes(optionId) ? [] : [optionId],
          };
        }

        // Checkbox: toggle in/out
        if (current.includes(optionId)) {
          return {
            ...prev,
            [group.id]: current.filter((id) => id !== optionId),
          };
        }
        return {
          ...prev,
          [group.id]: [...current, optionId],
        };
      });
    },
    [],
  );

  // ── Price calculation ────────────────────────────────────────────────────────

  const extraFen = useMemo(() => {
    let total = 0;
    for (const group of specGroups) {
      const selected = selections[group.id] ?? [];
      for (const opt of group.options) {
        if (selected.includes(opt.id) && opt.extraPriceFen) {
          total += opt.extraPriceFen;
        }
      }
    }
    return total;
  }, [specGroups, selections]);

  const unitPriceFen = dishPriceFen + extraFen;
  const totalPriceFen = unitPriceFen * quantity;

  // ── Confirm ──────────────────────────────────────────────────────────────────

  const handleConfirm = useCallback(() => {
    onConfirm(selections, quantity);
  }, [selections, quantity, onConfirm]);

  // ── Quantity ─────────────────────────────────────────────────────────────────

  const decrement = useCallback(() => {
    setQuantity((q) => Math.max(1, q - 1));
  }, []);

  const increment = useCallback(() => {
    setQuantity((q) => q + 1);
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────────

  if (!visible) return null;

  return (
    <div className={styles.overlay}>
      {/* Backdrop */}
      <div className={styles.backdrop} onClick={onClose} />

      {/* Sheet */}
      <div className={styles.sheet}>
        {/* Drag handle */}
        <div className={styles.dragHandleWrap}>
          <div className={styles.dragHandle} />
        </div>

        {/* Dish header */}
        <div className={styles.dishHeader}>
          {dishImage && (
            <img
              className={styles.dishImage}
              src={dishImage}
              alt={dishName}
            />
          )}
          <div className={styles.dishInfo}>
            <div className={styles.dishName}>{dishName}</div>
            <div className={styles.dishPrice}>{formatPrice(dishPriceFen)}</div>
          </div>
        </div>

        <div className={styles.divider} />

        {/* Spec groups */}
        <div className={styles.groupList}>
          {specGroups.map((group) => (
            <div key={group.id} className={styles.group}>
              <div className={styles.groupName}>
                {group.name}
                {group.required && (
                  <span className={styles.requiredTag}>必选</span>
                )}
              </div>
              <div className={styles.optionList}>
                {group.options.map((opt) => {
                  const selected = (selections[group.id] ?? []).includes(opt.id);
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      className={cn(
                        styles.optionPill,
                        selected && styles.selected,
                      )}
                      onClick={() => handleOptionToggle(group, opt.id)}
                    >
                      {opt.label}
                      {opt.extraPriceFen != null && opt.extraPriceFen > 0 && (
                        <span className={styles.extraPrice}>
                          +{formatPrice(opt.extraPriceFen)}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className={styles.divider} />

        {/* Quantity row */}
        <div className={styles.quantityRow}>
          <span className={styles.quantityLabel}>数量</span>
          <div className={styles.quantityControls}>
            <button
              type="button"
              className={cn(styles.quantityBtn, 'tx-pressable')}
              disabled={quantity <= 1}
              onClick={decrement}
            >
              -
            </button>
            <span className={styles.quantityValue}>{quantity}</span>
            <button
              type="button"
              className={cn(styles.quantityBtn, 'tx-pressable')}
              onClick={increment}
            >
              +
            </button>
          </div>
        </div>

        {/* Confirm button */}
        <div className={styles.confirmWrap}>
          <button
            type="button"
            className={cn(styles.confirmBtn, 'tx-pressable')}
            onClick={handleConfirm}
          >
            加入购物车 {formatPrice(totalPriceFen)}
          </button>
        </div>
      </div>
    </div>
  );
}
