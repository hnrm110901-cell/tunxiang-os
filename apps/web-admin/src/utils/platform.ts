/**
 * 平台检测 — V3 域名架构
 *
 * hub.tunxiangos.com → 屯象运维（跨商户，IP白名单）
 * os.tunxiangos.com  → 商家端（RLS隔离）
 * localhost          → 开发模式
 */

export type PlatformMode = 'hub' | 'os' | 'dev';

export function detectPlatform(): PlatformMode {
  const hostname = window.location.hostname;
  if (hostname.startsWith('hub.')) return 'hub';
  if (hostname.startsWith('os.')) return 'os';
  return 'dev'; // localhost 开发模式默认为 OS
}

export function isHub(): boolean {
  return detectPlatform() === 'hub';
}

export function isOS(): boolean {
  return detectPlatform() !== 'hub';
}

export function getPlatformLabel(): string {
  const mode = detectPlatform();
  return mode === 'hub' ? '屯象OS · 运维中心' : '屯象OS · 商家管理';
}

/**
 * Hub 模式下可以切换查看不同商户
 * OS 模式下 tenant_id 固定（登录时确定）
 */
export function canSwitchTenant(): boolean {
  return detectPlatform() === 'hub';
}

/**
 * Hub 模式下的 API 基础 URL（不走 RLS，用 platform-admin token）
 * OS 模式下的 API 基础 URL（走 RLS，用商户 token）
 */
export function getApiBase(): string {
  return import.meta.env.VITE_API_BASE_URL || '';
}
