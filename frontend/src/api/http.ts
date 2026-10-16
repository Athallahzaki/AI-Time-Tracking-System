import { reactive } from 'vue';
import { apiFetch } from '@/composables/useAuth';

/**
 * Lapisan HTTP untuk fitur dokumen 12 (data karyawan, pengaturan baru, report,
 * antrean tinjauan, tampilan viewer).
 *
 * Banyak endpoint ini BELUM dibuat di backend. Supaya frontend bisa dibangun dan
 * didemokan lebih dulu, setiap "domain" punya pengganti (mock) di src/api/mock/.
 *
 * Aturan pemilihan sumber data (VITE_API_MODE):
 *   - "auto"  (bawaan) : coba backend dulu. Kalau route-nya belum ada (FastAPI
 *                        menjawab 404 {"detail":"Not Found"} atau 405), domain itu
 *                        dipindah ke mock untuk sisa sesi. Kalau panggilan PERTAMA
 *                        di domain itu berhasil, domain dikunci ke backend dan
 *                        endpoint lain yang belum ada di domain yang sama
 *                        menghasilkan error jelas (tidak dicampur data palsu).
 *   - "mock"           : selalu mock (demo tanpa backend).
 *   - "real"           : tidak pernah mock.
 *
 * Status per domain bisa dibaca dari `apiSources` untuk menampilkan banner
 * "data simulasi" di halaman.
 */

export type ApiMode = 'auto' | 'mock' | 'real';
export type SourceState = 'unknown' | 'real' | 'mock';

const RAW_MODE = String(import.meta.env.VITE_API_MODE || 'auto').toLowerCase();
export const API_MODE: ApiMode =
  RAW_MODE === 'mock' || RAW_MODE === 'real' ? RAW_MODE : 'auto';

export const apiSources = reactive<Record<string, SourceState>>({});

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

/** Error khusus: endpoint belum ada di backend padahal domainnya sudah nyata. */
export class NotImplementedApiError extends ApiError {
  constructor(method: string, path: string) {
    super(
      `Endpoint ${method} ${path} belum tersedia di backend. Fitur ini menunggu BE.`,
      501,
    );
  }
}

interface RequestOptions<T> {
  /** Nama domain untuk keputusan real/mock, mis. "employees". */
  domain: string;
  method?: string;
  path: string;
  body?: unknown;
  /** Pengganti saat backend belum punya route ini. */
  mock?: () => T | Promise<T>;
  /** Kembalikan Response mentah (untuk unduhan file). */
  raw?: boolean;
}

async function isRouteMissing(res: Response): Promise<boolean> {
  if (res.status === 405 || res.status === 501) return true;
  if (res.status !== 404) return false;
  // FastAPI untuk route yang tidak terdaftar: {"detail": "Not Found"}.
  // 404 dari HTTPException aplikasi biasanya punya pesan lain.
  try {
    const body = await res.clone().json();
    return body?.detail === 'Not Found';
  } catch {
    return true;
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail)) {
      // Error validasi pydantic: ambil pesan pertama yang terbaca.
      message = detail
        .map((d: any) => `${(d?.loc || []).slice(1).join('.')}: ${d?.msg}`)
        .join('; ');
    }
  } catch {
    // badan bukan JSON
  }
  if (res.status === 401) message = 'Sesi habis. Silakan masuk lagi.';
  if (res.status === 403) message = 'Akses ditolak untuk peran Anda.';
  return new ApiError(message, res.status);
}

async function useMock<T>(domain: string, mock: () => T | Promise<T>): Promise<T> {
  apiSources[domain] = 'mock';
  // Sedikit jeda supaya status "memuat" di UI tetap terlihat realistis.
  await new Promise((r) => setTimeout(r, 120));
  return mock();
}

export async function request<T = any>(opts: RequestOptions<T>): Promise<T> {
  const method = (opts.method || 'GET').toUpperCase();
  const state = apiSources[opts.domain] ?? 'unknown';

  if (opts.mock && (API_MODE === 'mock' || state === 'mock')) {
    return useMock(opts.domain, opts.mock);
  }

  let res: Response;
  try {
    res = await apiFetch(opts.path, {
      method,
      headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (err) {
    // Backend tidak terjangkau sama sekali.
    if (opts.mock && API_MODE === 'auto' && state !== 'real') {
      return useMock(opts.domain, opts.mock);
    }
    throw new ApiError('Backend tidak dapat dihubungi.', 0);
  }

  if (!res.ok && (await isRouteMissing(res))) {
    if (opts.mock && API_MODE === 'auto' && state !== 'real') {
      return useMock(opts.domain, opts.mock);
    }
    throw new NotImplementedApiError(method, opts.path.split('?')[0]);
  }

  if (!res.ok) throw await errorFrom(res);

  if (apiSources[opts.domain] !== 'mock') apiSources[opts.domain] = 'real';
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Bangun query string, melewati nilai kosong. */
export function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}
