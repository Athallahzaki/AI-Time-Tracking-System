import type {
  AppUser,
  BreakHoursSettings,
  DayKey,
  EmailConfig,
  Employee,
  EngineScheduleSettings,
  ReviewStatus,
  SettingsAuditEntry,
  WeeklyRanges,
} from '../types';
import { DAY_KEYS } from '../types';

/**
 * Basis data tiruan di browser. Dipakai HANYA selama endpoint backend belum ada
 * (lihat src/api/http.ts). Disimpan di localStorage supaya data demo tidak hilang
 * saat refresh; hapus dengan resetMockDb() atau dari menu Pengaturan > Data simulasi.
 */

const STORAGE_KEY = 'ai-time-tracking.mock-db.v1';

export interface MockDb {
  employees: Employee[];
  users: AppUser[];
  breakHours: BreakHoursSettings;
  engineSchedule: EngineScheduleSettings;
  email: EmailConfig;
  audit: SettingsAuditEntry[];
  reviewDecisions: Record<
    string,
    { status: ReviewStatus; by: string; at: number; note: string | null }
  >;
  nextUserId: number;
}

function weekly(fn: (day: DayKey) => WeeklyRanges[DayKey]): WeeklyRanges {
  return Object.fromEntries(DAY_KEYS.map((d) => [d, fn(d)])) as WeeklyRanges;
}

export function localDateString(date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const SEED_EMPLOYEES: Array<[string, string, string | null, string | null]> = [
  ['EMP001', 'Andi Pratama', 'Produksi', 'andi.pratama@example.com'],
  ['EMP002', 'Budi Santoso', 'Produksi', null],
  ['EMP003', 'Citra Lestari', 'Keuangan', 'citra.lestari@example.com'],
  ['EMP004', 'Dewi Anggraini', 'HR', 'dewi.anggraini@example.com'],
  ['EMP005', 'Eko Saputra', 'Gudang', null],
  ['EMP006', 'Fajar Nugroho', 'IT', 'fajar.nugroho@example.com'],
  ['EMP007', 'Gita Permata', 'Marketing', 'gita.permata@example.com'],
  ['EMP008', 'Hendra Wijaya', 'Gudang', 'hendra.wijaya@example.com'],
  ['EMP009', 'Indah Sari', 'Keuangan', null],
  ['EMP010', 'Joko Susilo', 'Produksi', 'joko.susilo@example.com'],
];

function seed(): MockDb {
  const now = Date.now() / 1000;
  const today = localDateString();
  return {
    employees: SEED_EMPLOYEES.map(([employee_id, name, division, email], i) => ({
      uid: uuid(),
      employee_id,
      name,
      division,
      email,
      active: i !== 8,
      enrolled_refs: i < 6 ? 5 : 0,
      has_account: i < 2,
      created_at: now - (30 - i) * 86400,
    })),
    users: [
      { id: 1, username: 'admin', role: 'admin', enabled: true, created_at: now - 40 * 86400 },
      {
        id: 2,
        username: 'EMP001',
        role: 'viewer',
        enabled: true,
        created_at: now - 10 * 86400,
        employee_id: 'EMP001',
      },
      {
        id: 3,
        username: 'EMP002',
        role: 'viewer',
        enabled: true,
        created_at: now - 9 * 86400,
        employee_id: 'EMP002',
        must_change_password: true,
      },
    ],
    breakHours: {
      current: {
        effective_from: today,
        days: weekly((d) =>
          d === 'sat' || d === 'sun'
            ? []
            : d === 'fri'
              ? [{ start: '11:30', end: '13:00' }]
              : [{ start: '12:00', end: '13:00' }],
        ),
      },
      pending: null,
    },
    engineSchedule: {
      days: Object.fromEntries(
        DAY_KEYS.map((d) => [
          d,
          d === 'sun'
            ? { enabled: false, start: '07:00', end: '18:00' }
            : { enabled: true, start: d === 'sat' ? '08:00' : '07:00', end: d === 'sat' ? '14:00' : '18:00' },
        ]),
      ) as EngineScheduleSettings['days'],
    },
    email: {
      recap_recipients: ['hr@example.com'],
      recap_send_time: '18:30',
      default_from_env: ['hr@example.com'],
    },
    audit: [],
    reviewDecisions: {},
    nextUserId: 4,
  };
}

let cache: MockDb | null = null;

export function db(): MockDb {
  if (cache) return cache;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      cache = JSON.parse(raw) as MockDb;
      return cache;
    }
  } catch {
    // localStorage tidak tersedia: tetap di memori
  }
  cache = seed();
  save();
  return cache;
}

export function save(): void {
  try {
    if (cache) localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // abaikan
  }
}

export function resetMockDb(): void {
  cache = seed();
  save();
}

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function addAudit(actor: string, setting: string, oldValue: unknown, newValue: unknown) {
  const store = db();
  store.audit.unshift({
    id: uuid(),
    at: Date.now() / 1000,
    actor,
    setting,
    old_value: typeof oldValue === 'string' ? oldValue : JSON.stringify(oldValue),
    new_value: typeof newValue === 'string' ? newValue : JSON.stringify(newValue),
  });
  store.audit = store.audit.slice(0, 200);
  save();
}

/** Password sementara yang gampang dibaca (tanpa 0/O/1/l). */
export function generateTempPassword(length = 10): string {
  const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789';
  const bytes = new Uint32Array(length);
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) crypto.getRandomValues(bytes);
  else for (let i = 0; i < length; i++) bytes[i] = Math.floor(Math.random() * 2 ** 32);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
}
