import { onMounted, onUnmounted, reactive, ref } from 'vue';

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
  track_id?: string | number;
  elapsedSeconds?: number;
  elapsedObservedAtMs?: number;
  durationSuffix?: string;
  timerMode?: 'qualifying' | 'counting' | 'paused' | 'limit' | 'unidentified';
  qualificationRemainingSeconds?: number;
  dailyUsedSeconds?: number;
  allowanceSeconds?: number;
}

export interface DetectionFrame {
  atMs: number;
  detections: DetectionItem[];
}

export interface PtsDetectionFrame {
  pts: number;
  streamEpoch: number;
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
  frameBuffer: DetectionFrame[];
  ptsFrameBuffer: PtsDetectionFrame[];
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
  track_id: string | number;
  bbox: BackendBbox;
  confidence: number | null;
  state?: string;
  dwell_time?: number;
  presence_status?: string;
  identity?: string | null;
  similarity?: number;
  session_elapsed?: number;
  is_official_break?: boolean;
  is_qualified?: boolean;
  qualification_remaining_seconds?: number;
  visit_free_time_seconds?: number;
  daily_used_seconds?: number;
  remaining_seconds?: number;
  allowance_seconds?: number;
}

interface ProtocolViewBox {
  track_uuid?: string;
  track_id?: string | number;
  bbox?: [number, number, number, number];
  person_id?: string | null;
  confidence?: number;
  similarity?: number;
  session_elapsed?: number;
  dwell_time?: number;
  presence_status?: string;
  is_official_break?: boolean;
  is_qualified?: boolean;
  qualification_remaining_seconds?: number;
  visit_free_time_seconds?: number;
  daily_used_seconds?: number;
  remaining_seconds?: number;
  allowance_seconds?: number;
}

interface BackendDetectionPayload {
  camera_id: string;
  frame_id?: number;
  at?: string;
  ts?: string;
  pts?: number;
  stream_epoch?: number;
  width?: number;
  height?: number;
  fps?: number;
  people?: BackendPerson[];
  boxes?: ProtocolViewBox[];
}

const DETECTION_BUFFER_WINDOW_MS = 8000;
const MAX_PTS_BUFFER_FRAMES = 20_000;
// Match the direct-player lag tolerance. A larger value would make boxes visibly
// lead/lag the recorded person; a smaller one would flicker during brief GPU dips.
const MAX_DIRECT_PTS_DIFFERENCE_SECONDS = 1.0;
const MAX_CLOCK_DIFFERENCE_MS = 30_000;

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
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
    }
  }
  return best.detections;
}

export function resolveDetectionsAtPts(
  camera: CameraItem,
  targetPts: number,
): DetectionItem[] {
  const buffer = camera.ptsFrameBuffer;
  if (!buffer?.length || !Number.isFinite(targetPts)) return [];

  // Frames arrive in ascending PTS order. Binary search keeps this cheap for
  // long recordings while retaining the full file timeline.
  let low = 0;
  let high = buffer.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (buffer[middle].pts < targetPts) low = middle + 1;
    else high = middle;
  }
  const after = buffer[low];
  const before = low > 0 ? buffer[low - 1] : after;
  const best = Math.abs(before.pts - targetPts) <= Math.abs(after.pts - targetPts)
    ? before
    : after;
  return Math.abs(best.pts - targetPts) <= MAX_DIRECT_PTS_DIFFERENCE_SECONDS
    ? best.detections
    : [];
}

const liveCameras = reactive<CameraItem[]>([]);
const liveStats = reactive<DashboardStats>({
  activeFacilities: 0,
  totalFacilities: 0,
  activeUsers: 0,
  totalUsage: '0s',
  avgSession: '0s',
  exceededDuration: 0,
});

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
      // Detector score from the engine. No fake default: missing stays missing.
      confidence: box.confidence ?? null,
      presence_status:
        box.presence_status ?? (box.person_id ? 'CONFIRMED' : 'TRACKED'),
      session_elapsed: box.session_elapsed ?? box.dwell_time ?? 0,
      is_official_break: box.is_official_break,
      is_qualified: box.is_qualified,
      qualification_remaining_seconds: box.qualification_remaining_seconds,
      visit_free_time_seconds: box.visit_free_time_seconds,
      daily_used_seconds: box.daily_used_seconds,
      remaining_seconds: box.remaining_seconds,
      allowance_seconds: box.allowance_seconds,
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

function detectionStreamUrl(cameraId: string, replay = false): string {
  const configured = import.meta.env.VITE_API_URL as string | undefined;
  const base =
    configured ||
    (window.location.port === '5173'
      ? '/api/detections/stream'
      : 'http://localhost:8000/api/detections/stream');
  const separator = base.includes('?') ? '&' : '?';
  return `${base}${separator}camera_id=${encodeURIComponent(cameraId)}${replay ? '&replay=true' : ''}`;
}

