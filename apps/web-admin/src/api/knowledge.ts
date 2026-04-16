/**
 * 知识库管理 API 客户端
 */

const API_BASE = '/api/v1/knowledge';

interface DocumentListParams {
  tenant_id: string;
  collection?: string;
  status?: string;
  page?: number;
  size?: number;
}

interface SearchParams {
  query: string;
  collection: string;
  tenant_id: string;
  top_k?: number;
  filters?: Record<string, string>;
  rerank?: boolean;
}

export const knowledgeApi = {
  listDocuments: async (params: DocumentListParams) => {
    const qs = new URLSearchParams(params as unknown as Record<string, string>);
    const resp = await fetch(`${API_BASE}/documents?${qs}`);
    return resp.json();
  },

  getDocument: async (id: string, tenantId: string) => {
    const resp = await fetch(`${API_BASE}/documents/${id}?tenant_id=${tenantId}`);
    return resp.json();
  },

  uploadDocument: async (formData: FormData) => {
    const resp = await fetch(`${API_BASE}/documents`, {
      method: 'POST',
      body: formData,
    });
    return resp.json();
  },

  deleteDocument: async (id: string, tenantId: string) => {
    const resp = await fetch(`${API_BASE}/documents/${id}?tenant_id=${tenantId}`, {
      method: 'DELETE',
    });
    return resp.json();
  },

  searchKnowledge: async (params: SearchParams) => {
    const resp = await fetch(`${API_BASE}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    return resp.json();
  },

  publishDocument: async (id: string, tenantId: string) => {
    const resp = await fetch(`${API_BASE}/documents/${id}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenant_id: tenantId }),
    });
    return resp.json();
  },
};
