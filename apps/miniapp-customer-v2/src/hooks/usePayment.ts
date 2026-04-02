/**
 * usePayment — WeChat Pay integration
 *
 * Flow:
 *   POST /api/v1/orders/{id}/pay { method, ...extraParams }
 *   → { prepay_id, timeStamp, nonceStr, package, signType, paySign } for wechat pay
 *   → Taro.requestPayment({ ... })
 *   → POST /api/v1/orders/{id}/pay-confirm on success
 *
 * For 'stored_value' and 'mixed' methods the backend confirms the payment
 * directly; no Taro.requestPayment call is needed.
 */

import { useState, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { txRequest, TxRequestError } from '../utils/request'

// ─── Types ────────────────────────────────────────────────────────────────────

export type PaymentMethod = 'wechat' | 'stored_value' | 'mixed'

export interface PayResult {
  success: boolean
  orderId: string
  method: PaymentMethod
  /** Populated when success=false */
  errorCode?: string
  errorMessage?: string
}

/** Shape returned by the backend for wechat pay */
interface WechatPrepayResponse {
  prepay_id: string
  timeStamp: string
  nonceStr: string
  package: string
  signType: 'MD5' | 'HMAC-SHA256' | 'RSA'
  paySign: string
}

/** Generic pay endpoint response envelope */
interface PayInitResponse {
  /** Present when method === 'wechat' */
  wechat?: WechatPrepayResponse
  /** True when backend already confirmed (stored_value / mixed) */
  confirmed?: boolean
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function usePayment() {
  const [isProcessing, setIsProcessing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const pay = useCallback(
    async (
      orderId: string,
      method: PaymentMethod,
      extraParams?: Record<string, unknown>,
    ): Promise<PayResult> => {
      setIsProcessing(true)
      setError(null)

      try {
        // ── Step 1: Initiate payment with backend ──────────────────────────
        const initData = await txRequest<PayInitResponse>(
          `/api/v1/orders/${encodeURIComponent(orderId)}/pay`,
          'POST',
          { method, ...extraParams },
        )

        // ── Step 2: Stored value / mixed — backend already confirmed ───────
        if (method === 'stored_value' || (method === 'mixed' && initData.confirmed)) {
          return { success: true, orderId, method }
        }

        // ── Step 3: WeChat Pay — call Taro.requestPayment ──────────────────
        if (method === 'wechat' || method === 'mixed') {
          const wx = initData.wechat
          if (!wx) {
            const msg = 'Backend did not return WeChat pay parameters'
            setError(msg)
            return { success: false, orderId, method, errorCode: 'MISSING_PREPAY', errorMessage: msg }
          }

          try {
            await Taro.requestPayment({
              timeStamp: wx.timeStamp,
              nonceStr: wx.nonceStr,
              package: wx.package,
              signType: wx.signType,
              paySign: wx.paySign,
            })
          } catch (payErr: unknown) {
            // WeChat Pay SDK encodes cancellation as errMsg "requestPayment:fail cancel"
            const taroMsg =
              payErr instanceof Error
                ? payErr.message
                : typeof payErr === 'object' && payErr !== null && 'errMsg' in payErr
                ? String((payErr as Record<string, unknown>).errMsg)
                : 'Payment failed'

            const isCancelled =
              taroMsg.includes('cancel') || taroMsg.includes('fail cancel')

            const code = isCancelled ? 'USER_CANCELLED' : 'WX_PAY_FAILED'
            const msg = isCancelled ? 'Payment cancelled by user' : taroMsg

            setError(msg)
            return { success: false, orderId, method, errorCode: code, errorMessage: msg }
          }

          // ── Step 4: Notify backend of successful wx pay ──────────────────
          try {
            await txRequest(
              `/api/v1/orders/${encodeURIComponent(orderId)}/pay-confirm`,
              'POST',
              { method },
            )
          } catch (confirmErr: unknown) {
            // Pay succeeded on WeChat side — still treat as success,
            // but surface a soft warning so ops can investigate if needed.
            const msg =
              confirmErr instanceof TxRequestError
                ? confirmErr.message
                : 'Order status update failed — payment was charged'
            console.warn('[usePayment] pay-confirm failed:', msg)
          }

          return { success: true, orderId, method }
        }

        // Unreachable, but keeps TS happy
        const exhaustive: never = method
        return {
          success: false,
          orderId,
          method: exhaustive,
          errorCode: 'UNSUPPORTED_METHOD',
          errorMessage: `Unsupported payment method: ${String(method)}`,
        }
      } catch (err: unknown) {
        const msg =
          err instanceof TxRequestError
            ? err.message
            : err instanceof Error
            ? err.message
            : 'An unexpected payment error occurred'

        setError(msg)

        // Surface error to user
        Taro.showToast({ title: msg, icon: 'none', duration: 2500 }).catch(() => {
          // ignore toast errors
        })

        return {
          success: false,
          orderId,
          method,
          errorCode: err instanceof TxRequestError ? err.code : 'UNKNOWN',
          errorMessage: msg,
        }
      } finally {
        setIsProcessing(false)
      }
    },
    [],
  )

  return {
    pay,
    isProcessing,
    error,
  }
}
