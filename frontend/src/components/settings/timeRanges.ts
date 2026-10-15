import type { TimeRange } from '@/api/types';

/** "HH:MM" → menit sejak tengah malam; NaN bila format salah. */
export function toMinutes(value: string): number {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value || '');
  if (!match) return Number.NaN;
  const h = Number(match[1]);
  const m = Number(match[2]);
  if (h > 23 || m > 59) return Number.NaN;
  return h * 60 + m;
}

/**
 * Validasi rentang dalam SATU hari: format benar, mulai < selesai, tidak
 * tumpang tindih. Rentang melewati tengah malam belum didukung prototype.
 * Mengembalikan pesan error per indeks (string kosong = valid).
 */
export function validateRanges(ranges: TimeRange[]): string[] {
  const errors: string[] = ranges.map((r): string => {
    const start = toMinutes(r.start);
    const end = toMinutes(r.end);
    if (Number.isNaN(start) || Number.isNaN(end)) return 'Format jam harus HH:MM.';
    if (start >= end) return 'Jam selesai harus setelah jam mulai (lewat tengah malam belum didukung).';
    return '';
  });
  const order = ranges
    .map((r, i) => ({ i, start: toMinutes(r.start), end: toMinutes(r.end) }))
    .filter((r) => !errors[r.i])
    .sort((a, b) => a.start - b.start);
  for (let k = 1; k < order.length; k++) {
    if (order[k].start < order[k - 1].end) {
      errors[order[k].i] = 'Tumpang tindih dengan rentang lain di hari yang sama.';
    }
  }
  return errors;
}

export function describeRanges(ranges: TimeRange[]): string {
  return ranges.length ? ranges.map((r) => `${r.start}–${r.end}`).join(', ') : 'Tidak ada';
}
