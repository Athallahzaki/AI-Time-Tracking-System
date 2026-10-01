import { ref, reactive, onMounted, onUnmounted } from 'vue';

export interface ActiveSessionRaw {
  camera_id: string;
  track_id: number;
  identity: string | null;
  similarity: number;
  presence_status: string;
  first_seen: number; // unix epoch seconds
  last_seen: number;
  dwell_time: number;
  session_elapsed: number;
  formatted_duration: string;
}

export interface UnidentifiedAlert {
  key: string; // camera_id + track_id — cukup unik selama proses backend belum restart
  camera_id: string;
  track_id: number;
  session_elapsed: number;
  formatted_duration: string;
  first_seen: number;
}

/**
 * PENTING — sudah dicek langsung ke core/state.py:
 *
 * event_ingestion.py menyimpan event protokol (termasuk kemungkinan
 * person.unidentified_present dari ENGINE_PROTOCOL.md §4.3) ke tabel
 * `protocol_events` lewat save_protocol_event(). Jalur ini TIDAK PERNAH
 * memanggil system_state.record_event().
 *
 * GET /api/attendance/events hanya membaca system_state._event_history,
 * yang cuma diisi lewat record_event() — sejauh ini cuma dipanggil untuk
 * "ManualCorrectionEvent" (lihat routers/attendance.py). Jadi endpoint itu
 * TIDAK AKAN PERNAH menampilkan alert orang tak dikenal.
 *
 * Jalan pintas yang tersedia SEKARANG dan jujur: turunkan dari
 * GET /api/attendance/active, yang sudah membawa `identity` (null kalau
 * belum dikenali) dan `session_elapsed` per track secara real-time.
 *
 * Beda dengan D4 (klasifikasi gap yang jadi dasar sanksi), ambang di sini
 * PRESENTASIONAL SAJA — sekadar memberi tahu HR untuk melihat, bukan
 * keputusan yang punya konsekuensi formal. Karena itu wajar ambang ini
 * hidup sementara di frontend. Begitu backend punya event asli
 * (person.unidentified_present) tersambung ke endpoint apa pun, pindahkan
 * logikanya ke sana dan hapus ALERT_THRESHOLD_SECONDS di bawah.
 */
const ALERT_THRESHOLD_SECONDS = 120; // tentatif — ganti kalau backend punya angka resmi

const alerts = reactive<UnidentifiedAlert[]>([]);

export function useUnidentifiedAlerts() {
  const isLoading = ref(false);
  const loadError = ref<string | null>(null);

  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let activeClientsCount = 0;

  async function fetchActiveSessions() {
    isLoading.value = alerts.length === 0;
    try {
      const res = await fetch('/api/attendance/active');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.status !== 'success' || !Array.isArray(json.sessions)) {
        throw new Error('Bentuk respons /api/attendance/active tidak dikenali');
      }

      const sessions: ActiveSessionRaw[] = json.sessions;
      const nextAlerts: UnidentifiedAlert[] = sessions
        .filter(
          (s) => !s.identity && s.session_elapsed >= ALERT_THRESHOLD_SECONDS,
        )
        .map((s) => ({
          key: `${s.camera_id}_${s.track_id}`,
          camera_id: s.camera_id,
          track_id: s.track_id,
          session_elapsed: s.session_elapsed,
          formatted_duration: s.formatted_duration,
          first_seen: s.first_seen,
        }))
        .sort((a, b) => b.session_elapsed - a.session_elapsed);

      alerts.splice(0, alerts.length, ...nextAlerts);
      loadError.value = null;
    } catch (err: any) {
      loadError.value = err?.message || 'Gagal memuat status kehadiran';
    } finally {
      isLoading.value = false;
    }
  }

  onMounted(() => {
    activeClientsCount++;
    fetchActiveSessions();
    if (!pollTimer) {
      pollTimer = setInterval(fetchActiveSessions, 5000);
    }
  });

  onUnmounted(() => {
    activeClientsCount--;
    if (activeClientsCount <= 0 && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  });

  return { alerts, isLoading, loadError, refetch: fetchActiveSessions };
}
