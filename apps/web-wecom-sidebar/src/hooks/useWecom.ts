/**
 * useWecom.ts — 企微 JS-SDK 封装
 *
 * 初始化流程：
 *   1. 调用 /api/v1/wecom/jssdk-config 获取签名
 *   2. wx.config() — 注入企业基础配置（必须先调用）
 *   3. wx.agentConfig() — 注入应用级配置（获取 getCurExternalContact 权限）
 *   4. wx.invoke('getCurExternalContact') — 获取当前客户 externalUserId
 *
 * 注意：企微侧边栏中，jwxwork-1.2.0.js 已在 index.html 中通过 <script> 同步加载，
 * 因此 window.wx 在此 hook 执行时已存在。
 */
import { useState, useEffect } from 'react';
import { fetchJssdkConfig } from '../api/memberApi';

// 企微 JS-SDK 全局变量类型声明
declare const wx: {
  config(params: WxConfigParams): void;
  agentConfig(params: WxAgentConfigParams): void;
  invoke(
    api: string,
    params: Record<string, unknown>,
    callback: (res: { err_msg: string; userId?: string }) => void,
  ): void;
  ready(callback: () => void): void;
  error(callback: (err: { errMsg: string }) => void): void;
};

interface WxConfigParams {
  beta: boolean;
  debug: boolean;
  appId: string;
  timestamp: number;
  nonceStr: string;
  signature: string;
  jsApiList: string[];
}

interface WxAgentConfigParams {
  corpid: string;
  agentid: string;
  timestamp: number;
  nonceStr: string;
  signature: string;
  jsApiList: string[];
  success: () => void;
  fail: (err: { errMsg: string }) => void;
}

export interface UseWecomResult {
  externalUserId: string | null;
  error: string | null;
  loading: boolean;
}

export function useWecom(): UseWecomResult {
  const [externalUserId, setExternalUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function initWecom(): Promise<void> {
      // 1. 获取 JS-SDK 签名配置（含 agentConfig 签名）
      const pageUrl = window.location.href.split('#')[0];
      const config = await fetchJssdkConfig(pageUrl);

      if (cancelled) return;

      // 2. wx.config — 企业基础鉴权（必须先于 agentConfig）
      await new Promise<void>((resolve, reject) => {
        wx.config({
          beta: true,       // 必须设 true，才能启用企微非公开 API
          debug: false,
          appId: config.appId,
          timestamp: config.timestamp,
          nonceStr: config.nonceStr,
          signature: config.signature,
          jsApiList: [],    // 基础配置无需声明具体 API
        });

        wx.ready(() => resolve());
        wx.error((err) => reject(new Error(`wx.config 失败: ${err.errMsg}`)));
      });

      if (cancelled) return;

      // 3. wx.agentConfig — 应用级鉴权，声明 getCurExternalContact 权限
      await new Promise<void>((resolve, reject) => {
        wx.agentConfig({
          corpid: config.appId,
          agentid: config.agentId,
          timestamp: config.timestamp,
          nonceStr: config.nonceStr,
          signature: config.agentSignature,
          jsApiList: ['getCurExternalContact'],
          success: () => resolve(),
          fail: (err) => reject(new Error(`wx.agentConfig 失败: ${err.errMsg}`)),
        });
      });

      if (cancelled) return;

      // 4. 获取当前客户 externalUserId
      await new Promise<void>((resolve, reject) => {
        wx.invoke(
          'getCurExternalContact',
          {},
          (res) => {
            if (res.err_msg === 'getCurExternalContact:ok' && res.userId) {
              setExternalUserId(res.userId);
              resolve();
            } else {
              reject(new Error(`获取客户 ID 失败: ${res.err_msg}`));
            }
          },
        );
      });
    }

    initWecom()
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : '企微初始化失败';
          setError(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { externalUserId, error, loading };
}
