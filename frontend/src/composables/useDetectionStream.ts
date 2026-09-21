<<<<<<< HEAD
import { onMounted, onUnmounted, reactive, ref } from 'vue';
=======
import { ref, reactive, onMounted, onUnmounted } from 'vue';
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275

export interface DetectionItem {
  id?: string | number;
  label: string;
  sub: string;
  conf: string;
  extra?: string;
  color: 'emerald' | 'amber' | 'red' | 'cyan';
  top: string;
  left: string;
  width: string;
  height: string;
  warning?: boolean;
<<<<<<< HEAD
  track_id?: string | number;
}

=======
  track_id?: number;
}

/**
 * Satu frame deteksi yang sudah dinormalisasi, ditandai waktu kejadiannya.
 * `atMs` dipakai untuk mencari frame yang paling cocok dengan posisi
 * playback video saat ini (lihat resolveDetectionsAt / CameraFeedCard.vue).
 */
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
export interface DetectionFrame {
  atMs: number;
  detections: DetectionItem[];
}

export interface CameraItem {
  id: string;
  code: string;
  name: string;
  stream_url?: string;
  fps: string | number;
  is_running?: boolean;
  active_people?: number;
  detections: DetectionItem[];
<<<<<<< HEAD
=======
  /** Buffer beberapa detik terakhir, dipakai untuk sinkronisasi overlay ke video (bukan ke waktu SSE tiba). */
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
  frameBuffer: DetectionFrame[];
}

export interface DashboardStats {
  activeFacilities: number;
  totalFacilities: number;
  activeUsers: number;
  totalUsage: string;
  avgSession: string;
  exceededDuration: number;
}

interface BackendBbox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface BackendPerson {
<<<<<<< HEAD
  track_id: string | number;
=======
  track_id: number;
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
  bbox: BackendBbox;
  confidence: number;
  state?: string;
  dwell_time?: number;
  presence_status?: string;
  identity?: string | null;
  similarity?: number;
  session_elapsed?: number;
}

<<<<<<< HEAD
interface ProtocolViewBox {
  track_uuid?: string;
  track_id?: string | number;
  bbox?: [number, number, number, number];
  person_id?: string | null;
  confidence?: number;
  similarity?: number;
}

interface BackendDetectionPayload {
  camera_id: string;
  frame_id?: number;
  at?: string;
  ts?: string;
  pts?: number;
  width?: number;
  height?: number;
  fps?: number;
  people?: BackendPerson[];
  boxes?: ProtocolViewBox[];
}

const DETECTION_BUFFER_WINDOW_MS = 8000;
const MAX_CLOCK_DIFFERENCE_MS = 30_000;
=======
interface BackendDetectionPayload {
  camera_id: string;
  frame_id: number;
  /**
   * ISO8601 wall-clock, sama dengan `at` di kontrak `view.frame`
   * (ENGINE_PROTOCOL.md §5) — dipakai menyelaraskan ke EXT-X-PROGRAM-DATE-TIME.
   * Optional untuk sekarang: kalau backend belum mengirimnya, kita fallback
   * ke waktu tiba SSE (kurang presisi, tapi tidak mematahkan apa pun).
   */
  at?: string;
  /** Presentation timestamp dari engine, detik. Belum dipakai di frontend, disiapkan untuk nanti. */
  pts?: number;
  width: number;
  height: number;
  fps: number;
  people: BackendPerson[];
}

/** Seberapa jauh ke belakang kita menyimpan frame — cukup untuk menutupi latensi HLS biasa. */
const DETECTION_BUFFER_WINDOW_MS = 8000;
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
<<<<<<< HEAD
  return `${m}m ${s % 60}s`;
}

