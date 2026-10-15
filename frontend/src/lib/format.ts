import type { IdentitySource, UsageStatus } from '@/api/types';

/** 1830 → "30m 30d"; 45 → "45d"; 3725 → "1j 2m". */
export function formatDuration(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `${s}d`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = s % 60;
  if (h > 0) return `${h}j ${m}m`;
  return rest ? `${m}m ${rest}d` : `${m}m`;
}

/** Menit dengan satu desimal, untuk tabel dan Excel. */
export function toMinutes(seconds: number | null | undefined): number {
  return Math.round(((Number(seconds) || 0) / 60) * 10) / 10;
}

export function formatDate(date: string | null | undefined): string {
  if (!date) return '-';
  const d = new Date(date.length === 10 ? `${date}T00:00:00` : date);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString('id-ID', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
}

export function formatTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-';
  const d = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
}

export function formatDateTime(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return '-';
  return new Date(epochSeconds * 1000).toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const STATUS_META: Record<UsageStatus, { label: string; class: string; bar: string }> = {
  safe: { label: 'Aman', class: 'bg-emerald-50 text-emerald-700 border-emerald-200', bar: 'bg-emerald-500' },
  warning: { label: 'Peringatan', class: 'bg-amber-50 text-amber-700 border-amber-200', bar: 'bg-amber-500' },
  exceeded: { label: 'Lewat batas', class: 'bg-red-50 text-red-700 border-red-200', bar: 'bg-red-500' },
};

export const IDENTITY_SOURCE_META: Record<string, { label: string; short: string; hint: string; class: string }> = {
  face: {
    label: 'Wajah',
    short: 'Wajah',
    hint: 'Dikenali langsung dari wajah',
    class: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  tracking: {
    label: 'Pelacakan',
    short: 'Lacak',
    hint: 'Lanjutan track dari wajah yang sama',
    class: 'bg-sky-50 text-sky-700 border-sky-200',
  },
  reid: {
    label: 'ReID',
    short: 'ReID',
    hint: 'Disambung lewat penampilan tubuh — perlu dicek bila dominan',
    class: 'bg-violet-50 text-violet-700 border-violet-200',
  },
  reid_retro: {
    label: 'ReID (mundur)',
    short: 'ReID↺',
    hint: 'Waktu sebelum wajah terlihat, diatribusikan setelah wajah dikonfirmasi',
    class: 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200',
  },
};

export function identitySourceMeta(source: IdentitySource | null | undefined) {
  if (!source) return null;
  return (
    IDENTITY_SOURCE_META[source] ?? {
      label: String(source),
      short: String(source),
      hint: 'Sumber identitas lain (belum dikenal frontend)',
      class: 'bg-slate-50 text-slate-600 border-slate-200',
    }
  );
}

export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}
