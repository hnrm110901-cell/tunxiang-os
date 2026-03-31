/**
 * useAllergenCheck — 点单时实时检查菜品是否触发会员过敏/忌口
 *
 * 用法：
 *   const { checkDish, pendingAlerts, clearAlerts } = useAllergenCheck(memberId);
 *
 *   // 点击添加菜品时：
 *   const alerts = await checkDish(dishId, dishName);
 *   if (alerts.length > 0) {
 *     // 显示 AllergenAlertModal
 *   } else {
 *     // 直接添加
 *   }
 *
 * 注意：
 *   - 无 memberId 时直接返回空数组（未识别会员，不做检查）
 *   - API 调用失败时静默处理，返回空数组（不阻塞点单流程）
 */
import { useState, useCallback } from 'react';
import { checkAllergens } from '../api/allergenApi';
import type { AllergenAlert } from '../api/allergenApi';

export interface PendingAlerts {
  dishId: string;
  dishName: string;
  alerts: AllergenAlert[];
}

export function useAllergenCheck(memberId: string | null) {
  const [pendingAlerts, setPendingAlerts] = useState<PendingAlerts | null>(null);

  /**
   * 检查单个菜品是否触发过敏/忌口。
   * 有预警时同时更新 pendingAlerts 状态（供弹窗消费）。
   * 返回 AllergenAlert[]，空数组表示安全。
   */
  const checkDish = useCallback(
    async (dishId: string, dishName: string): Promise<AllergenAlert[]> => {
      if (!memberId) return [];

      try {
        const results = await checkAllergens(
          [dishId],
          memberId,
          { [dishId]: dishName },
        );

        if (results.length === 0) return [];

        const dishResult = results.find(r => r.dish_id === dishId);
        if (!dishResult || dishResult.alerts.length === 0) return [];

        setPendingAlerts({
          dishId,
          dishName,
          alerts: dishResult.alerts,
        });
        return dishResult.alerts;
      } catch {
        // 食安提醒是增强功能，API 失败不阻塞点单主流程
        return [];
      }
    },
    [memberId],
  );

  /** 清除待处理的过敏预警（弹窗关闭后调用） */
  const clearAlerts = useCallback(() => {
    setPendingAlerts(null);
  }, []);

  return {
    checkDish,
    pendingAlerts,
    clearAlerts,
  };
}
