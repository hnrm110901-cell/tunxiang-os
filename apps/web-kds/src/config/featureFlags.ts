/**
 * web-kds 前端 Feature Flags
 * key 命名：<domain>.<module>.<feature>
 * 默认值：开发环境开启。生产由后端 /api/v1/flags 下发覆盖（C2/C3 接入）。
 */

export type FlagKey =
  | 'edge.kds.local_cache.enable';

const DEFAULTS: Record<FlagKey, boolean> = {
  'edge.kds.local_cache.enable': true,
};

const overrides: Partial<Record<FlagKey, boolean>> = {};

export function isFeatureEnabled(key: FlagKey): boolean {
  if (key in overrides) return overrides[key] as boolean;
  return DEFAULTS[key];
}

export function setFlagOverride(key: FlagKey, value: boolean): void {
  overrides[key] = value;
}

export function resetFlagOverrides(): void {
  (Object.keys(overrides) as FlagKey[]).forEach((k) => delete overrides[k]);
}
