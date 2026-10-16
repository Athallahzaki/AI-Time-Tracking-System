import type {
  Employee,
  IdentitySource,
  LocationUsage,
  ReportRow,
  UsageStatus,
  VisitSegment,
} from '../types';
import { localDateString } from './db';

/**
 * Generator pemakaian free time tiruan yang DETERMINISTIK: karyawan + tanggal yang
 * sama selalu menghasilkan angka yang sama, jadi report, antrean tinjauan, dan
 * tampilan viewer saling konsisten selama mode simulasi.
 */

export const MOCK_ALLOWANCE_SECONDS = 30 * 60;
export const MOCK_WARNING_REMAINING_SECONDS = 5 * 60;

const LOCATIONS = [
  { id: 'cam-hiburan', name: 'Ruang Hiburan' },
  { id: 'cam-biliar', name: 'Ruang Biliar' },
  { id: 'cam-smoking', name: 'Smoking Area' },
];

function hashString(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function rng(seed: number) {
  let s = seed || 1;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return ((s >>> 0) % 1_000_000) / 1_000_000;
  };
}

export function statusFor(used: number, allowance: number): UsageStatus {
  if (used > allowance) return 'exceeded';
  if (allowance - used <= MOCK_WARNING_REMAINING_SECONDS) return 'warning';
  return 'safe';
}

function dayFraction(date: string): number {
  // Hari ini baru terisi sebagian sesuai jam sekarang; hari lalu penuh.
  const today = localDateString();
  if (date < today) return 1;
  if (date > today) return 0;
  const now = new Date();
  const hours = now.getHours() + now.getMinutes() / 60;
  return Math.max(0, Math.min(1, (hours - 7) / 10));
}

interface DayUsage {
  used: number;
  reid: number;
  visits: number;
  byLocation: LocationUsage[];
  segments: VisitSegment[];
  firstSeen: string | null;
}

export function usageFor(employee: Employee, date: string): DayUsage {
  const empty: DayUsage = { used: 0, reid: 0, visits: 0, byLocation: [], segments: [], firstSeen: null };
  const weekday = new Date(`${date}T00:00:00`).getDay();
  if (weekday === 0 || !employee.active) return empty;

  const rand = rng(hashString(`${employee.employee_id}|${date}`));
  const fraction = dayFraction(date);
  if (fraction <= 0) return empty;

  // Kebanyakan aman, sebagian dekat batas, sebagian kecil melewati batas.
  const roll = rand();
  const fullDayMinutes = roll < 0.6 ? 5 + rand() * 18 : roll < 0.85 ? 24 + rand() * 6 : 31 + rand() * 20;
  const visitCount = 1 + Math.floor(rand() * 5);
  const reidShare = rand() < 0.25 ? 0.5 + rand() * 0.4 : rand() * 0.3;

  const segments: VisitSegment[] = [];
  let totalSeconds = 0;
  let reidSeconds = 0;
  const workStart = 8 * 3600;
  const span = 9 * 3600;
  const cutoff = workStart + span * fraction;

  for (let i = 0; i < visitCount; i++) {
    const start = workStart + (span / visitCount) * i + rand() * (span / visitCount) * 0.5;
    if (start > cutoff) break;
    const seconds = Math.round(((fullDayMinutes * 60) / visitCount) * (0.6 + rand() * 0.8));
    const loc = LOCATIONS[Math.floor(rand() * LOCATIONS.length)];
    const sourceRoll = rand();
    let source: IdentitySource = 'face';
    if (sourceRoll < reidShare * 0.6) source = 'reid';
    else if (sourceRoll < reidShare) source = 'reid_retro';
    else if (sourceRoll < reidShare + 0.25) source = 'tracking';
    const startDate = new Date(`${date}T00:00:00`);
    startDate.setSeconds(start);
    const endDate = new Date(startDate.getTime() + seconds * 1000);
    segments.push({
      visit_id: `v-${employee.employee_id}-${date}-${i}`,
      camera_id: loc.id,
      location: loc.name,
      start: startDate.toISOString(),
      end: endDate.toISOString(),
      seconds,
      identity_source: source,
    });
    totalSeconds += seconds;
    if (source === 'reid' || source === 'reid_retro') reidSeconds += seconds;
  }

  const byLocationMap = new Map<string, number>();
  for (const s of segments) byLocationMap.set(s.location, (byLocationMap.get(s.location) || 0) + s.seconds);

  const firstSeen = segments.length ? new Date(new Date(segments[0].start).getTime() - (20 + rand() * 60) * 60_000) : null;

  return {
    used: totalSeconds,
    reid: reidSeconds,
    visits: segments.length,
    byLocation: [...byLocationMap.entries()].map(([location, seconds]) => ({ location, seconds })),
    segments,
    firstSeen: firstSeen ? firstSeen.toISOString() : null,
  };
}

export function reportRowFor(employee: Employee, date: string): ReportRow {
  const u = usageFor(employee, date);
  const status = statusFor(u.used, MOCK_ALLOWANCE_SECONDS);
  return {
    date,
    employee_uid: employee.uid,
    employee_id: employee.employee_id,
    name: employee.name,
    division: employee.division,
    used_seconds: u.used,
    allowance_seconds: MOCK_ALLOWANCE_SECONDS,
    remaining_seconds: Math.max(0, MOCK_ALLOWANCE_SECONDS - u.used),
    visits: u.visits,
    status,
    reid_seconds: u.reid,
    needs_review: status === 'exceeded' && u.used > 0 && u.reid / u.used > 0.5,
    first_seen_at: u.firstSeen,
    by_location: u.byLocation,
  };
}

export function datesBetween(from: string, to: string): string[] {
  const out: string[] = [];
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return out;
  for (let d = start; d <= end && out.length < 366; d.setDate(d.getDate() + 1)) {
    out.push(localDateString(d));
  }
  return out;
}
