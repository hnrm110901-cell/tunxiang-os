/**
 * 微服务端点配置
 * 所有服务的 base URL 统一在此管理，方便按环境切换
 */

const envBase = import.meta.env.VITE_API_BASE_URL || '';

/**
 * 当 VITE_API_BASE_URL 配置了网关地址时，所有请求通过网关路由，
 * 各服务 base URL 都指向同一个网关。
 * 当未配置时，本地开发按端口直连各服务。
 */
export const SERVICES = {
  gateway:   envBase || 'http://localhost:8000',
  trade:     envBase || 'http://localhost:8001',
  menu:      envBase || 'http://localhost:8002',
  member:    envBase || 'http://localhost:8003',
  growth:    envBase || 'http://localhost:8004',
  ops:       envBase || 'http://localhost:8005',
  supply:    envBase || 'http://localhost:8006',
  finance:   envBase || 'http://localhost:8007',
  agent:     envBase || 'http://localhost:8008',
  analytics: envBase || 'http://localhost:8009',
  brain:     envBase || 'http://localhost:8010',
  intel:     envBase || 'http://localhost:8011',
  org:       envBase || 'http://localhost:8012',
} as const;

export type ServiceName = keyof typeof SERVICES;
