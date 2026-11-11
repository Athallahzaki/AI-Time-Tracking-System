// Panel debug admin (Fase 1). Backend hanya mendaftarkan rute ini bila
// DEBUG_PANEL_ENABLED diisi; bila tidak, `request` melempar NotImplementedApiError.
import { request } from './http';

const DOMAIN = 'debug';

export interface DebugCamera {
  camera_id: string;
  state: 'online' | 'degraded' | 'failed';
  metrics: Record<string, number>;
  per_minute: Record<string, number>;
  last_event: { type: string; at: number; reason: string | null } | null;
}

export interface DebugHealth {
  engine_connected: boolean;
  last_event_seq: number | null;
  health_age_seconds: number | null;
  window_seconds: number;
  engine: Record<string, unknown>;
  cameras: DebugCamera[];
  identity_metrics: Record<string, number>;
  identity_per_minute: Record<string, number>;
}

export interface DebugLogEntry {
  ts: number;
  source: 'backend' | 'frontend';
  level: string;
  logger: string;
  message: string;
  url?: string;
}

export function getDebugHealth(): Promise<DebugHealth> {
  return request<DebugHealth>({ domain: DOMAIN, path: '/api/debug/health' });
}

export async function getDebugLogs(source: string, minLevel: string): Promise<DebugLogEntry[]> {
  const query = new URLSearchParams({ min_level: minLevel, limit: '300' });
  if (source) query.set('source', source);
  const res = await request<{ logs: DebugLogEntry[] }>({ domain: DOMAIN, path: `/api/debug/logs?${query}` });
  return res.logs || [];
}

/** Rekaman kesehatan satu rentang (epoch detik) sebagai CSV berformat lag_probe. */
export async function downloadHealthCsv(from: number, to: number): Promise<Blob> {
  const res = await request<Response>({
    domain: DOMAIN,
    path: `/api/debug/health.csv?from=${from}&to=${to}`,
    raw: true,
  });
  return res.blob();
}

let reported = 0;
const MAX_REPORTS_PER_PAGE = 20; // galat berulang tidak boleh membanjiri backend

/** Laporkan galat browser ke panel debug. Tidak pernah melempar dan tidak pernah melaporkan dirinya sendiri. */
export function reportClientError(message: unknown, level: 'ERROR' | 'WARNING' = 'ERROR'): void {
  if (reported >= MAX_REPORTS_PER_PAGE) return;
  reported += 1;
  const text = (message instanceof Error ? `${message.name}: ${message.message}` : String(message)).slice(0, 2000);
  request({
    domain: DOMAIN,
    method: 'POST',
    path: '/api/debug/client-log',
    body: { level, message: text || 'galat tanpa pesan', url: window.location.pathname.slice(0, 500) },
  }).catch(() => {
    /* panel mati, belum login, atau jaringan putus: abaikan */
  });
}
