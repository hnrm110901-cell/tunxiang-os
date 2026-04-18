/**
 * web-pos 前端 Feature Flags
 * 统一 key 命名：<domain>.<module>.<feature>
 * 默认值：开发环境开启。生产由后端 /api/v1/flags 下发覆盖（后续 Sprint 接入）。
 */

export type FlagKey =
  | 'trade.pos.settle.hardening'
  | 'trade.pos.toast.enable'
  | 'trade.pos.errorBoundary.enable';

const DEFAULTS: Record<FlagKey, boolean> = {
  'trade.pos.settle.hardening': true,
  'trade.pos.toast.enable': true,
  'trade.pos.errorBoundary.enable': true,
};

const overrides: Partial<Record<FlagKey, boolean>> = {};

export function isEnabled(key: FlagKey): boolean {
  if (key in overrides) return overrides[key] as boolean;
  return DEFAULTS[key];
}

export function setFlagOverride(key: FlagKey, value: boolean): void {
  overrides[key] = value;
}

export function resetFlagOverrides(): void {
  (Object.keys(overrides) as FlagKey[]).forEach((k) => delete overrides[k]);
}
