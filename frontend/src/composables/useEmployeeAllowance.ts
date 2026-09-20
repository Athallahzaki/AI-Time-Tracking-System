import { onMounted, reactive, ref } from 'vue';

export type IntervalSource = 'face' | 'tracking' | 'forced';
export type IntervalZone = 'door' | 'interior' | 'frame_edge';
export type EndReason =
  | 'left_frame'
  | 'occluded_timeout'
  | 'merged_into_other_track'
  | 'camera_lost'
  | 'engine_shutdown'
  | 'identity_released';

export interface PresenceGap {
  interval_id: string;
  camera_id: string;
  start_at: string;
  end_at: string;
  duration_seconds: number;
  start_source: IntervalSource;
  end_source: IntervalSource;
  start_zone: IntervalZone;
  end_zone: IntervalZone;
  end_reason: EndReason;
  identity_confidence: number;
  evidence_crop?: { start?: string; end?: string };
}

export interface EmployeeAllowance {
  person_id: string;
  name: string;
  quota_minutes: number;
  used_minutes: number;
  remaining_minutes: number;
  gaps: PresenceGap[];
}

export type GapReliability = 'reliable' | 'uncertain';

export function classifyGapReliability(gap: PresenceGap): GapReliability {
  if (gap.end_zone === 'interior') return 'uncertain';
  if (gap.end_reason === 'camera_lost') return 'uncertain';
  if (gap.end_source === 'tracking' && gap.identity_confidence < 0.6)
    return 'uncertain';
  return 'reliable';
}

const employees = reactive<EmployeeAllowance[]>([]);

export function useEmployeeAllowance() {
  const isLoading = ref(false);
  const loadError = ref<string | null>(null);
  const lastFetchedAt = ref<Date | null>(null);

  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let activeClientsCount = 0;

  async function fetchAllowanceData() {
    isLoading.value = employees.length === 0;
    try {
      const res = await fetch('/api/attendence/allowance');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.status === 'success' && Array.isArray(json.data)) {
        employees.splice(0, employees.length, ...json.data);
        loadError.value = null;
        lastFetchedAt.value = new Date();
      } else {
        throw new Error('Bentuk respons tidak sesuai kontrak yang diharapkan');
      }
    } catch (err: any) {
      loadError.value = err?.message || 'gagal memuat data jatah istirahat';
    } finally {
      isLoading.value = false;
    }
  }

  onMounted(() => {
    activeClientsCount--;
    if (activeClientsCount <= 0 && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  });

  return {
    employees,
    isLoading,
    loadError,
    lastFetchedAt,
    refetch: fetchAllowanceData
  }
}
