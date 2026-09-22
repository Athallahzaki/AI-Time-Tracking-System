import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';

/**
 * Tipe-tipe di bawah ini disalin PERSIS dari schemas/attendance.py backend
 * (field snake_case dipertahankan apa adanya, sesuai konvensi Pydantic yang
 * sudah dipakai di endpoint lain seperti track_id, person_id).
 */

export type GapClassification =
  | 'tracking_loss'
  | 'break'
  | 'departure'
  | 'camera_failure'
  | 'system_event'
  | 'official_break'
  | 'unknown';

export interface BreakEntry {
  gap_id: string;
  start_at: string;
  end_at: string;
  duration_seconds: number;
  camera_id: string;
  end_zone: string;
  end_reason: string;
  corrected: boolean;
  original_duration_seconds?: number;
}

export interface BreakUsage {
  person_id: string;
  date: string;
  allowance_minutes: number;
  used_minutes: number;
  remaining_minutes: number;
  break_count: number;
  breaks: BreakEntry[];
  suspicious_gap_count: number;
  status: 'ok' | 'warning' | 'exceeded';
}

/**
 * ENDPOINT INI BELUM ADA DI BACKEND.
 *
 * schemas/attendance.py sudah punya BreakUsage, tapi routers/attendance.py
 * yang saya lihat baru: /active, /corrections, /events, /summary — belum ada
 * yang mengembalikan BreakUsage.
 *
 * Usulan untuk backend (kecil, karena logikanya di session_deriver.py /
 * break_policy.py sudah ada — tinggal dibungkus jadi route):
 *
 *   GET /api/attendance/breaks?date=YYYY-MM-DD
 *   → { "status": "success", "data": BreakUsage[] }
 *
 * Sampai endpoint ini ada, composable akan menampilkan status error apa
 * adanya — BUKAN data rekaan. Sistem ini jadi dasar sanksi karyawan; angka
 * palsu yang terlihat asli lebih berbahaya daripada layar "gagal memuat".
 */
const BREAKS_ENDPOINT = '/api/attendance/breaks';

const usages = reactive<BreakUsage[]>([]);
const employeeNames = reactive<Record<string, string>>({});

export function getEmployeeName(personId: string): string {
  return employeeNames[personId] || personId;
}

/**
 * Peringkat status untuk sorting — orang yang paling butuh perhatian HR
 * (exceeded) ditaruh paling atas, memakai status yang SUDAH DIHITUNG backend,
 * bukan ambang batas yang saya tebak sendiri seperti sebelumnya.
 */
const STATUS_RANK: Record<BreakUsage['status'], number> = {
  exceeded: 0,
  warning: 1,
  ok: 2,
};

export function useEmployeeAllowance() {
  const isLoading = ref(false);
  const loadError = ref<string | null>(null);
  const lastFetchedAt = ref<Date | null>(null);

  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let activeClientsCount = 0;

  async function fetchEmployeeNames() {
    try {
      const res = await fetch('/api/enrollments');
      if (!res.ok) return;
      const json = await res.json();
      // Bentuk pasti /api/enrollments belum saya lihat — jaga-jaga dua kemungkinan bentuk.
      const list: any[] = Array.isArray(json?.enrollments)
        ? json.enrollments
        : Array.isArray(json?.data)
        ? json.data
        : Array.isArray(json)
          ? json
          : [];
      list.forEach((item) => {
        if (item?.person_id) {
          employeeNames[item.person_id] = item.name || item.person_id;
        }
      });
    } catch {
      // Nama tinggal fallback ke person_id kalau ini gagal — bukan data kritis.
    }
  }

  async function fetchAllowanceData() {
    isLoading.value = usages.length === 0;
    try {
      const today = new Date().toISOString().slice(0, 10);
      const res = await fetch(`${BREAKS_ENDPOINT}?date=${today}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.status === 'success' && Array.isArray(json.data)) {
        usages.splice(0, usages.length, ...json.data);
        loadError.value = null;
        lastFetchedAt.value = new Date();
      } else {
        throw new Error('Bentuk respons tidak sesuai skema BreakUsage');
      }
    } catch (err: any) {
      // Sengaja tidak fallback ke data palsu — lihat komentar di atas BREAKS_ENDPOINT.
      loadError.value = err?.message || 'Gagal memuat data jatah istirahat';
    } finally {
      isLoading.value = false;
    }
  }

  onMounted(() => {
    activeClientsCount++;
    fetchEmployeeNames();
    fetchAllowanceData();
    if (!pollTimer) {
      pollTimer = setInterval(fetchAllowanceData, 10000);
    }
  });

  onUnmounted(() => {
    activeClientsCount--;
    if (activeClientsCount <= 0 && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  });

  const sortedUsages = computed(() =>
    [...usages].sort((a, b) => {
      const rankDiff = STATUS_RANK[a.status] - STATUS_RANK[b.status];
      if (rankDiff !== 0) return rankDiff;
      return a.remaining_minutes - b.remaining_minutes;
    })
  );

  return {
    usages,
    sortedUsages,
    isLoading,
    loadError,
    lastFetchedAt,
    refetch: fetchAllowanceData,
    getEmployeeName,
  };
}
