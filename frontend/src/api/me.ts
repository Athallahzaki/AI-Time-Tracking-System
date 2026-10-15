import { apiFetch } from '@/composables/useAuth';
import { request } from './http';
import { localDateString } from './mock/db';
import { MOCK_ALLOWANCE_SECONDS, statusFor, usageFor } from './mock/usage';
import type { MyUsageToday, UsageStatus } from './types';

/**
 * Pemakaian free time milik viewer yang sedang login (dok. 12 §3.2).
 *
 * Urutan sumber:
 *  1. GET /api/me/usage-today (usulan; BE menentukan karyawan dari sesi).
 *  2. Bila belum ada: GET /api/attendance/break-usage?person_id=<ID karyawan>
 *     yang SUDAH ADA di backend — data nyata, tapi penyaringannya masih
 *     mengandalkan parameter, jadi belum aman untuk produksi (dok. 12 §3.8).
 *  3. Bila itu pun gagal: angka simulasi.
 */

function mapStatus(raw: unknown, used: number, allowance: number): UsageStatus {
  const text = String(raw || '').toLowerCase();
  if (['exceeded', 'limit', 'violation', 'over'].includes(text)) return 'exceeded';
  if (['warning', 'near_limit'].includes(text)) return 'warning';
  if (['ok', 'safe', 'normal'].includes(text)) return 'safe';
  return statusFor(used, allowance);
}

async function fromBreakUsage(employeeId: string, name: string): Promise<MyUsageToday | null> {
  try {
    const res = await apiFetch(`/api/attendance/break-usage?person_id=${encodeURIComponent(employeeId)}`);
    if (!res.ok) return null;
    const body = await res.json();
    const allowance = Math.round(Number(body.allowance_minutes || 0) * 60);
    const used = Math.round(Number(body.used_minutes || 0) * 60);
    const byCamera = new Map<string, number>();
    let first: string | null = null;
    for (const b of body.breaks || []) {
      const key = String(b.camera_id || 'Lainnya');
      byCamera.set(key, (byCamera.get(key) || 0) + Number(b.duration_seconds || 0));
      if (b.start_at && (!first || b.start_at < first)) first = b.start_at;
    }
    return {
      date: body.date || localDateString(),
      employee_id: employeeId,
      name,
      used_seconds: used,
      allowance_seconds: allowance,
      remaining_seconds: Math.max(0, Math.round(Number(body.remaining_minutes || 0) * 60)),
      status: mapStatus(body.status, used, allowance),
      by_location: [...byCamera.entries()].map(([location, seconds]) => ({ location, seconds })),
      visits: Number(body.break_count || 0),
      first_seen_at: first,
    };
  } catch {
    return null;
  }
}

function simulated(employeeId: string, name: string): MyUsageToday {
  const date = localDateString();
  const u = usageFor(
    {
      uid: employeeId,
      employee_id: employeeId,
      name,
      division: null,
      email: null,
      active: true,
      enrolled_refs: 0,
      has_account: true,
      created_at: 0,
    },
    date,
  );
  return {
    date,
    employee_id: employeeId,
    name,
    used_seconds: u.used,
    allowance_seconds: MOCK_ALLOWANCE_SECONDS,
    remaining_seconds: Math.max(0, MOCK_ALLOWANCE_SECONDS - u.used),
    status: statusFor(u.used, MOCK_ALLOWANCE_SECONDS),
    by_location: u.byLocation,
    visits: u.visits,
    first_seen_at: u.firstSeen,
  };
}

export async function getMyUsageToday(employeeId: string, name: string): Promise<MyUsageToday> {
  return request<MyUsageToday>({
    domain: 'me',
    path: '/api/me/usage-today',
    mock: async () => (await fromBreakUsage(employeeId, name)) ?? simulated(employeeId, name),
  });
}
