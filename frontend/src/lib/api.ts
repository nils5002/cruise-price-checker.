import type {
  AdminError,
  AdminStatus,
  Alert,
  CruiseDetailPayload,
  CruiseOverview,
  HistoryPoint,
  Meta,
  ParsedUrl,
  Scan,
  ScanDetail,
  ScanOptions,
} from '../types';

const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api';
const API_KEY_STORAGE = 'cpc.apiKey';

export function getApiKey(): string {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE) ?? '';
  } catch {
    return '';
  }
}

export function setApiKey(value: string): void {
  try {
    if (value) window.localStorage.setItem(API_KEY_STORAGE, value);
    else window.localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    /* storage may be unavailable */
  }
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (init?.body) headers['Content-Type'] = 'application/json';
  const key = getApiKey();
  if (key) headers['X-API-Key'] = key;

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    if (payload && typeof payload === 'object' && 'detail' in payload) {
      const raw = (payload as { detail: unknown }).detail;
      if (typeof raw === 'string') detail = raw;
      else if (Array.isArray(raw) && raw.length > 0) detail = JSON.stringify(raw[0]);
    } else if (typeof payload === 'string' && payload) {
      detail = payload;
    }
    throw new ApiError(detail, response.status);
  }
  return payload as T;
}

export function artifactUrl(path: string): string {
  return `${API_BASE}/artifacts/${path.split('/').map(encodeURIComponent).join('/')}`;
}

export const api = {
  meta: () => request<Meta>('/meta'),
  parseUrl: (url: string) => request<ParsedUrl>('/parse-url', { method: 'POST', body: JSON.stringify({ url }) }),
  cruises: () => request<CruiseOverview[]>('/cruises'),
  cruise: (id: number) => request<CruiseDetailPayload>(`/cruises/${id}`),
  createCruise: (payload: { url: string; start_scan: boolean; schedule_interval: string; options: ScanOptions }) =>
    request<{ cruise: { id: number }; scan_id: number | null; warning: string | null }>('/cruises', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateCruise: (id: number, payload: Record<string, unknown>) =>
    request<CruiseOverview>(`/cruises/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteCruise: (id: number) => request<void>(`/cruises/${id}`, { method: 'DELETE' }),
  history: (id: number) => request<HistoryPoint[]>(`/cruises/${id}/history`),
  startScan: (id: number, options: ScanOptions) =>
    request<Scan>(`/cruises/${id}/scans`, { method: 'POST', body: JSON.stringify(options) }),
  scan: (id: number) => request<ScanDetail>(`/scans/${id}`),
  scans: (cruiseId?: number) => request<Scan[]>(`/scans${cruiseId ? `?cruise_id=${cruiseId}` : ''}`),
  alerts: (cruiseId: number) => request<Alert[]>(`/cruises/${cruiseId}/alerts`),
  createAlert: (cruiseId: number, payload: Record<string, unknown>) =>
    request<Alert>(`/cruises/${cruiseId}/alerts`, { method: 'POST', body: JSON.stringify(payload) }),
  deleteAlert: (id: number) => request<void>(`/alerts/${id}`, { method: 'DELETE' }),
  testAlert: (id: number) => request<{ sent: boolean; detail: string }>(`/alerts/${id}/test`, { method: 'POST' }),
  adminStatus: () => request<AdminStatus>('/admin/status'),
  adminErrors: () => request<AdminError[]>('/admin/errors'),
  adminDebug: (scanId: number) => request<Record<string, unknown>>(`/admin/debug/scan/${scanId}`),
  resetProfile: (key: string) =>
    request<{ profile: string; reset: boolean; detail: string }>(`/admin/profiles/${key}/reset`, { method: 'POST' }),
};
