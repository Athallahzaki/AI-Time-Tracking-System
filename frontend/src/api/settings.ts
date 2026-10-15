import { currentUsername } from '@/composables/useAuth';
import { request } from './http';
import { addAudit, clone, db, localDateString, save } from './mock/db';
import type {
  BreakHoursSettings,
  EmailConfig,
  EngineScheduleSettings,
  SettingsAuditEntry,
  WeeklyRanges,
} from './types';
import { DAY_KEYS } from './types';

// Setiap pengaturan adalah domain terpisah, karena BE kemungkinan membuatnya satu per satu.

function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return localDateString(d);
}

function hhmmToMinutes(value: string): number {
  const [h, m] = value.split(':').map(Number);
  return h * 60 + m;
}

/** Hitung status jadwal engine saat ini dari data mingguan (dipakai mock). */
function computeEngineNow(schedule: EngineScheduleSettings): Pick<EngineScheduleSettings, 'now_active' | 'next_change_at'> {
  const now = new Date();
  const dayIndex = (now.getDay() + 6) % 7; // Senin = 0
  const today = schedule.days[DAY_KEYS[dayIndex]];
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (!today?.enabled) return { now_active: false, next_change_at: null };
  const start = hhmmToMinutes(today.start);
  const end = hhmmToMinutes(today.end);
  if (minutes < start) return { now_active: false, next_change_at: today.start };
  if (minutes < end) return { now_active: true, next_change_at: today.end };
  return { now_active: false, next_change_at: null };
}

export async function getBreakHours(): Promise<BreakHoursSettings> {
  return request<BreakHoursSettings>({
    domain: 'break-hours',
    path: '/api/settings/break-hours',
    mock: () => {
      const store = db();
      // Jadwal tertunda yang tanggal berlakunya sudah tiba menjadi jadwal aktif.
      if (store.breakHours.pending && store.breakHours.pending.effective_from <= localDateString()) {
        store.breakHours.current = store.breakHours.pending;
        store.breakHours.pending = null;
        save();
      }
      return clone(store.breakHours);
    },
  });
}

/** Simpan jam istirahat. Dok. 12 §3.3: berlaku mulai HARI BERIKUTNYA. */
export async function saveBreakHours(days: WeeklyRanges): Promise<BreakHoursSettings> {
  return request<BreakHoursSettings>({
    domain: 'break-hours',
    method: 'PUT',
    path: '/api/settings/break-hours',
    body: { days },
    mock: () => {
      const store = db();
      const before = store.breakHours.pending?.days ?? store.breakHours.current.days;
      store.breakHours.pending = { effective_from: tomorrow(), days: clone(days) };
      save();
      addAudit(currentUsername(), 'Jam istirahat resmi', before, days);
      return clone(store.breakHours);
    },
  });
}

export async function cancelPendingBreakHours(): Promise<BreakHoursSettings> {
  return request<BreakHoursSettings>({
    domain: 'break-hours',
    method: 'DELETE',
    path: '/api/settings/break-hours/pending',
    mock: () => {
      const store = db();
      if (store.breakHours.pending) {
        addAudit(currentUsername(), 'Jam istirahat resmi (batal jadwal tertunda)', store.breakHours.pending.days, store.breakHours.current.days);
      }
      store.breakHours.pending = null;
      save();
      return clone(store.breakHours);
    },
  });
}

export async function getEngineSchedule(): Promise<EngineScheduleSettings> {
  return request<EngineScheduleSettings>({
    domain: 'engine-schedule',
    path: '/api/settings/engine-schedule',
    mock: () => {
      const schedule = clone(db().engineSchedule);
      return { ...schedule, ...computeEngineNow(schedule) };
    },
  });
}

export async function saveEngineSchedule(days: EngineScheduleSettings['days']): Promise<EngineScheduleSettings> {
  return request<EngineScheduleSettings>({
    domain: 'engine-schedule',
    method: 'PUT',
    path: '/api/settings/engine-schedule',
    body: { days },
    mock: () => {
      const store = db();
      addAudit(currentUsername(), 'Jadwal operasional engine', store.engineSchedule.days, days);
      store.engineSchedule.days = clone(days);
      save();
      const schedule = clone(store.engineSchedule);
      return { ...schedule, ...computeEngineNow(schedule) };
    },
  });
}

// GET /api/settings/email SUDAH ADA tetapi bentuknya {email: status SMTP}. Konfigurasi
// rekap memakai path terpisah supaya tidak bentrok dengan endpoint lama.
export async function getEmailConfig(): Promise<EmailConfig> {
  return request<EmailConfig>({
    domain: 'email-config',
    path: '/api/settings/email/recap',
    mock: () => clone(db().email),
  });
}

export async function saveEmailConfig(
  config: Pick<EmailConfig, 'recap_recipients' | 'recap_send_time'>,
): Promise<EmailConfig> {
  return request<EmailConfig>({
    domain: 'email-config',
    method: 'PUT',
    path: '/api/settings/email/recap',
    body: config,
    mock: () => {
      const store = db();
      addAudit(
        currentUsername(),
        'Email rekap harian',
        { penerima: store.email.recap_recipients, jam: store.email.recap_send_time },
        { penerima: config.recap_recipients, jam: config.recap_send_time },
      );
      store.email.recap_recipients = [...config.recap_recipients];
      store.email.recap_send_time = config.recap_send_time;
      save();
      return clone(store.email);
    },
  });
}

export async function getSettingsAudit(limit = 50): Promise<SettingsAuditEntry[]> {
  const res = await request<{ items: SettingsAuditEntry[] }>({
    domain: 'settings-audit',
    path: `/api/settings/audit?limit=${limit}`,
    mock: () => ({ items: clone(db().audit.slice(0, limit)) }),
  });
  return res.items || [];
}