export function resolveDetectionsAt(
  camera: CameraItem,
  targetMs: number,
): DetectionItem[] {
  const buffer = camera.frameBuffer;
  if (!buffer?.length) return camera.detections || [];

  let best = buffer[0];
  let bestDiff = Math.abs(best.atMs - targetMs);
  for (let index = 1; index < buffer.length; index++) {
    const difference = Math.abs(buffer[index].atMs - targetMs);
    if (difference < bestDiff) {
      best = buffer[index];
      bestDiff = difference;
=======
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

/**
 * Cari frame deteksi yang atMs-nya paling dekat dengan targetMs.
 * targetMs biasanya "posisi waktu yang sedang tampil di video sekarang",
 * BUKAN "waktu sekarang" — lihat computeTargetMs() di CameraFeedCard.vue.
 */
export function resolveDetectionsAt(camera: CameraItem, targetMs: number): DetectionItem[] {
  const buf = camera.frameBuffer;
  if (!buf || buf.length === 0) return camera.detections || [];

  let best = buf[0];
  let bestDiff = Math.abs(best.atMs - targetMs);
  for (let i = 1; i < buf.length; i++) {
    const diff = Math.abs(buf[i].atMs - targetMs);
    if (diff < bestDiff) {
      best = buf[i];
      bestDiff = diff;
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
    }
  }
  return best.detections;
}

<<<<<<< HEAD
const liveCameras = reactive<CameraItem[]>([]);
=======
// Reactive list of cameras dynamically loaded from backend GET /api/cameras
const liveCameras = reactive<CameraItem[]>([]);

>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
const liveStats = reactive<DashboardStats>({
  activeFacilities: 0,
  totalFacilities: 0,
  activeUsers: 0,
  totalUsage: '0s',
  avgSession: '0s',
  exceededDuration: 0,
});

<<<<<<< HEAD
function finiteNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function protocolBoxesToPeople(
  boxes: ProtocolViewBox[],
  frameWidth: number,
  frameHeight: number,
): BackendPerson[] {
  return boxes.map((box, index) => {
    const raw = Array.isArray(box.bbox) ? box.bbox : [0, 0, 0, 0];
    const normalized = raw.every(
      (value) => Number(value) >= 0 && Number(value) <= 1,
    );
    return {
      track_id: box.track_id ?? box.track_uuid ?? index + 1,
      identity: box.person_id ?? null,
      confidence: box.confidence ?? box.similarity ?? 0.95,
      presence_status: box.person_id ? 'CONFIRMED' : 'TRACKED',
      bbox: {
        x1: finiteNumber(raw[0]) * (normalized ? frameWidth : 1),
        y1: finiteNumber(raw[1]) * (normalized ? frameHeight : 1),
        x2: finiteNumber(raw[2]) * (normalized ? frameWidth : 1),
        y2: finiteNumber(raw[3]) * (normalized ? frameHeight : 1),
      },
    };
  });
}

function eventTimeMs(data: BackendDetectionPayload): number {
  const raw = data.at || data.ts;
  const parsed = raw ? new Date(raw).getTime() : Number.NaN;
  if (!Number.isFinite(parsed)) return Date.now();
  // Fake scenarios have a fixed historical clock while the MP4 plays now.
  return Math.abs(Date.now() - parsed) > MAX_CLOCK_DIFFERENCE_MS
    ? Date.now()
    : parsed;
}

function detectionStreamUrl(cameraId: string): string {
  const configured = import.meta.env.VITE_API_URL as string | undefined;
  const base =
    configured ||
    (window.location.port === '5173'
      ? '/api/detections/stream'
      : 'http://localhost:8000/api/detections/stream');
  return `${base}${base.includes('?') ? '&' : '?'}camera_id=${encodeURIComponent(cameraId)}`;
}

=======
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
export function useDetectionStream() {
  const isConnected = ref(false);
  const isStreaming = ref(false);
  const lastUpdated = ref<Date | null>(null);
  const connectionError = ref<string | null>(null);

<<<<<<< HEAD
  const eventSources = new Map<string, EventSource>();
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let statsPollTimer: ReturnType<typeof setInterval> | null = null;
  let mounted = false;

  function closeCameraStream(cameraId: string) {
    eventSources.get(cameraId)?.close();
    eventSources.delete(cameraId);
  }

  function closeAllStreams() {
    for (const source of eventSources.values()) source.close();
    eventSources.clear();
    isConnected.value = false;
  }

  function handlePayload(rawPayload: string) {
    try {
      const data = JSON.parse(rawPayload) as BackendDetectionPayload;
      if (!data?.camera_id) return;

      isStreaming.value = true;
      lastUpdated.value = new Date();

      let camera = liveCameras.find((item) => item.id === data.camera_id);
      if (!camera) {
        camera = {
          id: data.camera_id,
          code: data.camera_id.toUpperCase(),
          name: data.camera_id,
          stream_url: '',
          fps: data.fps || 0,
          is_running: true,
          active_people: 0,
          detections: [],
          frameBuffer: [],
        };
        liveCameras.push(camera);
      }

      const frameWidth = finiteNumber(data.width, 1920) || 1920;
      const frameHeight = finiteNumber(data.height, 1080) || 1080;
      const people = Array.isArray(data.people)
        ? data.people
        : protocolBoxesToPeople(data.boxes || [], frameWidth, frameHeight);

      const detections: DetectionItem[] = people.map((person) => {
        const bbox = person.bbox || { x1: 0, y1: 0, x2: 0, y2: 0 };
        const x1 = Math.max(0, Math.min(frameWidth, finiteNumber(bbox.x1)));
        const y1 = Math.max(0, Math.min(frameHeight, finiteNumber(bbox.y1)));
        const x2 = Math.max(x1, Math.min(frameWidth, finiteNumber(bbox.x2)));
        const y2 = Math.max(y1, Math.min(frameHeight, finiteNumber(bbox.y2)));
        const rawConfidence = finiteNumber(person.confidence, 0.95);
        const confidence = rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence;
        const elapsed = person.session_elapsed ?? person.dwell_time ?? 0;

        let color: DetectionItem['color'] = 'cyan';
        let warning = false;
        let extra = formatDuration(finiteNumber(elapsed));
        if (person.presence_status === 'LIMIT') {
          color = 'red';
          warning = true;
          extra += ' (LIMIT REACHED)';
        } else if (person.presence_status === 'WARNING') {
          color = 'amber';
          warning = true;
          extra += ' (LIMIT NEAR)';
        } else if (person.presence_status === 'CONFIRMED') {
          color = 'emerald';
        }

        return {
          id: person.track_id,
          track_id: person.track_id,
          label: person.identity
            ? `Emp #${person.identity}`
            : `ID #${person.track_id}`,
          sub: person.presence_status || person.state || 'TRACKED',
          conf: `${Math.round(confidence)}%`,
          extra,
          color,
          warning,
          left: `${((x1 / frameWidth) * 100).toFixed(2)}%`,
          top: `${((y1 / frameHeight) * 100).toFixed(2)}%`,
          width: `${(((x2 - x1) / frameWidth) * 100).toFixed(2)}%`,
          height: `${(((y2 - y1) / frameHeight) * 100).toFixed(2)}%`,
        };
      });

      const atMs = eventTimeMs(data);
      camera.frameBuffer.push({ atMs, detections });
      const cutoff = Date.now() - DETECTION_BUFFER_WINDOW_MS;
      while (camera.frameBuffer.length && camera.frameBuffer[0].atMs < cutoff) {
        camera.frameBuffer.shift();
      }

      camera.detections = detections;
      if (data.fps) camera.fps = data.fps.toFixed(1);
      camera.active_people = detections.length;
      camera.is_running = true;
    } catch (error) {
      console.error('[SSE] Failed to parse detection message:', error);
    }
  }

  function scheduleReconnect() {
    if (!mounted || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      syncCameraStreams();
    }, 3000);
  }

  function connectCamera(cameraId: string) {
    if (!cameraId || eventSources.has(cameraId)) return;

    const source = new EventSource(detectionStreamUrl(cameraId));
    eventSources.set(cameraId, source);
    source.onopen = () => {
      isConnected.value = true;
      connectionError.value = null;
    };
    source.addEventListener('detection', (event: MessageEvent) => {
      handlePayload(event.data);
    });
    source.onmessage = (event: MessageEvent) => handlePayload(event.data);
    source.onerror = () => {
      closeCameraStream(cameraId);
      isConnected.value = eventSources.size > 0;
      connectionError.value = `Detection stream ${cameraId} disconnected`;
      scheduleReconnect();
    };
  }

  function syncCameraStreams() {
    const cameraIds = new Set(liveCameras.map((camera) => camera.id));
    for (const cameraId of eventSources.keys()) {
      if (!cameraIds.has(cameraId)) closeCameraStream(cameraId);
    }
    for (const cameraId of cameraIds) connectCamera(cameraId);
  }

  function connect() {
    closeAllStreams();
    syncCameraStreams();
  }

  async function fetchCameras() {
    try {
      const response = await fetch('/api/cameras');
      if (!response.ok) return;
      const json = await response.json();
      if (json.status !== 'success' || !Array.isArray(json.cameras)) return;

      const backendCameras = json.cameras;
      for (let index = liveCameras.length - 1; index >= 0; index--) {
        if (!backendCameras.some((item: any) => item.id === liveCameras[index].id)) {
          liveCameras.splice(index, 1);
        }
      }

      backendCameras.forEach((backendCamera: any) => {
        let camera = liveCameras.find((item) => item.id === backendCamera.id);
        const running =
          backendCamera.is_running ?? backendCamera.enabled ?? camera?.is_running ?? false;

        if (!camera) {
          camera = {
            id: backendCamera.id,
            code: backendCamera.code || backendCamera.id.toUpperCase(),
            name: backendCamera.name || backendCamera.id,
            stream_url: backendCamera.stream_url || '',
            fps: backendCamera.fps || 0,
            is_running: Boolean(running),
            active_people: backendCamera.active_people || 0,
            detections: [],
            frameBuffer: [],
          };
          liveCameras.push(camera);
        } else {
          camera.name = backendCamera.name || camera.name;
          camera.code = backendCamera.code || camera.code;
          camera.stream_url = backendCamera.stream_url ?? camera.stream_url;
          camera.is_running = Boolean(running);
          if (backendCamera.fps !== undefined) camera.fps = backendCamera.fps;
        }
      });
      syncCameraStreams();
    } catch (error) {
      console.debug('[API] Cameras fetch error:', error);
=======
  let eventSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let statsPollTimer: ReturnType<typeof setInterval> | null = null;
  let activeClientsCount = 0;

  async function fetchCameras() {
    try {
      const res = await fetch('/api/cameras');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && Array.isArray(json.cameras)) {
        const backendCams = json.cameras;

        // Remove cameras no longer in backend config
        for (let i = liveCameras.length - 1; i >= 0; i--) {
          if (!backendCams.some((bc: any) => bc.id === liveCameras[i].id)) {
            liveCameras.splice(i, 1);
          }
        }

        // Add or update cameras
        backendCams.forEach((backendCam: any) => {
          let match = liveCameras.find((c) => c.id === backendCam.id);
          if (!match) {
            match = {
              id: backendCam.id,
              code: backendCam.code || backendCam.id.toUpperCase(),
              name: backendCam.name || backendCam.id,
              stream_url: backendCam.stream_url || '',
              fps: backendCam.fps || 0,
              is_running: backendCam.is_running || false,
              active_people: backendCam.active_people || 0,
              detections: [],
              frameBuffer: [],
            };
            liveCameras.push(match);
          } else {
            match.name = backendCam.name || match.name;
            match.code = backendCam.code || match.code;
            match.stream_url = backendCam.stream_url || match.stream_url;
            match.is_running = backendCam.is_running;
            if (backendCam.fps !== undefined) match.fps = backendCam.fps;
          }
        });
      }
    } catch (err) {
      console.debug('[API] Cameras fetch error:', err);
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
    }
  }

  async function fetchStats() {
    try {
<<<<<<< HEAD
      const response = await fetch('/api/stats');
      if (!response.ok) return;
      const json = await response.json();
      if (json.status === 'success' && json.data) Object.assign(liveStats, json.data);
    } catch (error) {
      console.debug('[API] Stats fetch skipped:', error);
    }
  }

  onMounted(async () => {
    mounted = true;
    await fetchCameras();
    await fetchStats();
    statsPollTimer = setInterval(() => {
      fetchStats();
      fetchCameras();
    }, 5000);
  });

  onUnmounted(() => {
    mounted = false;
    closeAllStreams();
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (statsPollTimer) clearInterval(statsPollTimer);
    reconnectTimer = null;
    statsPollTimer = null;
=======
      const res = await fetch('/api/stats');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        Object.assign(liveStats, json.data);
      }
    } catch (err) {
      console.debug('[API] Stats fetch skipped:', err);
    }
  }

  function connect() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }

    const apiUrl =
      import.meta.env.VITE_API_URL ||
      (window.location.port === '5173'
        ? '/api/detections/stream'
        : 'http://localhost:8000/api/detections/stream');

    try {
      eventSource = new EventSource(apiUrl);

      eventSource.onopen = () => {
        isConnected.value = true;
        connectionError.value = null;
      };

      const handlePayload = (rawPayload: string) => {
        try {
          const data: BackendDetectionPayload = JSON.parse(rawPayload);
          if (!data || !data.camera_id) return;

          isStreaming.value = true;
          lastUpdated.value = new Date();

          let targetCam = liveCameras.find((c) => c.id === data.camera_id);
          if (!targetCam) {
            targetCam = {
              id: data.camera_id,
              code: data.camera_id.toUpperCase(),
              name: data.camera_id,
              stream_url: '',
              fps: data.fps || 0,
              is_running: true,
              active_people: 0,
              detections: [],
              frameBuffer: [],
            };
            liveCameras.push(targetCam);
          }

          const frameW = data.width || 1920;
          const frameH = data.height || 1080;

          // Convert backend detections to frontend percentage coordinates
          // (persentase ini relatif ke SELURUH FRAME SUMBER — lihat
          // videoContentRect di CameraFeedCard.vue untuk pemetaan yang benar
          // ke area video yang benar-benar tampil setelah object-fit).
          const mappedDetections: DetectionItem[] = (data.people || []).map(
            (person) => {
              const bbox = person.bbox || { x1: 0, y1: 0, x2: 0, y2: 0 };

              const x1 = Math.max(0, Math.min(frameW, bbox.x1));
              const y1 = Math.max(0, Math.min(frameH, bbox.y1));
              const x2 = Math.max(x1, Math.min(frameW, bbox.x2));
              const y2 = Math.max(y1, Math.min(frameH, bbox.y2));

              const leftPct = (x1 / frameW) * 100;
              const topPct = (y1 / frameH) * 100;
              const widthPct = ((x2 - x1) / frameW) * 100;
              const heightPct = ((y2 - y1) / frameH) * 100;

              const label = person.identity
                ? `Emp #${person.identity}`
                : `ID #${person.track_id}`;

              const sub = person.presence_status || person.state || 'TRACKED';

              const confVal =
                person.confidence != null
                  ? person.confidence <= 1
                    ? person.confidence * 100
                    : person.confidence
                  : 95;
              const conf = `${Math.round(confVal)}%`;

              const elapsed = person.session_elapsed ?? person.dwell_time ?? 0;
              let extra = formatDuration(elapsed);

              let color: 'emerald' | 'amber' | 'red' | 'cyan' = 'emerald';
              let warning = false;

              if (person.presence_status === 'LIMIT') {
                color = 'red';
                warning = true;
                extra += ' (LIMIT REACHED)';
              } else if (person.presence_status === 'WARNING') {
                color = 'amber';
                warning = true;
                extra += ' (LIMIT NEAR)';
              } else if (person.presence_status === 'CONFIRMED') {
                color = 'emerald';
              } else {
                color = 'cyan';
              }

              return {
                id: person.track_id,
                track_id: person.track_id,
                label,
                sub,
                conf,
                extra,
                color,
                warning,
                left: `${leftPct.toFixed(2)}%`,
                top: `${topPct.toFixed(2)}%`,
                width: `${widthPct.toFixed(2)}%`,
                height: `${heightPct.toFixed(2)}%`,
              };
            }
          );

          // ── Frame buffer untuk sinkronisasi overlay (Bug B) ──────────────
          // Kalau backend belum mengirim `at`, fallback ke waktu tiba SSE.
          // Ini kurang presisi untuk HLS, tapi tidak mematahkan apa pun,
          // dan otomatis membaik begitu backend menambahkan field `at`.
          const atMs = data.at ? new Date(data.at).getTime() : Date.now();

          targetCam.frameBuffer.push({ atMs, detections: mappedDetections });
          const cutoff = Date.now() - DETECTION_BUFFER_WINDOW_MS;
          while (targetCam.frameBuffer.length && targetCam.frameBuffer[0].atMs < cutoff) {
            targetCam.frameBuffer.shift();
          }

          // `detections` tetap dipakai sebagai "state terbaru" untuk hal-hal
          // yang tidak butuh presisi spasial (jumlah orang, label, dwell time).
          // Untuk posisi kotak overlay, komponen video memakai resolveDetectionsAt().
          targetCam.detections = mappedDetections;
          if (data.fps) {
            targetCam.fps = data.fps.toFixed(1);
          }
          targetCam.active_people = mappedDetections.length;
          targetCam.is_running = true;
        } catch (err) {
          console.error('[SSE] Failed to parse detection message:', err);
        }
      };

      eventSource.addEventListener('detection', (event: MessageEvent) => {
        handlePayload(event.data);
      });

      eventSource.onmessage = (event: MessageEvent) => {
        handlePayload(event.data);
      };

      eventSource.onerror = () => {
        isConnected.value = false;
        connectionError.value = 'Disconnected from AI Engine';
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        scheduleReconnect();
      };
    } catch (err: any) {
      connectionError.value = err?.message || 'Failed to initialize EventSource';
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      connect();
    }, 3000);
  }

  onMounted(() => {
    activeClientsCount++;
    fetchCameras();
    fetchStats();
    if (!eventSource) {
      connect();
    }
    if (!statsPollTimer) {
      statsPollTimer = setInterval(() => {
        fetchStats();
        fetchCameras();
      }, 5000);
    }
  });

  onUnmounted(() => {
    activeClientsCount--;
    if (activeClientsCount <= 0) {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (statsPollTimer) {
        clearInterval(statsPollTimer);
        statsPollTimer = null;
      }
    }
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
  });

  return {
    cameras: liveCameras,
    stats: liveStats,
    isConnected,
    isStreaming,
    lastUpdated,
    connectionError,
    reconnect: connect,
    fetchCameras,
    fetchStats,
  };
<<<<<<< HEAD
}
=======
}
>>>>>>> 3c9d63454561bca7e7a76e5ac71f24aea5959275
