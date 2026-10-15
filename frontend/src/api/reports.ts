import { buildXlsx, downloadBlob } from '@/lib/xlsx';
import type { Sheet } from '@/lib/xlsx';
import { STATUS_META, IDENTITY_SOURCE_META, toMinutes } from '@/lib/format';
import { apiSources, qs, request } from './http';
import { listEmployees } from './employees';
import { datesBetween, reportRowFor, usageFor } from './mock/usage';
import type { ReportFilters, ReportResponse, ReportRow, VisitSegment } from './types';

const DOMAIN = 'reports';
/** Batas rentang per permintaan (server i5-3470 tidak perlu menghitung ulang setahun). */
export const MAX_RANGE_DAYS = 31;

function filterParams(filters: ReportFilters) {
  return {
    from: filters.from,
    to: filters.to,
    division: filters.division,
    employee_uid: filters.employee_uid,
    status: filters.status,
  };
}

async function mockRows(filters: ReportFilters): Promise<ReportRow[]> {
  const employees = await listEmployees({ status: 'all' });
  const dates = datesBetween(filters.from, filters.to).reverse();
  const rows: ReportRow[] = [];
  for (const date of dates) {
    for (const e of employees) {
      if (filters.division && e.division !== filters.division) continue;
      if (filters.employee_uid && e.uid !== filters.employee_uid) continue;
      const row = reportRowFor(e, date);
      if (row.visits === 0) continue;
      if (filters.status && row.status !== filters.status) continue;
      rows.push(row);
    }
  }
  return rows;
}

function summarize(rows: ReportRow[]): ReportResponse['summary'] {
  const used = rows.reduce((sum, r) => sum + r.used_seconds, 0);
  return {
    employees: new Set(rows.map((r) => r.employee_uid)).size,
    rows: rows.length,
    exceeded: rows.filter((r) => r.status === 'exceeded').length,
    warning: rows.filter((r) => r.status === 'warning').length,
    avg_used_seconds: rows.length ? used / rows.length : 0,
    needs_review: rows.filter((r) => r.needs_review).length,
  };
}

export async function getDailyReport(
  filters: ReportFilters,
  page = 1,
  size = 50,
): Promise<ReportResponse> {
  return request<ReportResponse>({
    domain: DOMAIN,
    path: `/api/reports/daily${qs({ ...filterParams(filters), page, size })}`,
    mock: async () => {
      const rows = await mockRows(filters);
      return {
        summary: summarize(rows),
        items: rows.slice((page - 1) * size, page * size),
        total: rows.length,
      };
    },
  });
}

export async function getVisits(employeeUid: string, date: string): Promise<VisitSegment[]> {
  const res = await request<{ items: VisitSegment[] }>({
    domain: DOMAIN,
    path: `/api/reports/daily/${encodeURIComponent(employeeUid)}/${date}/visits`,
    mock: async () => {
      const employees = await listEmployees({ status: 'all' });
      const e = employees.find((x) => x.uid === employeeUid);
      return { items: e ? usageFor(e, date).segments : [] };
    },
  });
  return res.items || [];
}

function filenameFrom(res: Response, fallback: string): string {
  const header = res.headers.get('Content-Disposition') || '';
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : fallback;
}

/** Susunan kolom sama dengan yang diharapkan dari generator BE (dok. 12 §3.5). */
function buildSheets(rows: ReportRow[]): Sheet[] {
  const rekap: Sheet = {
    name: 'Rekap Harian',
    widths: [12, 12, 26, 14, 12, 12, 10, 12, 12, 14, 18],
    rows: [
      [
        'Tanggal',
        'ID Karyawan',
        'Nama',
        'Divisi',
        'Terpakai (menit)',
        'Sisa (menit)',
        'Kunjungan',
        'Status',
        'Dari ReID (menit)',
        'Perlu dicek HR',
        'Pertama terlihat',
      ],
      ...rows.map((r) => [
        r.date,
        r.employee_id,
        r.name,
        r.division ?? '',
        toMinutes(r.used_seconds),
        toMinutes(r.remaining_seconds),
        r.visits,
        STATUS_META[r.status]?.label ?? r.status,
        toMinutes(r.reid_seconds),
        r.needs_review ? 'Ya' : '',
        r.first_seen_at ? new Date(r.first_seen_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }) : '',
      ]),
    ],
  };
  const lokasi: Sheet = {
    name: 'Rincian Lokasi',
    widths: [12, 12, 26, 18, 14],
    rows: [
      ['Tanggal', 'ID Karyawan', 'Nama', 'Lokasi', 'Menit'],
      ...rows.flatMap((r) =>
        r.by_location.map((l) => [r.date, r.employee_id, r.name, l.location, toMinutes(l.seconds)]),
      ),
    ],
  };
  const legend: Sheet = {
    name: 'Keterangan',
    widths: [18, 70],
    rows: [
      ['Istilah', 'Arti'],
      ['Terpakai', 'Waktu terlihat di area rekreasi yang memotong jatah harian'],
      ...Object.values(IDENTITY_SOURCE_META).map((m) => [`Sumber: ${m.label}`, m.hint]),
      ['Perlu dicek HR', 'Pelanggaran yang sebagian besar menitnya bersumber ReID'],
    ],
  };
  return [rekap, lokasi, legend];
}

/**
 * Export Excel. Backend (bila ada) yang membuat file; FE hanya mengunduh.
 * Selama BE belum punya generator, file dibuat di browser dari data yang sama
 * dengan tabel, dan nama file diberi akhiran "-simulasi".
 */
export async function exportReportXlsx(filters: ReportFilters): Promise<{ filename: string; generatedBy: 'backend' | 'browser' }> {
  const fallbackName = `report-free-time_${filters.from}_${filters.to}.xlsx`;
  let generatedBy: 'backend' | 'browser' = 'backend';
  const res = await request<Response | { browser: true }>({
    domain: 'reports-xlsx',
    path: `/api/reports/daily.xlsx${qs(filterParams(filters))}`,
    raw: true,
    mock: () => ({ browser: true as const }),
  });

  if (res instanceof Response) {
    const blob = await res.blob();
    const filename = filenameFrom(res, fallbackName);
    downloadBlob(blob, filename);
    return { filename, generatedBy };
  }

  generatedBy = 'browser';
  // Ambil semua baris (tanpa paginasi) dari sumber report yang sedang aktif.
  const all = await getDailyReport(filters, 1, 100_000);
  const filename = fallbackName.replace('.xlsx', apiSources[DOMAIN] === 'mock' ? '-simulasi.xlsx' : '.xlsx');
  downloadBlob(buildXlsx(buildSheets(all.items)), filename);
  return { filename, generatedBy };
}
