const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1/forge';

export async function forgeApi<T = any>(path: string, options?: RequestInit): Promise<T> {
  const tenantId = localStorage.getItem('tenant_id') || 'demo-tenant';
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': tenantId,
      ...options?.headers,
    },
    ...options,
  });
  if (!res.ok) throw new Error(`API Error: ${res.status}`);
  return res.json();
}