export function useDetectionStream() {
  const isConnected = ref(false);
  const isStreaming = ref(false);
  const lastUpdated = ref<Date | null>(null);
  const connectionError = ref<string | null>(null);

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
          ptsFrameBuffer: [],
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
        const rawConfidence = person.confidence == null ? Number.NaN : Number(person.confidence);
        const confidence = Number.isFinite(rawConfidence)
          ? (rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence)
          : null;
        const elapsed = person.session_elapsed ?? person.dwell_time ?? 0;

        let color: DetectionItem['color'] = 'cyan';
        let warning = false;
        let durationSuffix = '';
        let timerMode: DetectionItem['timerMode'] = 'counting';
        if (person.presence_status === 'LIMIT') {
          color = 'red';
          warning = true;
          durationSuffix = ' (LIMIT REACHED)';
          timerMode = 'limit';
        } else if (person.presence_status === 'WARNING') {
          color = 'amber';
          warning = true;
          durationSuffix = ' (LIMIT NEAR)';
        } else if (person.presence_status === 'CONFIRMED') {
          color = 'emerald';
        } else if (person.presence_status === 'VERIFYING') {
          color = 'cyan';
          timerMode = 'qualifying';
        } else if (person.presence_status === 'OFFICIAL_BREAK') {
          color = 'emerald';
          timerMode = 'paused';
        } else if (person.presence_status === 'UNIDENTIFIED') {
          color = 'cyan';
          timerMode = 'unidentified';
        }

        const qualificationRemaining = finiteNumber(
          person.qualification_remaining_seconds,
        );
        const dailyUsed = finiteNumber(person.daily_used_seconds);
        const allowance = finiteNumber(person.allowance_seconds, 30 * 60);
        let timerText = `Jatah terpakai ${formatDuration(dailyUsed)} / ${formatDuration(allowance)}`;
        if (timerMode === 'qualifying') {
          timerText = `Validasi orang lewat ${Math.ceil(qualificationRemaining)}s`;
        } else if (timerMode === 'paused') {
          timerText = 'Istirahat 12:00–13:00 · timer dijeda';
        } else if (timerMode === 'unidentified') {
          timerText = `Belum dikenali · kunjungan ${formatDuration(finiteNumber(person.visit_free_time_seconds))}`;
        } else if (timerMode === 'limit') {
          timerText = `BATAS TERCAPAI · ${formatDuration(dailyUsed)} / ${formatDuration(allowance)}`;
        }

        return {
          id: person.track_id,
          track_id: person.track_id,
          label: person.identity
            ? `Emp #${person.identity}`
            : `ID #${person.track_id}`,
          sub: person.presence_status || person.state || 'TRACKED',
          conf: confidence == null ? '' : `${Math.round(confidence)}%`,
          extra: timerText,
          elapsedSeconds: finiteNumber(elapsed),
          elapsedObservedAtMs: Date.now(),
          durationSuffix,
          timerMode,
          qualificationRemainingSeconds: qualificationRemaining,
          dailyUsedSeconds: dailyUsed,
          allowanceSeconds: allowance,
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

      if (data.pts != null && Number.isFinite(Number(data.pts))) {
        const pts = Number(data.pts);
        const streamEpoch = finiteNumber(data.stream_epoch);
        const lastPtsFrame = camera.ptsFrameBuffer.at(-1);
        if (
          lastPtsFrame
          && (lastPtsFrame.streamEpoch !== streamEpoch || pts < lastPtsFrame.pts)
        ) {
          camera.ptsFrameBuffer.splice(0);
        }
        camera.ptsFrameBuffer.push({ pts, streamEpoch, detections });
        if (camera.ptsFrameBuffer.length > MAX_PTS_BUFFER_FRAMES) {
          camera.ptsFrameBuffer.splice(
            0,
            camera.ptsFrameBuffer.length - MAX_PTS_BUFFER_FRAMES,
          );
        }
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

  function connectCamera(camera: CameraItem) {
    const cameraId = camera.id;
    if (!cameraId || eventSources.has(cameraId)) return;

    const directMp4 = camera.stream_url?.toLowerCase().split('?', 1)[0].endsWith('.mp4');
    const source = new EventSource(detectionStreamUrl(cameraId, Boolean(directMp4)));
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
    for (const cameraId of cameraIds) {
      const camera = liveCameras.find((item) => item.id === cameraId);
      if (camera) connectCamera(camera);
    }
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
            ptsFrameBuffer: [],
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
    }
  }

  async function fetchStats() {
    try {
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
}
