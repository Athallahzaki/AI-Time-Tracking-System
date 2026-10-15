// Tipe data fitur dokumen 12. Bentuknya mengikuti usulan kontrak di
// docs/README-PLAN-FE-FITUR-DOK12.md §4 — BE diharapkan memakai nama field yang sama.

export interface Employee {
  /** Kunci internal tetap (tidak berubah walau ID karyawan diedit). */
  uid: string;
  /** ID karyawan yang terlihat HR; boleh diedit. */
  employee_id: string;
  name: string;
  division: string | null;
  email: string | null;
  active: boolean;
  enrolled_refs: number;
  has_account: boolean;
  created_at: number;
}

export interface EmployeeInput {
  employee_id: string;
  name: string;
  division?: string | null;
  email?: string | null;
}

export interface AccountCredentials {
  username: string;
  temporary_password: string;
}

export interface AppUser {
  id: number;
  username: string;
  role: 'admin' | 'viewer' | string;
  enabled: boolean;
  created_at: number;
  employee_uid?: string | null;
  employee_id?: string | null;
  must_change_password?: boolean;
}

export type DayKey = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun';
export const DAY_KEYS: DayKey[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
export const DAY_LABELS: Record<DayKey, string> = {
  mon: 'Senin',
  tue: 'Selasa',
  wed: 'Rabu',
  thu: 'Kamis',
  fri: 'Jumat',
  sat: 'Sabtu',
  sun: 'Minggu',
};

export interface TimeRange {
  start: string; // "HH:MM"
  end: string;
}

export type WeeklyRanges = Record<DayKey, TimeRange[]>;

export interface BreakHoursSettings {
  current: { effective_from: string; days: WeeklyRanges };
  pending: { effective_from: string; days: WeeklyRanges } | null;
}

export interface EngineDaySchedule {
  enabled: boolean;
  start: string;
  end: string;
}

export interface EngineScheduleSettings {
  days: Record<DayKey, EngineDaySchedule>;
  now_active?: boolean;
  next_change_at?: string | null;
}

export interface EmailConfig {
  recap_recipients: string[];
  recap_send_time: string;
  default_from_env: string[];
}

export interface SettingsAuditEntry {
  id: string;
  at: number;
  actor: string;
  setting: string;
  old_value: string;
  new_value: string;
}

export type UsageStatus = 'safe' | 'warning' | 'exceeded';

export interface LocationUsage {
  location: string;
  seconds: number;
}

export interface ReportRow {
  date: string;
  employee_uid: string;
  employee_id: string;
  name: string;
  division: string | null;
  used_seconds: number;
  allowance_seconds: number;
  remaining_seconds: number;
  visits: number;
  status: UsageStatus;
  reid_seconds: number;
  needs_review: boolean;
  first_seen_at: string | null;
  by_location: LocationUsage[];
}

export interface ReportSummary {
  employees: number;
  rows: number;
  exceeded: number;
  warning: number;
  avg_used_seconds: number;
  needs_review: number;
}

export interface ReportResponse {
  summary: ReportSummary;
  items: ReportRow[];
  total: number;
}

export type IdentitySource = 'face' | 'tracking' | 'reid' | 'reid_retro' | string;

export interface VisitSegment {
  visit_id: string;
  camera_id: string;
  location: string;
  start: string; // ISO
  end: string | null;
  seconds: number;
  identity_source: IdentitySource;
}

export interface ReportFilters {
  from: string;
  to: string;
  division?: string;
  employee_uid?: string;
  status?: UsageStatus | '';
}

export type ReviewStatus = 'pending' | 'confirmed' | 'rejected';

export interface ReviewItem {
  id: string;
  date: string;
  employee_uid: string;
  employee_id: string;
  name: string;
  used_seconds: number;
  allowance_seconds: number;
  reid_seconds: number;
  visits: number;
  status: ReviewStatus;
  decided_by?: string | null;
  decided_at?: number | null;
  note?: string | null;
}

export interface ReviewDetail extends ReviewItem {
  segments: VisitSegment[];
}

export interface MyUsageToday {
  date: string;
  employee_id: string;
  name: string;
  used_seconds: number;
  allowance_seconds: number;
  remaining_seconds: number;
  status: UsageStatus;
  by_location: LocationUsage[];
  visits: number;
  first_seen_at: string | null;
}
